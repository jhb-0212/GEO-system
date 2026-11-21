"""把《应用内搜索人工观测表_测试数据_2026-11-20.xlsx》导入正式库的 seq6 轮次。

用途：只验证“应用内人工采样 -> 样本/引用/证据/轮次”链路，不代表真实观测。
- 4 个纯应用内平台（夸克/微信搜一搜AI/知乎直答/小红书点点）× 6 题 = 24 条测试样本；
- 百度AI搜/秘塔AI搜索/360纳米AI 已有 API 入口，应用内重复任务的 18 格取消；
- 每条样本附测试工作簿为证据文件；
- 轮次以 closed 收口，不伪造 done，也不改动任何真实基线。

运行：backend 目录下
  .venv\\Scripts\\python.exe scripts/import_app_search_test_samples.py --dry-run
  .venv\\Scripts\\python.exe scripts/import_app_search_test_samples.py --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from datetime import date, datetime, time, timezone, timedelta
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.monitoring import create_manual_sample
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import (
    AiEngine,
    AiEngineEntry,
    EvidenceFile,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
    User,
)
from app.models.enums import (
    AnswerKind,
    EvidenceFileType,
    RoleCode,
    RoundStatus,
    SamplingMode,
    TaskStatus,
)
from app.schemas.monitoring import ManualSampleCreate
from app.services.access import ProjectContext
from app.services.audit import record_audit
from app.services.state_machine import ensure_task_transition

PROJECT_ID = uuid.UUID("154640d4-6356-4a1c-8bde-2d511cfb06cd")
ROUND_ID = uuid.UUID("d2a32cf3-cc6b-4c4a-a637-d4a4335de620")
WORKBOOK = Path(
    r"C:\Users\EDY\Desktop\GEO系统开发\应用内搜索人工观测表_测试数据_2026-11-20.xlsx"
)
PURE_APP_PLATFORMS = {"夸克", "微信搜一搜AI", "知乎直答", "小红书点点"}
HYBRID_APP_PLATFORMS = {"百度AI搜", "秘塔AI搜索", "360纳米AI"}
TZ = timezone(timedelta(hours=8))


def rows_from_workbook() -> list[dict]:
    wb = load_workbook(WORKBOOK, read_only=True, data_only=True, keep_links=False)
    try:
        ws = wb["观测记录"]
        headers = [cell for cell in next(ws.iter_rows(min_row=3, max_row=3, values_only=True))]
        rows = []
        for excel_row, values in enumerate(
            ws.iter_rows(min_row=4, max_row=27, values_only=True), start=4
        ):
            item = dict(zip(headers, values))
            rows.append(
                {
                    "excel_row": excel_row,
                    "serial": item.get("序号"),
                    "platform": item.get("平台"),
                    "question_code": item.get("问题编号"),
                    "question_text": item.get("问题原文"),
                    "observed_date": item.get("观测日期"),
                    "observed_time": item.get("观测时间"),
                    "answer_form": item.get("回答形式"),
                    "brand_mentioned_raw": item.get("品牌提及"),
                    "brand_quote": item.get("品牌提及原话/位置"),
                    "competitor_mentioned": item.get("竞品提及"),
                    "competitor_quote": item.get("竞品名称/原话"),
                    "source_urls": item.get("来源 URL/链接"),
                    "source_count": item.get("来源数量"),
                    "answer_length": item.get("回答字数/AI总结"),
                    "evidence_filename": item.get("截图/录屏文件名"),
                    "note": item.get("备注"),
                    "validity": item.get("样本有效性"),
                    "observer": item.get("观测人"),
                }
            )
        return rows
    finally:
        wb.close()


def parse_sampled_at(row: dict) -> datetime:
    d = row["observed_date"]
    t = row["observed_time"]
    if isinstance(d, datetime):
        d = d.date()
    if isinstance(d, str):
        d = date.fromisoformat(d.strip())
    if not isinstance(d, date):
        raise ValueError(f"无法解析观测日期：{d!r}")
    if isinstance(t, time):
        pass
    elif isinstance(t, str):
        t = time.fromisoformat(t)
    else:
        raise ValueError(f"无法解析观测时间：{t!r}")
    return datetime.combine(d, t).replace(tzinfo=TZ)


def parse_bool_tristate(value: object) -> bool | None:
    text = str(value or "").strip()
    if text == "是":
        return True
    if text == "否":
        return False
    if text == "不确定":
        return None
    raise ValueError(f"无法解析是非值：{value!r}")


def split_urls(value: object) -> list[str]:
    if not value:
        return []
    text = str(value).replace("\r", "\n")
    parts = [part.strip() for part in text.split("\n") if part.strip()]
    return [part for part in parts if part.startswith(("http://", "https://"))]


def find_task(db: Session, platform: str, question_code: str) -> MonitoringTask:
    row = db.scalar(
        select(MonitoringTask)
        .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
        .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
        .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
        .join(Question, Question.id == QuestionVersion.question_id)
        .where(
            MonitoringTask.project_id == PROJECT_ID,
            MonitoringTask.round_id == ROUND_ID,
            AiEngine.name == platform,
            Question.code == question_code,
        )
    )
    if row is None:
        raise LookupError(f"找不到任务：{platform} / {question_code}")
    return row


def sample_count(db: Session, task_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count(MonitoringSample.id)).where(
                MonitoringSample.project_id == PROJECT_ID,
                MonitoringSample.task_id == task_id,
            )
        )
        or 0
    )


def ensure_evidence(db: Session, sample: MonitoringSample, actor_id: uuid.UUID) -> bool:
    existing = db.scalar(
        select(func.count(EvidenceFile.id)).where(
            EvidenceFile.project_id == PROJECT_ID,
            EvidenceFile.sample_id == sample.id,
        )
    )
    if existing:
        return False
    relative = (
        Path("evidence")
        / str(PROJECT_ID)
        / str(sample.id)
        / f"{uuid.uuid4().hex}.xlsx"
    )
    target = settings.evidence_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(WORKBOOK, target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    row = EvidenceFile(
        project_id=PROJECT_ID,
        sample_id=sample.id,
        storage_key=relative.as_posix(),
        file_type=EvidenceFileType.ATTACHMENT,
        checksum=digest,
        byte_size=target.stat().st_size,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        project_id=PROJECT_ID,
        actor_id=actor_id,
        action="evidence.upload",
        target_type="evidence_file",
        target_id=row.id,
        payload={
            "sample_id": str(sample.id),
            "file_type": row.file_type.value,
            "file_name": WORKBOOK.name,
            "test_data": True,
        },
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        parser.error("必须指定 --dry-run 或 --apply")
    if not WORKBOOK.is_file():
        raise SystemExit(f"测试工作簿不存在：{WORKBOOK}")
    rows = rows_from_workbook()
    if len(rows) != 24:
        raise SystemExit(f"测试工作簿应有 24 条记录，实际 {len(rows)}")

    db = SessionLocal()
    try:
        project = db.get(Project, PROJECT_ID)
        actor = db.scalar(select(User).where(User.username == "geo_admin"))
        round_row = db.get(MonitoringRound, ROUND_ID)
        if not project or not actor or not round_row:
            raise SystemExit("项目、执行人或轮次不存在")
        ctx = ProjectContext(
            user=actor,
            project=project,
            role=RoleCode.PROJECT_ADMIN,
            permissions=frozenset(),
            is_system_admin=bool(actor.is_system_admin),
        )

        results = []
        for row in rows:
            platform = str(row["platform"])
            if platform not in PURE_APP_PLATFORMS:
                results.append(
                    {
                        "serial": row["serial"],
                        "platform": platform,
                        "action": "skip_non_pure_app",
                    }
                )
                continue
            task = find_task(db, platform, str(row["question_code"]))
            if sample_count(db, task.id) > 0:
                sample = db.scalar(
                    select(MonitoringSample)
                    .where(
                        MonitoringSample.project_id == PROJECT_ID,
                        MonitoringSample.task_id == task.id,
                    )
                    .order_by(MonitoringSample.attempt_no.desc())
                )
                evidence_added = ensure_evidence(db, sample, actor.id) if args.apply else False
                results.append(
                    {
                        "serial": row["serial"],
                        "platform": platform,
                        "question": row["question_code"],
                        "action": "already_sampled",
                        "sample_id": str(sample.id),
                        "evidence_added": evidence_added,
                    }
                )
                continue
            raw_answer = "\n".join(
                [
                    "【测试数据，不代表真实观测结果】",
                    f"平台：{platform}",
                    f"题目：{row['question_code']} {row['question_text']}",
                    f"观测时间：{row['observed_date']} {row['observed_time']}",
                    f"入口路径：{row.get('entry_path') or ''}",
                    f"回答形式：{row['answer_form']}",
                    f"品牌提及：{row['brand_mentioned_raw']}",
                    f"品牌提及原话：{row.get('brand_quote') or '无'}",
                    f"竞品提及：{row.get('competitor_mentioned') or '无'}",
                    f"竞品名称/原话：{row.get('competitor_quote') or '无'}",
                    f"来源数量：{row.get('source_count') or 0}",
                    f"来源：{'; '.join(split_urls(row.get('source_urls'))) or '无'}",
                    f"回答字数：{row.get('answer_length') or ''}",
                    f"备注：{row.get('note') or ''}",
                ]
            )
            payload = ManualSampleCreate(
                raw_answer=raw_answer,
                answer_kind=(
                    AnswerKind.SEARCH_RESULT
                    if str(row["answer_form"]).strip() == "search_result"
                    else AnswerKind.ANSWER
                ),
                sampling_mode=SamplingMode.SEARCH_ON,
                sampled_at=parse_sampled_at(row),
                brand_mentioned=parse_bool_tristate(row["brand_mentioned_raw"]),
                brand_identified=parse_bool_tristate(row["brand_mentioned_raw"]),
                citation_urls=split_urls(row.get("source_urls")),
                raw_response={
                    "source": "manual_test",
                    "test_data": True,
                    "workbook": WORKBOOK.name,
                    "sheet": "观测记录",
                    "excel_row": row["excel_row"],
                    "serial": row["serial"],
                    "platform": platform,
                    "question_code": row["question_code"],
                    "answer_form": row["answer_form"],
                    "source_count": row.get("source_count"),
                    "answer_length": row.get("answer_length"),
                    "evidence_filename": row.get("evidence_filename"),
                    "test_note": row.get("note"),
                },
                note=(
                    "应用内人工观测测试数据（2026-11-20），仅验证模板/链路，"
                    f"不代表真实观测结果；工作簿行 {row['serial']}"
                ),
            )
            if args.dry_run:
                results.append(
                    {
                        "serial": row["serial"],
                        "platform": platform,
                        "question": row["question_code"],
                        "task_id": str(task.id),
                        "task_status": task.status.value,
                        "action": "would_create",
                        "citation_count": len(payload.citation_urls),
                    }
                )
                continue
            envelope = create_manual_sample(task.id, payload, ctx, db)
            sample_id = envelope["data"]["sample_id"]
            sample = db.get(MonitoringSample, uuid.UUID(sample_id))
            evidence_added = ensure_evidence(db, sample, actor.id)
            db.commit()
            results.append(
                {
                    "serial": row["serial"],
                    "platform": platform,
                    "question": row["question_code"],
                    "task_id": str(task.id),
                    "action": "created",
                    "sample_id": sample_id,
                    "status": envelope["data"]["status"],
                    "brand_mentioned": envelope["data"]["brand_mentioned"],
                    "brand_identified": envelope["data"]["brand_identified"],
                    "citation_count": envelope["data"]["citation_count"],
                    "evidence_added": evidence_added,
                }
            )

        # 3 个已有 API 入口的平台：应用内重复任务取消，保留 API 采样为主证据。
        cancelled = []
        for platform in HYBRID_APP_PLATFORMS:
            tasks = db.scalars(
                select(MonitoringTask)
                .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
                .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
                .where(
                    MonitoringTask.project_id == PROJECT_ID,
                    MonitoringTask.round_id == ROUND_ID,
                    AiEngine.name == platform,
                    MonitoringTask.status == TaskStatus.PENDING,
                )
            ).all()
            for task in tasks:
                if args.dry_run:
                    cancelled.append({"task_id": str(task.id), "platform": platform, "action": "would_cancel"})
                    continue
                ensure_task_transition(task.status, TaskStatus.CANCELLED)
                task.status = TaskStatus.CANCELLED
                task.lease_owner = None
                task.lease_expires_at = None
                db.flush()
                record_audit(
                    db,
                    project_id=PROJECT_ID,
                    actor_id=actor.id,
                    action="monitoring.task_cancel",
                    target_type="monitoring_task",
                    target_id=task.id,
                    payload={
                        "reason": "app_search_test_scope_reduced",
                        "note": "该平台已有 API 入口；应用内模式不单列，seq6 不伪造测试样本",
                        "platform": platform,
                    },
                )
                cancelled.append({"task_id": str(task.id), "platform": platform, "action": "cancelled"})

        counts = {
            status: int(count)
            for status, count in db.execute(
                select(MonitoringTask.status, func.count())
                .where(
                    MonitoringTask.project_id == PROJECT_ID,
                    MonitoringTask.round_id == ROUND_ID,
                )
                .group_by(MonitoringTask.status)
            ).all()
        }
        counts = {getattr(status, "value", str(status)): count for status, count in counts.items()}

        if not args.dry_run and round_row.status == RoundStatus.RUNNING:
            round_row.status = RoundStatus.CLOSED
            record_audit(
                db,
                project_id=PROJECT_ID,
                actor_id=actor.id,
                action="monitoring.round_close",
                target_type="monitoring_round",
                target_id=ROUND_ID,
                payload={
                    "reason": "app_search_test_data_chain_closed",
                    "task_counts": counts,
                    "note": "24 条测试样本已入库；18 条已有 API 入口的重复应用内任务取消",
                },
            )
            db.flush()
        db.commit()

        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "workbook": WORKBOOK.name,
                    "rows": len(rows),
                    "created_or_existing": results,
                    "cancelled": cancelled,
                    "task_counts": counts,
                    "round_status": round_row.status.value,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
