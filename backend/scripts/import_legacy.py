"""历史数据导入：批次化、可核对、可回滚。

设计要点：
1. 先建 ImportBatch，再写数据，每行回填 import_batch_id —— 旧数据靠批次标识，不靠时间猜。
2. 按目标表唯一键去重，重复行计入 skipped，不覆盖已有业务改动。
3. 批次 counts 记录逐表 imported / skipped / failed 与导入前后行数，作为数量核对依据。
4. 回滚按批次删除（子表先删），并把批次置为 rolled_back，回滚动作写审计。

用法（backend 目录）：
    .venv\\Scripts\\python.exe scripts\\import_legacy.py --source scripts\\legacy_samples --project-code gz-base --dry-run
    .venv\\Scripts\\python.exe scripts\\import_legacy.py --source scripts\\legacy_samples --project-code gz-base
    .venv\\Scripts\\python.exe scripts\\import_legacy.py --rollback <batch_id>
"""

import argparse
import csv
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models import Channel, ImportBatch, Lead, Project, Question  # noqa: E402
from app.models.enums import (  # noqa: E402
    ChannelCategory,
    ChannelStatus,
    ImportBatchStatus,
    QuestionStatus,
    QuestionType,
)
from app.services.audit import record_audit  # noqa: E402

MAPPING_VERSION = "v1"

# 映射表：旧系统字段 → 目标表字段。文档 docs/历史数据迁移方案.md 与本表保持一致。
MAPPINGS = {
    "questions.csv": {
        "target": "questions",
        "required": ("code", "title"),
        "fields": {"code": "code", "question_text": "title", "qtype": "question_type", "audience": "audience"},
    },
    "channels.csv": {
        "target": "channels",
        "required": ("code", "name"),
        "fields": {"code": "code", "channel_name": "name", "category": "category", "domain": "primary_domain"},
    },
    "leads.csv": {
        "target": "leads",
        "required": ("contact_name",),
        "fields": {
            "contact_name": "contact_name",
            "phone": "contact_phone",
            "wechat": "contact_wechat",
            "course": "interested_course",
            "source": "lead_source",
            "remark": "note",
        },
    },
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle)]


def normalize_question_type(raw: str | None) -> QuestionType:
    return QuestionType.GENERAL if (raw or "").strip().lower() in {"", "general", "通用"} else QuestionType.BRAND


def normalize_category(raw: str | None) -> ChannelCategory:
    value = (raw or "").strip()
    for category in ChannelCategory:
        if value == category.value:
            return category
    return ChannelCategory.CONTENT_PLATFORM


def import_questions(session, project: Project, rows, batch_id, dry_run: bool) -> dict[str, int]:
    stats = {"imported": 0, "skipped": 0, "failed": 0}
    for row in rows:
        code = (row.get("code") or "").strip()
        title = (row.get("question_text") or "").strip()
        if not code or not title:
            stats["failed"] += 1
            continue
        exists = session.scalar(select(Question).where(Question.project_id == project.id, Question.code == code))
        if exists:
            stats["skipped"] += 1
            continue
        if not dry_run:
            session.add(
                Question(
                    project_id=project.id,
                    code=code,
                    title=title,
                    question_type=normalize_question_type(row.get("qtype")),
                    audience=(row.get("audience") or None),
                    priority=100,
                    status=QuestionStatus.DRAFT,
                    current_version_no=1,
                    import_batch_id=batch_id,
                )
            )
        stats["imported"] += 1
    return stats


def import_channels(session, project: Project, rows, batch_id, dry_run: bool) -> dict[str, int]:
    stats = {"imported": 0, "skipped": 0, "failed": 0}
    for row in rows:
        code = (row.get("code") or "").strip()
        name = (row.get("channel_name") or "").strip()
        if not code or not name:
            stats["failed"] += 1
            continue
        exists = session.scalar(select(Channel).where(Channel.project_id == project.id, Channel.code == code))
        if exists:
            stats["skipped"] += 1
            continue
        if not dry_run:
            session.add(
                Channel(
                    project_id=project.id,
                    code=code,
                    name=name,
                    category=normalize_category(row.get("category")),
                    status=ChannelStatus.CANDIDATE,
                    primary_domain=(row.get("domain") or None),
                    import_batch_id=batch_id,
                )
            )
        stats["imported"] += 1
    return stats


def import_leads(session, project: Project, rows, batch_id, dry_run: bool) -> dict[str, int]:
    stats = {"imported": 0, "skipped": 0, "failed": 0}
    for row in rows:
        name = (row.get("contact_name") or "").strip()
        phone = (row.get("phone") or "").strip() or None
        wechat = (row.get("wechat") or "").strip() or None
        if not name:
            stats["failed"] += 1
            continue
        # 线索没有业务唯一键，按手机号/微信号去重；两者都空则视为无法去重、直接导入并计数
        if phone or wechat:
            conditions = [Lead.project_id == project.id]
            if phone:
                conditions.append(Lead.contact_phone == phone)
            if wechat:
                conditions.append(Lead.contact_wechat == wechat)
            if session.scalar(select(Lead).where(*conditions)):
                stats["skipped"] += 1
                continue
        if not dry_run:
            session.add(
                Lead(
                    project_id=project.id,
                    contact_name=name,
                    contact_phone=phone,
                    contact_wechat=wechat,
                    interested_course=(row.get("course") or None),
                    lead_source=(row.get("source") or "legacy_import"),
                    note=(row.get("remark") or None),
                    import_batch_id=batch_id,
                )
            )
        stats["imported"] += 1
    return stats


