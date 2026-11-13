"""本地模型 6 题 smoke：临时库建库、迁移、seed、本地适配器采样、读指标。

边界：
- 只接受库名以 `_smoke` 结尾的临时库，启动先 DROP/CREATE，结束默认 DROP；
- 不写正式 `geo` 库，不把本地平台登记进正式 4 平台目录，不改变 24 格基线；
- 本地模型没有联网引用，`citation_share` 仍为 null；hit/miss 只证明链路能走通。

用法（仓库根目录）：
    .\\backend\\.venv\\Scripts\\python.exe backend\\scripts\\local_llm_smoke.py
    .\\backend\\.venv\\Scripts\\python.exe backend\\scripts\\local_llm_smoke.py --keep --json
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
    "postgresql+psycopg://geo:geo_dev@localhost:5433/geo_local_smoke",
)
DEFAULT_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
DEFAULT_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")


def _db_name(database_url: str) -> str:
    name = make_url(database_url).database or ""
    if not name.endswith("_smoke"):
        raise SystemExit(
            f"拒绝操作非 smoke 库：{name!r}。库名必须以 `_smoke` 结尾，避免误碰正式库。"
        )
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
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _drop_database(database_url: str) -> None:
    name = _db_name(database_url)
    with _admin_conn(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=str(cwd), env=env, check=True)


def _run_smoke(args: argparse.Namespace) -> dict[str, Any]:
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

    # 必须在设置 DATABASE_URL 之后再 import app，避免 settings 缓存到正式库。
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
    )
    from app.models.enums import (
        EngineEntryType,
        ProjectStatus,
        QuestionStatus,
        RoundStatus,
        SamplingMode,
        TaskStatus,
    )
    from app.services.local_llm_adapter import LocalLLMAdapter
    from app.services.monitoring_collection import run_pending_tasks
    from app.services.stats import geo_overview

    db = SessionLocal()
    adapter: LocalLLMAdapter | None = None
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
        if not question_rows:
            raise SystemExit("临时库没有 active 题目，seed --technical-baseline 未生效")

        local_engine = AiEngine(
            code="local-ollama-smoke",
            name="本地 Ollama（仅 smoke）",
            vendor="Local",
            supports_search=False,
            supports_citation=False,
            access_note="仅用于本地链路 smoke，不是正式 4 平台，不进入业务基线",
            is_active=True,
        )
        db.add(local_engine)
        db.flush()
        entry = AiEngineEntry(
            engine_id=local_engine.id,
            entry_type=EngineEntryType.API,
            name="Ollama OpenAI 兼容",
            entry_url=args.base_url,
            supports_search=False,
            access_note=f"model={args.model}",
            is_active=True,
        )
        db.add(entry)
        db.flush()

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
            name="本地模型 6 题 smoke",
            is_baseline=False,
            status=RoundStatus.RUNNING,
        )
        db.add(round_row)
        db.flush()

        tasks = [
            MonitoringTask(
                project_id=project.id,
                round_id=round_row.id,
                question_version_id=version.id,
                engine_entry_id=entry.id,
                sampling_no=1,
                sampling_mode=SamplingMode.SEARCH_ON,
                status=TaskStatus.PENDING,
            )
            for _question, version in question_rows
        ]
        db.add_all(tasks)
        db.flush()

        adapter = LocalLLMAdapter(
            db,
            base_url=args.base_url,
            model=args.model,
            api_key=args.api_key,
            timeout_seconds=args.timeout,
        )
        run_result = run_pending_tasks(
            db,
            project_id=project.id,
            round_id=round_row.id,
            adapter=adapter,
            rate_limiter=None,
        )
        db.commit()

        overview = geo_overview(db, project.id, round_id=round_row.id)
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
                "sample_id": str(sample.id),
                "status": getattr(sample.status, "value", str(sample.status)),
                "failure_code": getattr(sample.failure_code, "value", sample.failure_code),
                "failure_note": sample.failure_note,
                "brand_mentioned": sample.brand_mentioned,
                "answer_chars": len(sample.raw_answer or ""),
            }
            for sample, task in sample_rows
        ]
        success = True
        return {
            "database": _db_name(args.database_url),
            "base_url": args.base_url,
            "model": args.model,
            "project_code": project.code,
            "round_id": str(round_row.id),
            "question_count": len(question_rows),
            "task_count": len(tasks),
            "run": run_result,
            "overview": {
                key: overview[key]
                for key in (
                    "valid_answers",
                    "mention_rate",
                    "citation_share",
                    "sov",
                    "prompt_coverage",
                    "freshness_hours",
                    "fresh_24h_rate",
                    "failure_rate",
                    "statement",
                )
            }
            | {
                key: overview["counts"][key]
                for key in (
                    "total_samples",
                    "failed_samples",
                    "active_questions",
                    "covered_questions",
                )
            },
            "samples": samples,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        if adapter is not None:
            adapter.close()
        db.close()
        db_engine.dispose()
        if success and not args.keep:
            _drop_database(args.database_url)
        elif not success:
            print(
                f"冒烟失败，保留临时库 {_db_name(args.database_url)} 供排查；"
                "确认后用 --keep 或手工 DROP。",
                file=sys.stderr,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="本地模型 6 题链路 smoke（临时库）")
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default=os.getenv("LOCAL_LLM_API_KEY", ""))
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--keep", action="store_true", help="保留临时库，便于查样本")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args()

    try:
        result = _run_smoke(args)
    except subprocess.CalledProcessError as exc:
        print(f"子进程失败：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"smoke 失败：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        overview = result["overview"]
        print(f"临时库：{result['database']}（{result['model']}）")
        print(f"题目 {result['question_count']} / 任务 {result['task_count']}")
        print(f"有效回答：{overview['valid_answers']}；失败样本：{overview['failed_samples']}")
        print(f"提及率：{overview['mention_rate']}；引用份额：{overview['citation_share']}")
        print(f"题库覆盖：{overview['prompt_coverage']}；失败率：{overview['failure_rate']}")
        print(overview["statement"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
