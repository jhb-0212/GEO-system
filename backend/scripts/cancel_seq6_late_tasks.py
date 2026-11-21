"""清理 seq6 关闭后晚到的 2 条重复 pending 任务。

不删除任务、不删样本：只把状态置 cancelled 并留审计。若确需补采，应新建轮次。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import AiEngine, AiEngineEntry, MonitoringRound, MonitoringTask, Project, Question, QuestionVersion, User
from app.models.enums import TaskStatus
from app.services.audit import record_audit
from app.services.state_machine import ensure_task_transition

PROJECT_ID = uuid.UUID("154640d4-6356-4a1c-8bde-2d511cfb06cd")
ROUND_ID = uuid.UUID("d2a32cf3-cc6b-4c4a-a637-d4a4335de620")


def main() -> int:
    db = SessionLocal()
    try:
        project = db.get(Project, PROJECT_ID)
        actor = db.scalar(select(User).where(User.username == "geo_admin"))
        round_row = db.get(MonitoringRound, ROUND_ID)
        if not project or not actor or not round_row:
            raise SystemExit("项目、执行人或轮次不存在")
        rows = db.execute(
            select(
                MonitoringTask,
                AiEngine.name,
                Question.code,
                AiEngineEntry.name,
            )
            .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
            .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
            .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
            .join(Question, Question.id == QuestionVersion.question_id)
            .where(
                MonitoringTask.project_id == PROJECT_ID,
                MonitoringTask.round_id == ROUND_ID,
                MonitoringTask.status == TaskStatus.PENDING,
            )
        ).all()
        cancelled = []
        for task, engine_name, code, entry_name in rows:
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
                    "reason": "late_duplicate_after_round_close",
                    "engine": engine_name,
                    "question": code,
                    "entry": entry_name,
                    "note": "seq6 已于本轮收口关闭；晚到重复任务不删除，仅取消；如需补采请新建轮次",
                },
            )
            cancelled.append(
                {
                    "task_id": str(task.id),
                    "engine": engine_name,
                    "question": code,
                    "entry": entry_name,
                    "from_status": "pending",
                }
            )
        db.commit()
        print(json.dumps({"cancelled": cancelled, "count": len(cancelled)}, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