IMPORTERS = {
    "questions.csv": import_questions,
    "channels.csv": import_channels,
    "leads.csv": import_leads,
}


def count_rows(session, target: str, project_id: uuid.UUID) -> int:
    model = {"questions": Question, "channels": Channel, "leads": Lead}[target]
    return session.scalar(select(func.count()).select_from(model).where(model.project_id == project_id)) or 0


def run_import(args) -> None:
    source = Path(args.source).resolve()
    if not source.is_dir():
        raise SystemExit(f"源目录不存在：{source}")

    session = SessionLocal()
    try:
        project = session.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            raise SystemExit(f"项目不存在：{args.project_code}")

        payload_rows: dict[str, list[dict[str, str]]] = {}
        for filename in MAPPINGS:
            path = source / filename
            if path.exists():
                payload_rows[filename] = read_rows(path)
            else:
                payload_rows[filename] = []

        total_source = sum(len(rows) for rows in payload_rows.values())
        batch = ImportBatch(
            project_id=project.id,
            source_system=args.source_system,
            mapping_version=MAPPING_VERSION,
            status=ImportBatchStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            counts={"source_rows": total_source},
        )
        session.add(batch)
        session.flush()

        before = {mapping["target"]: count_rows(session, mapping["target"], project.id) for mapping in MAPPINGS.values()}
        results: dict[str, dict[str, int]] = {}
        for filename, rows in payload_rows.items():
            mapping = MAPPINGS[filename]
            results[mapping["target"]] = IMPORTERS[filename](
                session, project, rows, batch.id, args.dry_run
            )

        session.flush()
        after = {mapping["target"]: count_rows(session, mapping["target"], project.id) for mapping in MAPPINGS.values()}

        batch.counts = {
            "source_rows": total_source,
            "per_table": results,
            "before": before,
            "after": after,
            "delta": {key: after[key] - before[key] for key in after},
        }
        batch.finished_at = datetime.now(timezone.utc)

        record_audit(
            session,
            project_id=project.id,
            actor_id=None,
            action="legacy_import",
            target_type="import_batch",
            target_id=batch.id,
            payload={"source_system": args.source_system, "mapping_version": MAPPING_VERSION,
                     "dry_run": args.dry_run, "counts": batch.counts},
        )

        if args.dry_run:
            batch.status = ImportBatchStatus.PENDING
            session.rollback()
            print("[dry-run] 未写入任何数据，统计如下：")
            for table, stats in results.items():
                print(f"  {table}: imported={stats['imported']} skipped={stats['skipped']} failed={stats['failed']}")
            print(f"  源数据行数 {total_source}，目标表前后行数 {before} -> {after}")
            return

        batch.status = ImportBatchStatus.COMPLETED
        session.commit()
        print(f"导入完成，批次 id = {batch.id}")
        for table, stats in results.items():
            delta = after[table] - before[table]
            print(f"  {table}: imported={stats['imported']} skipped={stats['skipped']} failed={stats['failed']} 表行数 +{delta}")
        print(f"  源数据行数 {total_source}，核对：导入数 + 跳过数 + 失败数 = "
              f"{sum(s['imported'] + s['skipped'] + s['failed'] for s in results.values())}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_rollback(batch_id: str) -> None:
    session = SessionLocal()
    try:
        batch = session.get(ImportBatch, uuid.UUID(batch_id))
        if batch is None:
            raise SystemExit(f"批次不存在：{batch_id}")
        if batch.status == ImportBatchStatus.ROLLED_BACK:
            print("该批次已回滚，无需重复操作")
            return

        before = {t: count_rows(session, t, batch.project_id) for t in ("questions", "channels", "leads")}
        deleted = {t: 0 for t in before}
        for target in ("leads", "questions", "channels"):
            model = {"questions": Question, "channels": Channel, "leads": Lead}[target]
            result = session.execute(delete(model).where(model.import_batch_id == batch.id))
            deleted[target] = result.rowcount or 0

        after = {t: count_rows(session, t, batch.project_id) for t in before}
        batch.status = ImportBatchStatus.ROLLED_BACK
        batch.rollback_note = f"按批次回滚：删除 {deleted}，回滚前 {before}，回滚后 {after}"
        record_audit(
            session,
            project_id=batch.project_id,
            actor_id=None,
            action="legacy_import_rollback",
            target_type="import_batch",
            target_id=batch.id,
            payload={"deleted": deleted, "before": before, "after": after},
        )
        session.commit()
        print(f"批次 {batch.id} 已回滚：删除 {deleted}；行数 {before} -> {after}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="历史数据导入/回滚")
    parser.add_argument("--source", help="旧数据 CSV 目录")
    parser.add_argument("--project-code", default="gz-base")
    parser.add_argument("--source-system", default="legacy_local")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rollback", help="按批次 id 回滚")
    args = parser.parse_args()

    if args.rollback:
        run_rollback(args.rollback)
        return
    if not args.source:
        raise SystemExit("需要 --source 或 --rollback")
    run_import(args)


if __name__ == "__main__":
    main()
