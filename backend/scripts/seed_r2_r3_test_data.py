"""在独立测试库灌入 R2/R3 两轮合成数据，只验证链路，不作业务证据。

边界：
- 库名必须以 `_test` 结尾，拒绝 `geo_pilot` / `geo` / 生产库；
- 项目 `gz-base`，4 个 API 入口 × 6 道 active 题 = 每轮 24 格；
- 每条任务 1 个样本、2 条 `example.com` 引用、1 条成功执行尝试；
- 所有样本 `sampling_context.synthetic=true`，原始回答带「测试数据」前缀；
- R2 合成提及 6/24，R3 合成提及 5/24，仅用于验证轮次差异，不是平台结论。

用法（backend 目录）：
    .\\backend\\.venv\\Scripts\\python.exe backend\\scripts\\seed_r2_r3_test_data.py ^
        --database-url "postgresql+psycopg://geo:geo_dev@localhost:5433/geo_r2r3_test" --apply --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_CODE = "gz-base"
ENGINES = ("deepseek", "doubao", "wenxin", "yuanbao")
CST = timezone(timedelta(hours=8))


ROUNDS = (
    {
        "name": "R2 测试数据（合成） 2026-11-30",
        "planned_at": datetime(2026, 11, 30, 10, 0, tzinfo=CST),
        "hits": {"Q01": set(ENGINES), "Q02": {"deepseek", "doubao"}, "Q05": {"deepseek"}},
    },
    {
        "name": "R3 测试数据（合成） 2026-12-03",
        "planned_at": datetime(2026, 12, 3, 10, 0, tzinfo=CST),
        "hits": {"Q01": set(ENGINES), "Q02": {"deepseek"}, "Q04": {"doubao"}},
    },
)


def main() -> int:
    parser = argparse.ArgumentParser(description="R2/R3 合成测试数据（独立测试库）")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    db_name = args.database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not db_name.endswith("_test"):
        raise SystemExit(f"拒绝执行：库 {db_name!r} 不是独立测试库（必须以 _test 结尾）")

    os.environ["DATABASE_URL"] = args.database_url
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    from sqlalchemy import select  # noqa: E402

    from app.db.session import SessionLocal  # noqa: E402
    from app.models import (  # noqa: E402
        AiEngine,
        AiEngineEntry,
        MonitoringCitation,
        MonitoringExecutionAttempt,
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
        AttemptStatus,
        CitationPageType,
        CitationReviewStatus,
        CitationUsage,
        EngineEntryType,
        QuestionStatus,
        RoundStatus,
        SampleStatus,
        SamplingMode,
        SourceCategory,
        TaskStatus,
    )
    from app.services.monitoring_batch import create_round  # noqa: E402

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == PROJECT_CODE))
        if project is None:
            raise SystemExit(f"项目不存在：{PROJECT_CODE}")
        actor = db.scalar(select(User).where(User.username == "geo_admin", User.is_active.is_(True)))
        if actor is None:
            raise SystemExit("缺少启用账号 geo_admin")

        versions = db.execute(
            select(Question, QuestionVersion)
            .join(
                QuestionVersion,
                (QuestionVersion.question_id == Question.id)
                & (QuestionVersion.version_no == Question.current_version_no),
            )
            .where(
                Question.project_id == project.id,
                Question.status == QuestionStatus.ACTIVE,
                QuestionVersion.project_id == project.id,
            )
            .order_by(Question.priority, Question.code)
        ).all()
        if len(versions) != 6:
            raise SystemExit(f"预期 6 道 active 题，实际 {len(versions)}")

        entries = db.execute(
            select(AiEngine, AiEngineEntry)
            .join(AiEngineEntry, AiEngineEntry.engine_id == AiEngine.id)
            .where(
                AiEngine.code.in_(ENGINES),
                AiEngine.is_active.is_(True),
                AiEngineEntry.entry_type == EngineEntryType.API,
                AiEngineEntry.is_active.is_(True),
            )
            .order_by(AiEngine.code)
        ).all()
        by_code = {engine.code: (engine, entry) for engine, entry in entries}
        missing = [code for code in ENGINES if code not in by_code]
        if missing:
            raise SystemExit(f"缺少启用的 API 入口：{missing}")

        results = []
        for spec in ROUNDS:
            existing = db.scalar(
                select(MonitoringRound).where(
                    MonitoringRound.project_id == project.id,
                    MonitoringRound.name == spec["name"],
                )
            )
            if existing is not None:
                results.append(
                    {
                        "round": spec["name"],
                        "round_id": str(existing.id),
                        "action": "skip-exists",
                        "status": existing.status.value,
                        "tasks": db.query(MonitoringTask).filter(MonitoringTask.round_id == existing.id).count(),
                        "samples": db.query(MonitoringSample)
                        .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
                        .filter(MonitoringTask.round_id == existing.id)
                        .count(),
                    }
                )
                continue

            round_row = create_round(
                db,
                project_id=project.id,
                actor_id=actor.id,
                name=spec["name"],
                is_baseline=False,
                planned_at=spec["planned_at"],
            )
            task_count = 0
            sample_count = 0
            citation_count = 0
            hit_count = 0

            for qcode, version in ((q.code, v) for q, v in versions):
                for engine_code in ENGINES:
                    engine, entry = by_code[engine_code]
                    trace_id = uuid.uuid4().hex
                    mentioned = engine_code in spec["hits"].get(qcode, set())
                    task = MonitoringTask(
                        project_id=project.id,
                        round_id=round_row.id,
                        question_version_id=version.id,
                        engine_entry_id=entry.id,
                        sampling_no=1,
                        trace_id=trace_id,
                        sampling_mode=SamplingMode.SEARCH_ON,
                        status=TaskStatus.DONE,
                        planned_at=spec["planned_at"],
                        created_by=actor.id,
                    )
                    db.add(task)
                    db.flush()
                    task_count += 1

                    db.add(
                        MonitoringExecutionAttempt(
                            project_id=project.id,
                            task_id=task.id,
                            attempt_no=1,
                            worker_id="synthetic-test",
                            status=AttemptStatus.SUCCEEDED,
                            started_at=spec["planned_at"],
                            finished_at=spec["planned_at"] + timedelta(seconds=3),
                        )
                    )

                    answer = (
                        f"【测试数据】{engine.name} 对 {qcode} 的回答：推荐广东省AI数字人才就业实训基地（合成，仅用于链路验证）。"
                        if mentioned
                        else f"【测试数据】{engine.name} 对 {qcode} 的回答：未提及目标品牌（合成，仅用于链路验证）。"
                    )
                    sample = MonitoringSample(
                        project_id=project.id,
                        task_id=task.id,
                        attempt_no=1,
                        trace_id=trace_id,
                        status=SampleStatus.HIT if mentioned else SampleStatus.MISS,
                        sampled_at=spec["planned_at"],
                        finished_at=spec["planned_at"] + timedelta(seconds=3),
                        sampling_mode=SamplingMode.SEARCH_ON,
                        conversation_id=uuid.uuid4().hex,
                        conversation_mode="stateless",
                        raw_answer=answer,
                        raw_response={"synthetic": True, "dataset": "r2r3-test", "engine": engine_code},
                        latency_ms=3000,
                        prompt_tokens=120,
                        completion_tokens=80,
                        total_tokens=200,
                        gateway_version="synthetic-test-v1",
                        brand_mentioned=mentioned,
                        brand_identified=mentioned,
                        brand_recommendation=mentioned,
                        recommendation_reason="synthetic-test" if mentioned else None,
                        entity_mention_count=1 if mentioned else 0,
                        brand_match_kind="exact" if mentioned else None,
                        brand_match_term="广东省AI数字人才就业实训基地" if mentioned else None,
                        brand_match_evidence=answer if mentioned else None,
                        matcher_version="synthetic-test",
                        answer_kind=AnswerKind.ANSWER,
                        engine_model="synthetic-test",
                        model_version="test-v1",
                        country_code="CN",
                        language="zh-CN",
                        sampling_context={
                            "synthetic": True,
                            "dataset": "r2r3-test",
                            "note": "仅验证链路，不作业务证据",
                            "engine": engine_code,
                            "question": qcode,
                        },
                    )
                    db.add(sample)
                    db.flush()
                    sample_count += 1
                    hit_count += 1 if mentioned else 0

                    for idx in range(1, 3):
                        db.add(
                            MonitoringCitation(
                                project_id=project.id,
                                sample_id=sample.id,
                                trace_id=trace_id,
                                raw_url=f"https://example.com/r2r3/{round_row.seq}/{engine_code}/{qcode}/{idx}",
                                normalized_url=f"https://example.com/r2r3/{round_row.seq}/{engine_code}/{qcode}/{idx}",
                                domain="example.com",
                                title=f"测试引用 {qcode} {engine_code} #{idx}",
                                snippet="合成引用，仅用于验证引用表与计数链路。",
                                site_name="example.com",
                                page_type=CitationPageType.ARTICLE,
                                page_type_source="rule",
                                source_category=SourceCategory.REFERENCE,
                                review_status=CitationReviewStatus.AUTO,
                                citation_usage=CitationUsage.CITED,
                                is_brand_related=mentioned,
                            )
                        )
                        citation_count += 1

            round_row.status = RoundStatus.COMPLETED
            db.flush()
            results.append(
                {
                    "round": spec["name"],
                    "round_id": str(round_row.id),
                    "seq": round_row.seq,
                    "action": "create",
                    "status": round_row.status.value,
                    "tasks": task_count,
                    "samples": sample_count,
                    "citations": citation_count,
                    "synthetic_hits": hit_count,
                }
            )

        if args.apply:
            db.commit()
        else:
            db.rollback()

    payload = {"database": db_name, "applied": bool(args.apply), "project": PROJECT_CODE, "rounds": results}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for row in results:
            print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
