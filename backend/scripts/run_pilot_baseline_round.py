"""R1 真实采集基线（试点库专用，拒绝 smoke 库）。

边界：
- 只写项目 `gz-base`（广东省 AI 数字人才就业实训基地 GEO），库名不得以 `_smoke` 结尾；
- 4 个平台 × 6 道活跃题 = 24 格，只走 API 入口，默认每格 1 个样本；
- 只临时收起不在 24 格范围内的启用引擎（baidu_ai_search/kimi/qianwen），生成完立即恢复；
- 真实适配器执行，不注入 FakeEngineAdapter；失败样本保留 failure_code，不补数；
- 不写死结果数字，产物 JSON/CSV 由本次运行生成。

用法（仓库根目录）：
    $env:DATABASE_URL="postgresql+psycopg://geo:geo_dev@localhost:5433/geo_pilot"
    .\\backend\\.venv\\Scripts\\python.exe backend\\scripts\\run_pilot_baseline_round.py \\
        --round-name "R1 真实采集基线 2026-11-27" --json --out GEO_R1_真实基线_2026-11-27.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
TARGET_ENGINES = ("deepseek", "doubao", "wenxin", "yuanbao")
PROJECT_CODE = "gz-base"
BRAND_KEYWORD = "广东省AI数字人才就业实训基地"


def _fail(message: str) -> None:
    print(f"拒绝执行：{message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="R1 真实采集基线（试点库）")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--round-name", required=True)
    parser.add_argument("--project-code", default=PROJECT_CODE)
    parser.add_argument(
        "--engines",
        default=",".join(TARGET_ENGINES),
        help="参与本轮的引擎代码，逗号分隔；单平台复测用 --engines wenxin",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    parser.add_argument("--check-only", action="store_true", help="只校验库/项目/题集/入口与凭据，不建轮、不调用平台")
    args = parser.parse_args()
    engines = tuple(code.strip() for code in args.engines.split(",") if code.strip())
    if not engines:
        _fail("--engines 不能为空")
    unknown = sorted(set(engines) - set(TARGET_ENGINES))
    if unknown:
        _fail(f"--engines 含未知平台 {unknown}；允许 {list(TARGET_ENGINES)}")

    db_name = args.database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    if db_name.endswith("_smoke"):
        _fail(f"当前库 {db_name!r} 是 smoke 库；真实基线必须用试点库")
    if os.environ.get("MONITORING_FAKE_ENGINE_ENABLED", "").strip().lower() in ("1", "true", "yes"):
        _fail("检测到 MONITORING_FAKE_ENGINE_ENABLED；真实基线不允许假引擎")

    # 必须在导入 app.* 之前设置 DATABASE_URL，配置在 import 时读取
    os.environ["DATABASE_URL"] = args.database_url

    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    from sqlalchemy import select, func  # noqa: E402

    from app.db.session import SessionLocal  # noqa: E402
    from app.models import (  # noqa: E402
        AiEngine,
        AiEngineEntry,
        BrandProfile,
        MonitoringCitation,
        MonitoringRound,
        MonitoringSample,
        MonitoringTask,
        Project,
        Question,
        QuestionVersion,
        User,
    )
    from app.models.enums import EngineEntryType, QuestionStatus, RoundStatus, SampleStatus  # noqa: E402
    from app.services import monitoring_batch, monitoring_collection  # noqa: E402

    prefix = args.database_url.rsplit("/", 1)[0]
    print(f"库={db_name} 前缀={prefix}")

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            _fail(f"库 {db_name} 里没有项目 {args.project_code}")
        brand = db.scalar(
            select(BrandProfile).where(
                BrandProfile.project_id == project.id, BrandProfile.is_active.is_(True)
            )
        )
        if brand is None or BRAND_KEYWORD not in (brand.canonical_name or ""):
            _fail(f"项目 {args.project_code} 的品牌档案不是试点品牌：{getattr(brand, 'canonical_name', None)!r}")

        active_questions = db.scalar(
            select(func.count(func.distinct(Question.id)))
            .select_from(Question)
            .join(QuestionVersion, QuestionVersion.question_id == Question.id)
            .where(Question.project_id == project.id, Question.status == QuestionStatus.ACTIVE)
        )
        versioned_questions = db.scalar(
            select(func.count(func.distinct(QuestionVersion.question_id)))
            .select_from(QuestionVersion)
            .join(Question, Question.id == QuestionVersion.question_id)
            .where(Question.project_id == project.id, Question.status == QuestionStatus.ACTIVE)
        )
        if active_questions != 6 or versioned_questions != 6:
            _fail(
                f"活跃题应为 6 道且都有版本，当前 active={active_questions} versioned={versioned_questions}；"
                "题集变动需先评审再跑基线"
            )

        entry_rows = []
        for code in engines:
            entry = db.scalar(
                select(AiEngineEntry)
                .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
                .where(
                    AiEngine.code == code,
                    AiEngine.is_active.is_(True),
                    AiEngineEntry.is_active.is_(True),
                    AiEngineEntry.supports_search.is_(True),
                    AiEngineEntry.entry_type == EngineEntryType.API,
                )
                .order_by(AiEngineEntry.created_at, AiEngineEntry.id)
            )
            if entry is None:
                _fail(f"{code} 没有可用的 API 入口")
            ref = entry.credential_ref or ""
            if not ref or not os.getenv(ref):
                _fail(f"{code} 的凭据引用 {ref!r} 在进程环境中未设置")
            entry_rows.append(entry)

        actor = db.scalar(select(User).where(User.username == "geo_admin")) or db.scalar(select(User))
        if actor is None:
            _fail("库内没有可用的创建人账号")
        actor_id = actor.id

        if args.check_only:
            print(
                json.dumps(
                    {
                        "mode": "check-only",
                        "database": db_name,
                        "project": project.code,
                        "brand": brand.canonical_name,
                        "active_questions": active_questions,
                        "engines": [
                            {
                                "engine": code,
                                "entry": entry.name,
                                "protocol": entry.protocol.value if hasattr(entry.protocol, "value") else str(entry.protocol),
                                "model": entry.model_name,
                                "credential_ref": entry.credential_ref,
                                "credential_set": bool(os.getenv(entry.credential_ref or "")),
                            }
                            for code, entry in zip(engines, entry_rows)
                        ],
                        "all_ready": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        existing_round = db.scalar(
            select(MonitoringRound).where(
                MonitoringRound.project_id == project.id,
                MonitoringRound.name == args.round_name,
            )
        )
        if existing_round is not None and existing_round.status in (RoundStatus.COMPLETED, RoundStatus.CLOSED):
            _fail(f"轮次 {args.round_name!r} 已是 {existing_round.status.value}，不能重复采集")

        # 只在生成任务时临时收起范围外引擎，生成后立即恢复；不改变入口配置
        scope_out = [
            engine
            for engine in db.scalars(
                select(AiEngine).where(AiEngine.is_active.is_(True), AiEngine.code.notin_(engines))
            ).all()
        ]
        for engine in scope_out:
            engine.is_active = False
        db.flush()

        round_row = existing_round
        try:
            if round_row is None:
                round_row = monitoring_batch.create_round(
                    db,
                    project_id=project.id,
                    actor_id=actor_id,
                    name=args.round_name,
                    is_baseline=False,
                    planned_at=datetime.now(UTC),
                )
            batch = monitoring_batch.generate_tasks(
                db,
                project_id=project.id,
                round_id=round_row.id,
                actor_id=actor_id,
                expected_engine_count=len(engines),
                entry_types=[EngineEntryType.API],
                samples_per_cell=1,
            )
        finally:
            for engine in scope_out:
                engine.is_active = True
        db.commit()

        print(json.dumps({"batch": batch}, ensure_ascii=False, indent=2))
        if not batch["complete"]:
            _fail(f"批次不完整：expected={batch['expected_task_count']} generated={batch['generated_task_count']} reason={batch['skipped_reason']}")

        run = monitoring_collection.run_pending_tasks(
            db, project_id=project.id, round_id=round_row.id
        )
        db.commit()

        round_row, snapshot, task_counts = monitoring_batch.complete_round(
            db, project_id=project.id, round_id=round_row.id, actor_id=actor_id
        )
        db.commit()

        # 证据汇总
        engine_metrics = []
        for code in engines:
            rows = db.execute(
                select(MonitoringSample.status, MonitoringSample.brand_mentioned, MonitoringSample.brand_identified, MonitoringSample.brand_recommendation)
                .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
                .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
                .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
                .where(MonitoringTask.round_id == round_row.id, AiEngine.code == code)
            ).all()
            engine_metrics.append(
                {
                    "engine": code,
                    "samples": len(rows),
                    "valid": sum(1 for r in rows if r[0] in (SampleStatus.HIT, SampleStatus.MISS)),
                    "mentioned": sum(1 for r in rows if r[1]),
                    "identified": sum(1 for r in rows if r[2]),
                    "recommended": sum(1 for r in rows if r[3]),
                    "failed": sum(1 for r in rows if r[0] == SampleStatus.FAILED),
                }
            )

        details = db.execute(
            select(
                AiEngine.code,
                Question.code,
                MonitoringTask.id,
                MonitoringSample.id,
                MonitoringSample.status,
                MonitoringSample.brand_mentioned,
                MonitoringSample.answer_kind,
                func.length(MonitoringSample.raw_answer),
                MonitoringSample.latency_ms,
                MonitoringSample.failure_code,
                MonitoringSample.sampled_at,
            )
            .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
            .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
            .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
            .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
            .join(Question, Question.id == QuestionVersion.question_id)
            .where(MonitoringTask.round_id == round_row.id)
            .order_by(AiEngine.code, Question.code)
        ).all()

        citation_counts = dict(
            db.execute(
                select(MonitoringCitation.sample_id, func.count())
                .where(MonitoringCitation.project_id == project.id)
                .group_by(MonitoringCitation.sample_id)
            ).all()
        )

        summary = {
            "mode": "real-pilot-r1" if "R1" in args.round_name else "real-pilot-round",
            "round_id": str(round_row.id),
            "round_name": round_row.name,
            "project_code": project.code,
            "database": db_name,
            "is_baseline": round_row.is_baseline,
            "completed_at": datetime.now(UTC).isoformat(),
            "batch": batch,
            "run": run,
            "task_counts": task_counts,
            "by_engine": engine_metrics,
            "samples": [
                {
                    "engine": row[0],
                    "question": row[1],
                    "task_id": str(row[2]),
                    "sample_id": str(row[3]),
                    "status": str(row[4]).split(".")[-1],
                    "brand_mentioned": bool(row[5]),
                    "answer_kind": row[6],
                    "answer_chars": row[7],
                    "latency_ms": row[8],
                    "failure_code": row[9],
                    "sampled_at": row[10].isoformat() if row[10] else None,
                    "citations": int(citation_counts.get(row[3], 0)),
                }
                for row in details
            ],
            "boundary": (
                f"真实 {len(engines)} 平台（{'/'.join(engines)}）× 6 题 × 1 样本；只走 API 入口；"
                "失败保留 failure_code，不补数。元宝是检索结果，不是生成回答，提及率必须分平台读。"
                "本轮为本机试点库 geo_pilot 的人工采集轮，不是生产库结论。"
            ),
        }

        text = json.dumps(summary, ensure_ascii=False, indent=2)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n", encoding="utf-8")
        if args.csv:
            args.csv.parent.mkdir(parents=True, exist_ok=True)
            with args.csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(summary["samples"][0].keys()))
                writer.writeheader()
                writer.writerows(summary["samples"])
        print(text if args.json else json.dumps({k: summary[k] for k in ("round_id", "task_counts", "by_engine")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
