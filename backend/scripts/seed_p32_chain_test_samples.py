r"""P32 链路测试轮：写入 24 条明确标注 test_data 的网页人工样本并冻结快照。

只用于验证 P1 链路：pending web_user 任务 → 手工样本 → 证据文件 → 任务 done →
轮次 completed → 统计快照冻结。不替代 seq9 的真实网页复测。

默认把样本置为 `manual_review`，避免 24 条测试回答进入项目正式有效分母；
`raw_response.test_data=true` 与 `note` 保留测试标记。若要看 hit/miss 分桶，
可传 `--sample-status valid`，但应只用于隔离测试项目。

用法（backend 目录）：
    .\.venv\Scripts\python.exe scripts\seed_p32_chain_test_samples.py --json
    .\.venv\Scripts\python.exe scripts\seed_p32_chain_test_samples.py --apply --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.monitoring import create_manual_sample  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
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
from app.models.enums import (  # noqa: E402
    AnswerKind,
    EvidenceFileType,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from app.api.deps import ProjectContext  # noqa: E402
from app.schemas.monitoring import ManualSampleCreate  # noqa: E402
from app.services.audit import record_audit  # noqa: E402
from app.services.monitoring_batch import complete_round, start_round  # noqa: E402

PROJECT_CODE = "gz-base"
ROUND_ID = uuid.UUID("20da3128-6b55-4757-b522-d34453e65709")
ACTOR_USERNAME = "geo_admin"
TEST_MARKER = "【测试数据｜仅验证 P1 链路，不代表真实观测】"


def _task_rows(db, project_id, round_id):
    return db.execute(
        select(MonitoringTask, QuestionVersion, Question, AiEngineEntry, AiEngine)
        .join(QuestionVersion, MonitoringTask.question_version_id == QuestionVersion.id)
        .join(Question, QuestionVersion.question_id == Question.id)
        .join(AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .join(AiEngine, AiEngineEntry.engine_id == AiEngine.id)
        .where(
            MonitoringTask.project_id == project_id,
            MonitoringTask.round_id == round_id,
        )
        .order_by(Question.code, AiEngine.code)
    ).all()


def _answer_text(question: Question, entry: AiEngineEntry, index: int, mention: bool) -> str:
    lines = [
        TEST_MARKER,
        f"平台入口：{entry.name}",
        f"题目：{question.title}",
        f"测试序号：{index + 1}/24",
        "会话：新开独立会话（测试占位）",
        "",
    ]
    if mention:
        lines.extend(
            [
                "回答摘录：在广州做 AI 实训/就业转型，可以关注广州 AI 实训基地的课程与项目制训练；"
                "建议先确认班型、项目方向和结课作品要求。",
                "品牌提及原话：可以关注广州 AI 实训基地的课程与项目制训练。",
            ]
        )
    else:
        lines.extend(
            [
                "回答摘录：广州有多家 AI 培训机构，建议按课程大纲、项目案例、师资和就业服务逐项对比；"
                "本条测试回答未提及目标机构。",
                "品牌提及原话：无",
            ]
        )
    lines.extend(
        [
            "来源数量：1" if index % 3 == 0 else "来源数量：0",
            "备注：该回答为链路测试占位文本，不是网页端真实抓取内容。",
        ]
    )
    return "\n".join(lines)


def _write_evidence(db, *, project_id, sample, task, question, entry, actor_id, apply):
    existing = db.scalar(
        select(func.count(EvidenceFile.id)).where(
            EvidenceFile.project_id == project_id,
            EvidenceFile.sample_id == sample.id,
        )
    )
    if existing:
        return False
    relative = (
        Path("evidence")
        / str(project_id)
        / str(sample.id)
        / "p1_chain_test_transcript.json"
    )
    target = settings.evidence_root / relative
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "test_data": True,
            "purpose": "P1 链路测试，不是真实网页观测证据",
            "project_id": str(project_id),
            "round_id": str(task.round_id),
            "task_id": str(task.id),
            "sample_id": str(sample.id),
            "question_code": question.code,
            "question_title": question.title,
            "entry_name": entry.name,
            "entry_type": entry.entry_type.value,
            "sample_status": sample.status.value,
            "answer_excerpt": (sample.raw_answer or "")[:800],
            "captured_at": (sample.sampled_at or datetime.now(timezone.utc)).isoformat(),
            "disclaimer": "仅验证手工录入、证据挂接和快照冻结链路，不得作为真实运营结论。",
        }
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    digest = hashlib.sha256(target.read_bytes()).hexdigest() if apply else None
    row = EvidenceFile(
        project_id=project_id,
        sample_id=sample.id,
        storage_key=relative.as_posix(),
        file_type=EvidenceFileType.OTHER,
        checksum=digest,
        byte_size=target.stat().st_size if apply else None,
        content_type="application/json",
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="evidence.upload",
        target_type="evidence_file",
        target_id=row.id,
        payload={
            "sample_id": str(sample.id),
            "file_type": row.file_type.value,
            "file_name": relative.name,
            "test_data": True,
            "purpose": "p1_chain_test",
        },
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写库；默认演练并回滚")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--round-id", default=str(ROUND_ID))
    parser.add_argument(
        "--sample-status",
        choices=("manual_review", "valid"),
        default="manual_review",
        help="测试样本落库后的状态；默认 manual_review，避免进入正式分母",
    )
    parser.add_argument("--no-complete", action="store_true", help="不启动/完成轮次")
    args = parser.parse_args()

    round_id = uuid.UUID(args.round_id)
    db = SessionLocal()
    try:
        project = db.scalar(select(Project).where(Project.code == PROJECT_CODE))
        actor = db.scalar(select(User).where(User.username == ACTOR_USERNAME))
        round_row = db.get(MonitoringRound, round_id)
        if not project or not actor or not round_row:
            raise SystemExit("项目、执行人或轮次不存在")
        if round_row.project_id != project.id:
            raise SystemExit("轮次不属于 gz-base 项目")

        ctx = ProjectContext(
            user=actor,
            project=project,
            role=RoleCode.PROJECT_ADMIN,
            permissions=frozenset(),
            is_system_admin=bool(actor.is_system_admin),
        )
        rows = _task_rows(db, project.id, round_id)
        if len(rows) != 24:
            raise SystemExit(f"测试轮应有 24 条任务，实际 {len(rows)}")
        non_manual = [entry for _task, _version, _q, entry, _e in rows if entry.entry_type.value != "web_user"]
        if non_manual:
            raise SystemExit(f"测试轮含非 web_user 任务：{len(non_manual)} 条")

        now = datetime.now(timezone.utc)
        results = []
        for index, (task, _version, question, entry, _engine) in enumerate(rows):
            existing = db.scalar(
                select(MonitoringSample)
                .where(
                    MonitoringSample.project_id == project.id,
                    MonitoringSample.task_id == task.id,
                )
                .order_by(MonitoringSample.attempt_no.desc())
            )
            if existing is not None:
                sample = existing
                created = False
            else:
                mention = index % 4 in (0, 1)
                citation = (
                    [f"https://example.com/geo-p1-chain/{index + 1:02d}"]
                    if index % 3 == 0
                    else []
                )
                payload = ManualSampleCreate(
                    raw_answer=_answer_text(question, entry, index, mention),
                    answer_kind=AnswerKind.ANSWER,
                    sampling_mode=SamplingMode.SEARCH_ON,
                    sampled_at=now - timedelta(minutes=(23 - index) * 3),
                    new_conversation_confirmed=True,
                    brand_mentioned=mention,
                    brand_identified=mention,
                    citation_urls=citation,
                    raw_response={
                        "source": "manual_test",
                        "test_data": True,
                        "purpose": "p1_chain_test",
                        "round_name": round_row.name,
                        "question_code": question.code,
                        "entry_name": entry.name,
                        "entry_type": entry.entry_type.value,
                        "test_sample_status": args.sample_status,
                        "evidence_kind": "json_transcript",
                    },
                    note=(
                        "P1 链路测试数据（2026-11-21），仅验证手工录入/证据/快照，"
                        "不代表真实网页观测；样本置 manual_review，不进入正式分母"
                        if args.sample_status == "manual_review"
                        else "P1 链路测试数据（2026-11-21），仅验证链路，不代表真实观测"
                    ),
                )
                if not args.apply:
                    results.append(
                        {
                            "task_id": str(task.id),
                            "question": question.code,
                            "entry": entry.name,
                            "action": "would_create",
                            "brand_mentioned": mention,
                            "citation_count": len(citation),
                        }
                    )
                    continue
                envelope = create_manual_sample(task.id, payload, ctx, db)
                sample = db.get(MonitoringSample, uuid.UUID(envelope["data"]["sample_id"]))
                created = True

            if sample is None:
                raise SystemExit("样本创建后未找到记录")

            review_changed = False
            if args.apply and args.sample_status == "manual_review" and sample.status != SampleStatus.MANUAL_REVIEW:
                sample.status = SampleStatus.MANUAL_REVIEW
                record_audit(
                    db,
                    project_id=project.id,
                    actor_id=actor.id,
                    action="monitoring.sample_review",
                    target_type="monitoring_sample",
                    target_id=sample.id,
                    payload={
                        "review_status": "manual_review",
                        "test_data": True,
                        "reason": "P1 链路测试样本，不进入正式有效回答分母",
                    },
                )
                review_changed = True

            evidence_added = (
                _write_evidence(
                    db,
                    project_id=project.id,
                    sample=sample,
                    task=task,
                    question=question,
                    entry=entry,
                    actor_id=actor.id,
                    apply=args.apply,
                )
                if args.apply
                else False
            )
            if args.apply:
                db.commit()
            results.append(
                {
                    "task_id": str(task.id),
                    "question": question.code,
                    "entry": entry.name,
                    "sample_id": str(sample.id),
                    "action": "created" if created else "already_sampled",
                    "sample_status": sample.status.value,
                    "review_changed": review_changed,
                    "evidence_added": evidence_added,
                }
            )

        if not args.apply:
            db.rollback()

        summary = {
            "apply": args.apply,
            "project": project.code,
            "round_id": str(round_id),
            "round_name": round_row.name,
            "round_seq": round_row.seq,
            "round_status": round_row.status.value,
            "sample_status_target": args.sample_status,
            "task_count": len(rows),
            "created_samples": sum(1 for row in results if row["action"] == "created"),
            "already_sampled": sum(1 for row in results if row["action"] == "already_sampled"),
            "evidence_added": sum(1 for row in results if row.get("evidence_added")),
            "results": results,
        }

        if args.apply and not args.no_complete:
            counts_rows = db.execute(
                select(MonitoringTask.status, func.count())
                .where(
                    MonitoringTask.project_id == project.id,
                    MonitoringTask.round_id == round_id,
                )
                .group_by(MonitoringTask.status)
            ).all()
            counts = {
                (status.value if hasattr(status, "value") else str(status)): int(count)
                for status, count in counts_rows
            }
            total = sum(counts.values())
            unsettled = total - counts.get(TaskStatus.DONE.value, 0) - counts.get(TaskStatus.FAILED.value, 0)
            summary["task_counts_before_complete"] = counts
            if unsettled:
                summary["complete"] = {"ok": False, "reason": f"仍有 {unsettled} 条未进入 done/failed"}
            else:
                if round_row.status == RoundStatus.PLANNING:
                    start_round(db, project_id=project.id, round_id=round_id)
                    db.flush()
                row, snapshot, task_counts = complete_round(
                    db,
                    project_id=project.id,
                    round_id=round_id,
                    actor_id=actor.id,
                )
                record_audit(
                    db,
                    project_id=project.id,
                    actor_id=actor.id,
                    action="monitoring.round_complete",
                    target_type="monitoring_round",
                    target_id=row.id,
                    payload={
                        "snapshot_id": str(snapshot.id),
                        "snapshot_hash": snapshot.snapshot_hash,
                        "task_counts": task_counts,
                        "test_data": True,
                        "purpose": "p1_chain_test",
                    },
                )
                db.commit()
                summary["complete"] = {
                    "ok": True,
                    "round_status": row.status.value,
                    "task_counts": task_counts,
                    "snapshot_id": str(snapshot.id),
                    "snapshot_hash": snapshot.snapshot_hash,
                    "snapshot_scope": snapshot.scope,
                    "snapshot_metrics": snapshot.metrics,
                }

        db.expire_all()
        task_counts_after = dict(
            (
                (status.value if hasattr(status, "value") else str(status)),
                int(count),
            )
            for status, count in db.execute(
                select(MonitoringTask.status, func.count())
                .where(
                    MonitoringTask.project_id == project.id,
                    MonitoringTask.round_id == round_id,
                )
                .group_by(MonitoringTask.status)
            ).all()
        )
        summary["task_counts_after"] = task_counts_after
        summary["sample_status_counts"] = dict(
            (
                (status.value if hasattr(status, "value") else str(status)),
                int(count),
            )
            for status, count in db.execute(
                select(MonitoringSample.status, func.count())
                .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
                .where(
                    MonitoringSample.project_id == project.id,
                    MonitoringTask.round_id == round_id,
                )
                .group_by(MonitoringSample.status)
            ).all()
        )
        summary["evidence_count"] = int(
            db.scalar(
                select(func.count(EvidenceFile.id))
                .join(MonitoringSample, EvidenceFile.sample_id == MonitoringSample.id)
                .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
                .where(
                    EvidenceFile.project_id == project.id,
                    MonitoringTask.round_id == round_id,
                )
            )
            or 0
        )

        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(
                f"{'APPLY' if args.apply else 'DRY-RUN'} round={summary['round_seq']} "
                f"created={summary['created_samples']} evidence={summary['evidence_added']} "
                f"status={summary['sample_status_target']} complete={summary.get('complete', {}).get('ok')}"
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
