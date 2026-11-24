r"""为一个项目创建“应用内 7×6 人工采样”轮次。

这个轮次只包含 `app_search` 入口的任务，任务以 pending 建出，等待运营在
工作台「新增手测样本」逐条录入。调度器看到轮次里已有 app_search 任务后
会跳过该轮次，不会补 API 自动任务、也不会向 Worker 派发。

用法（在 backend 目录）：
    .\.venv\Scripts\python.exe scripts\seed_manual_app_search_tasks.py --json
    .\.venv\Scripts\python.exe scripts\seed_manual_app_search_tasks.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
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
from app.services.state_machine import ensure_round_transition  # noqa: E402


def _active_versions(db, project_id):
    rows = db.execute(
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
    return rows


def run(*, apply: bool, project_code: str, round_name: str | None, actor_username: str) -> dict:
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == project_code))
        if project is None:
            raise SystemExit(f"项目不存在：{project_code}")
        actor = db.scalar(select(User).where(User.username == actor_username))
        if actor is None or not actor.is_active:
            raise SystemExit(f"操作账号不存在或已停用：{actor_username}")

        versions = _active_versions(db, project.id)
        entries = db.scalars(
            select(AiEngineEntry)
            .where(AiEngineEntry.entry_type == EngineEntryType.APP_SEARCH)
            .order_by(AiEngineEntry.created_at, AiEngineEntry.id)
        ).all()
        if not versions:
            raise SystemExit("项目没有启用题目版本，无法建人工任务")
        if not entries:
            raise SystemExit("没有 app_search 入口，无法建人工任务")

        name = round_name or f"应用内 {len(entries)}×{len(versions)} 人工采样（{datetime.now(timezone.utc):%Y-%m-%d}）"
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
            raise SystemExit(f"同名轮次已完成/关闭，不能追加人工任务：{name}")

        existing = {
            (task.question_version_id, task.engine_entry_id, task.sampling_no): task
            for task in db.scalars(
                select(MonitoringTask).where(MonitoringTask.round_id == round_row.id)
            ).all()
        }
        other_tasks = sum(
            1
            for task in existing.values()
            if all(task.engine_entry_id != entry.id for entry in entries)
        )
        if other_tasks:
            raise SystemExit(f"同名轮次含 {other_tasks} 条非应用内任务，拒绝混入人工轮次")

        created = 0
        reused = 0
        for _question, version in versions:
            for entry in entries:
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

        if round_row.status == RoundStatus.PLANNING:
            round_row.status = ensure_round_transition(round_row.status, RoundStatus.RUNNING)

        result = {
            "apply": apply,
            "project": project.code,
            "round_id": str(round_row.id),
            "round_name": round_row.name,
            "round_status": round_row.status.value,
            "created_round": created_round,
            "question_count": len(versions),
            "entry_count": len(entries),
            "created_task_count": created,
            "reused_task_count": reused,
            "expected_task_count": len(versions) * len(entries),
        }
        record_audit(
            db,
            project_id=project.id,
            actor_id=actor.id,
            action="monitoring.tasks_manual_generate",
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
    parser.add_argument("--round-name", default=None, help="轮次名称；默认按入口/题目数生成")
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
            f"round={result['round_id']} status={result['round_status']} "
            f"created={result['created_task_count']} reused={result['reused_task_count']} "
            f"expected={result['expected_task_count']} apply={result['apply']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
