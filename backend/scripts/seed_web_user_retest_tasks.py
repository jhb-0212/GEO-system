r"""创建 P32 网页端同题复测轮次（4 个 web_user 入口 × 6 题 = 24 任务）。

这个轮次只包含 seq5 基线同款的 4 个网页用户端入口，任务以 pending 建出，
等待运营在真实网页端逐题新开会话、留证并录入。它不自动执行，也不混入 API
或应用内任务。

人工专用轮次保持 `planning`：调度器虽会扫描 planning/running，但
`plan_round_tasks` 检测到 `web_user` 人工任务后返回 `manual_round`，不会
自动补 API 任务、也不会发 outbox；手测录入不依赖 running，24 条完成/失败后
再手工转 completed。

用法（backend 目录）：
    .\.venv\Scripts\python.exe scripts\seed_web_user_retest_tasks.py --json
    .\.venv\Scripts\python.exe scripts\seed_web_user_retest_tasks.py --apply --json
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AiEngine,
    AiEngineEntry,
    MonitoringRound,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
    User,
)
from app.models.enums import (  # noqa: E402
    EngineEntryType,
    QuestionStatus,
    RoundStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.audit import record_audit  # noqa: E402
from app.services.monitoring_batch import create_round  # noqa: E402

ENGINE_CODES = ("deepseek", "doubao", "wenxin", "yuanbao")


def _active_versions(db, project_id):
    return db.execute(
        select(Question, QuestionVersion)
        .join(
            QuestionVersion,
            (QuestionVersion.question_id == Question.id)
            & (QuestionVersion.version_no == Question.current_version_no),
        )
        .where(
            Question.project_id == project_id,
            Question.status == QuestionStatus.ACTIVE,
            QuestionVersion.project_id == project_id,
        )
        .order_by(Question.priority, Question.code)
    ).all()


def _web_user_entries(db):
    rows = db.execute(
        select(AiEngine, AiEngineEntry)
        .join(AiEngineEntry, AiEngineEntry.engine_id == AiEngine.id)
        .where(
            AiEngine.code.in_(ENGINE_CODES),
            AiEngine.is_active.is_(True),
            AiEngineEntry.entry_type == EngineEntryType.WEB_USER,
            AiEngineEntry.is_active.is_(True),
        )
        .order_by(AiEngine.code)
    ).all()
    by_code = {engine.code: (engine, entry) for engine, entry in rows}
    missing = [code for code in ENGINE_CODES if code not in by_code]
    if missing:
        raise SystemExit(f"缺少启用的 web_user 入口：{', '.join(missing)}")
    return [by_code[code] for code in ENGINE_CODES]


def run(*, apply: bool, project_code: str, round_name: str | None, actor_username: str) -> dict:
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == project_code))
        if project is None:
            raise SystemExit(f"项目不存在：{project_code}")
        actor = db.scalar(select(User).where(User.username == actor_username))
        if actor is None or not actor.is_active:
            raise SystemExit(f"操作账号不存在或已停用：{actor_username}")

        versions = _active_versions(db, project.id)
        if len(versions) != 6:
            raise SystemExit(f"预期 6 个 active 题目版本，实际 {len(versions)}")
        entries = _web_user_entries(db)
        if len(entries) != 4:
            raise SystemExit(f"预期 4 个 web_user 入口，实际 {len(entries)}")

        name = round_name or "P32 网页端同题复测（v2 人工专用，2026-11-21）"
        round_row = db.scalar(
            select(MonitoringRound).where(
                MonitoringRound.project_id == project.id,
                MonitoringRound.name == name,
            )
        )
        created_round = False
        if round_row is None:
            round_row = create_round(
                db,
                project_id=project.id,
                actor_id=actor.id,
                name=name,
                is_baseline=False,
                planned_at=datetime.now(timezone.utc),
            )
            created_round = True
        elif round_row.status in (RoundStatus.COMPLETED, RoundStatus.CLOSED):
            raise SystemExit(f"同名轮次已完成/关闭，不能追加任务：{name}")
        elif round_row.status != RoundStatus.PLANNING:
            raise SystemExit(
                f"同名轮次已是 {round_row.status.value}，不是人工专用 planning 轮次：{name}"
            )

        existing = {
            (task.question_version_id, task.engine_entry_id, task.sampling_no): task
            for task in db.scalars(
                select(MonitoringTask).where(MonitoringTask.round_id == round_row.id)
            ).all()
        }
        expected_entry_ids = {entry.id for _engine, entry in entries}
        other_tasks = sum(
            1 for task in existing.values() if task.engine_entry_id not in expected_entry_ids
        )
        if other_tasks:
            raise SystemExit(f"同名轮次含 {other_tasks} 条非 web_user 任务，拒绝混入")

        created = 0
        reused = 0
        for _question, version in versions:
            for _engine, entry in entries:
                key = (version.id, entry.id, 1)
                task = existing.get(key)
                if task is not None:
                    reused += 1
                    continue
                db.add(
                    MonitoringTask(
                        project_id=project.id,
                        round_id=round_row.id,
                        question_version_id=version.id,
                        engine_entry_id=entry.id,
                        sampling_no=1,
                        trace_id=uuid.uuid4().hex,
                        sampling_mode=SamplingMode.SEARCH_ON,
                        status=TaskStatus.PENDING,
                        created_by=actor.id,
                    )
                )
                created += 1
        db.flush()

        # 人工专用轮次保持 planning；调度器虽扫描 planning/running，但
        # plan_round_tasks 命中 web_user 人工任务会返回 manual_round。
        result = {
            "apply": apply,
            "project": project.code,
            "round_id": str(round_row.id),
            "round_name": round_row.name,
            "round_seq": round_row.seq,
            "round_status": round_row.status.value,
            "is_baseline": round_row.is_baseline,
            "created_round": created_round,
            "question_count": len(versions),
            "entry_count": len(entries),
            "created_task_count": created,
            "reused_task_count": reused,
            "expected_task_count": len(versions) * len(entries),
            "questions": [question.code for question, _version in versions],
            "entries": [
                {
                    "engine_code": engine.code,
                    "engine_name": engine.name,
                    "entry_id": str(entry.id),
                    "entry_name": entry.name,
                }
                for engine, entry in entries
            ],
        }
        record_audit(
            db,
            project_id=project.id,
            actor_id=actor.id,
            action="monitoring.tasks_web_user_retest_generate",
            target_type="monitoring_round",
            target_id=round_row.id,
            payload=result,
        )
        if apply:
            db.commit()
        else:
            db.rollback()
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写库；默认演练并回滚")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--project-code", required=True, help="项目 code，必须显式指定")
    parser.add_argument("--round-name", default=None, help="轮次名称")
    parser.add_argument("--actor", default="geo_admin", help="创建账号")
    args = parser.parse_args()
    result = run(
        apply=args.apply,
        project_code=args.project_code,
        round_name=args.round_name,
        actor_username=args.actor,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"round={result['round_id']} seq={result['round_seq']} "
            f"status={result['round_status']} created={result['created_task_count']} "
            f"reused={result['reused_task_count']} expected={result['expected_task_count']} "
            f"apply={result['apply']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
