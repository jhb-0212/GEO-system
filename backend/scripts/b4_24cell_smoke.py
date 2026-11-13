"""B4 24 格链路复跑：4 个入口 × 6 题，真实调用 OpenAI-compatible 模型。

边界：
- 这是“24 格链路/落库复跑”，不是 DeepSeek / 豆包 / 文心 / 元宝的 4 平台业务基线；
- 4 个入口全部指向同一个本地模型时，结果只能证明自动采集链能落 hit/miss，不能证明平台 GEO 表现；
- 临时库必须 `_smoke` 结尾，默认跑完 DROP；`--keep` 保留供查样本。

用法（仓库根目录）：
    .\\backend\\.venv\\Scripts\\python.exe backend\\scripts\\b4_24cell_smoke.py --keep --json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
DEFAULT_DATABASE_URL = os.getenv(
    "LOCAL_SMOKE_DATABASE_URL",
    "postgresql+psycopg://geo:geo_dev@localhost:5433/geo_b4_24cell_smoke",
)
DEFAULT_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
DEFAULT_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")
EXPECTED_ENGINES = 4


def _db_name(database_url: str) -> str:
    name = make_url(database_url).database or ""
    if not name.endswith("_smoke"):
        raise SystemExit(f"拒绝操作非 smoke 库：{name!r}")
    return name


def _admin_conn(database_url: str):
    url = make_url(database_url)
    return psycopg.connect(
        host=url.host or "localhost",
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        dbname="postgres",
        autocommit=True,
    )


def _recreate_database(database_url: str) -> None:
    name = _db_name(database_url)
    with _admin_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _drop_database(database_url: str) -> None:
    name = _db_name(database_url)
    with _admin_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=str(cwd), env=env, check=True)


def _run_baseline(args: argparse.Namespace) -> dict[str, Any]:
    _recreate_database(args.database_url)
    env = os.environ.copy()
    env["DATABASE_URL"] = args.database_url
    env.setdefault("SEED_ADMIN_PASSWORD", "geo-admin-dev")
    _run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
    )
    _run(
        [sys.executable, "scripts/seed.py", "--technical-baseline"],
        cwd=BACKEND_DIR,
        env=env,
    )

    os.environ["DATABASE_URL"] = args.database_url
    from app.db.session import SessionLocal, engine as db_engine
    from app.models import (
        AiEngine,
        AiEngineEntry,
        MonitoringRound,
        MonitoringSample,
        MonitoringTask,
        Project,
        Question,
        QuestionVersion,
        User,
    )
    from app.models.enums import (
        EngineEntryType,
        EngineProtocol,
        ProjectStatus,
        QuestionStatus,
        RoundStatus,
    )
    from app.services.monitoring_batch import generate_tasks
    from app.services.monitoring_collection import run_pending_tasks
    from app.services.stats import geo_overview, by_engine, by_question

    db = SessionLocal()
    success = False
    try:
        project = db.scalar(
            select(Project).where(
                Project.code == "gz-base",
                Project.status == ProjectStatus.ACTIVE,
            )
        )
        if project is None:
            raise SystemExit("临时库没有 gz-base 项目，seed 未生效")

        question_rows = db.execute(
            select(Question, QuestionVersion)
            .join(
                QuestionVersion,
                (QuestionVersion.question_id == Question.id)
                & (QuestionVersion.version_no == Question.current_version_no),
            )
            .where(
                Question.project_id == project.id,
                QuestionVersion.project_id == project.id,
                Question.status == QuestionStatus.ACTIVE,
            )
            .order_by(Question.code)
        ).all()
        if len(question_rows) != 6:
            raise SystemExit(f"预期 6 道 active 题，实际 {len(question_rows)}")

        engine_rows = db.execute(
            select(AiEngine, AiEngineEntry)
            .join(AiEngineEntry, AiEngineEntry.engine_id == AiEngine.id)
            .where(AiEngine.is_active.is_(True), AiEngineEntry.is_active.is_(True))
            .order_by(AiEngine.code)
        ).all()
        picked: dict[uuid.UUID, tuple[AiEngine, AiEngineEntry]] = {}
        for engine, entry in engine_rows:
            picked.setdefault(engine.id, (engine, entry))
        if len(picked) != EXPECTED_ENGINES:
            raise SystemExit(f"预期 {EXPECTED_ENGINES} 个启用平台，实际 {len(picked)}")

        for engine, entry in picked.values():
            entry.entry_type = EngineEntryType.API
            entry.entry_url = args.base_url
            entry.protocol = EngineProtocol.OPENAI_COMPATIBLE
            entry.model_name = args.model
            entry.credential_ref = None
            entry.is_active = True
            entry.access_note = "B4 24 格链路复跑；本地模型，不是平台业务基线"
        db.flush()

        actor_id = db.scalar(select(User.id).where(User.is_system_admin.is_(True)).limit(1))
        if actor_id is None:
            raise SystemExit("临时库没有系统管理员，无法写批量审计")

        max_seq = (
            db.scalar(
                select(func.max(MonitoringRound.seq)).where(
                    MonitoringRound.project_id == project.id
                )
            )
            or 0
        )
        round_row = MonitoringRound(
            project_id=project.id,
            seq=int(max_seq) + 1,
            name="B4 24 格本地链路复跑",
            is_baseline=False,
            status=RoundStatus.RUNNING,
        )
        db.add(round_row)
        db.flush()

        batch = generate_tasks(
            db,
            project_id=project.id,
            round_id=round_row.id,
            actor_id=actor_id,
        )
        run_result = run_pending_tasks(
            db,
            project_id=project.id,
            round_id=round_row.id,
            adapter=None,
            rate_limiter=None,
        )
        db.commit()

        sample_rows = db.execute(
            select(MonitoringSample, MonitoringTask)
            .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
            .where(
                MonitoringSample.project_id == project.id,
                MonitoringTask.round_id == round_row.id,
            )
            .order_by(MonitoringTask.created_at, MonitoringSample.attempt_no)
        ).all()
        samples = [
            {
                "task_id": str(task.id),
                "status": getattr(sample.status, "value", str(sample.status)),
                "failure_code": getattr(sample.failure_code, "value", sample.failure_code),
                "brand_mentioned": sample.brand_mentioned,
                "engine_entry_id": str(task.engine_entry_id),
                "question_version_id": str(task.question_version_id),
                "answer_chars": len(sample.raw_answer or ""),
            }
            for sample, task in sample_rows
        ]
        status_counts = {
            status: sum(1 for row in samples if row["status"] == status)
            for status in ("hit", "miss", "failed", "pending", "running", "manual_review")
        }

        overview = geo_overview(db, project.id, round_id=round_row.id)
        success = True
        return {
            "database": _db_name(args.database_url),
            "base_url": args.base_url,
            "model": args.model,
            "round_id": str(round_row.id),
            "question_count": len(question_rows),
            "engine_count": len(picked),
            "batch": batch,
            "run": run_result,
            "status_counts": status_counts,
            "by_engine": by_engine(db, project.id, round_id=round_row.id),
            "by_question": by_question(db, project.id, round_id=round_row.id),
            "overview": overview,
            "samples": samples,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        db_engine.dispose()
        if success and not args.keep:
            _drop_database(args.database_url)
        elif not success:
            print(
                f"复跑失败，保留临时库 {_db_name(args.database_url)} 供排查；确认后手工 DROP。",
                file=sys.stderr,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="B4 24 格链路复跑（临时库）")
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--keep", action="store_true", help="保留临时库，便于查样本")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args()

    try:
        result = _run_baseline(args)
    except subprocess.CalledProcessError as exc:
        print(f"子进程失败：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"复跑失败：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        overview = result["overview"]
        print(f"临时库：{result['database']}（{result['model']}）")
        print(f"题目 {result['question_count']} / 平台 {result['engine_count']}")
        print(f"批量：{result['batch']}")
        print(f"状态：{result['status_counts']}")
        print(f"有效回答：{overview['valid_answers']}；失败样本：{overview['counts']['failed_samples']}")
        print(f"提及率：{overview['mention_rate']}；引用份额：{overview['citation_share']}")
        print(overview["statement"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
