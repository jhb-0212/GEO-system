"""收口轮次范围：取消 seq3 残留 pending；把首月 4×6 网页轮 seq5 设为唯一基线。

不生成/覆盖统计快照；快照在引用字段与渠道回填完成后再统一重算。
"""

from __future__ import annotations

import argparse
import json
import uuid

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import MonitoringRound, MonitoringTask, Project, User
from app.models.enums import RoundStatus, TaskStatus
from app.services.audit import record_audit
from app.services.state_machine import ensure_task_transition

PROJECT_ID = uuid.UUID("154640d4-6356-4a1c-8bde-2d511cfb06cd")
SEQ3 = uuid.UUID("b01c5f7b-0aa3-48e6-b422-789a7ba4702e")
SEQ4 = uuid.UUID("26ca0939-c87c-403a-a6d9-e6624d9e4711")
SEQ5 = uuid.UUID("920460ab-6430-46db-ab91-0fbfba96bf9d")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        parser.error("必须指定 --dry-run 或 --apply")

    db = SessionLocal()
    try:
        project = db.get(Project, PROJECT_ID)
        actor = db.scalar(select(User).where(User.username == "geo_admin"))
        if not project or not actor:
            raise SystemExit("项目或执行人不存在")
        rounds = {
            row.id: row
            for row in db.scalars(
                select(MonitoringRound).where(
                    MonitoringRound.project_id == PROJECT_ID,
                    MonitoringRound.id.in_([SEQ3, SEQ4, SEQ5]),
                )
            ).all()
        }
        if set(rounds) != {SEQ3, SEQ4, SEQ5}:
            raise SystemExit("目标轮次不完整")

        seq3_pending = db.scalars(
            select(MonitoringTask).where(
                MonitoringTask.project_id == PROJECT_ID,
                MonitoringTask.round_id == SEQ3,
                MonitoringTask.status == TaskStatus.PENDING,
            )
        ).all()
        actions = []
        for task in seq3_pending:
            if args.dry_run:
                actions.append({"task_id": str(task.id), "action": "would_cancel_seq3_pending"})
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
                    "reason": "superseded_by_seq4_seq5",
                    "note": "seq3 历史混合轮残留网页任务；seq4 API 与 seq5 网页人工采样已覆盖 24 格",
                },
            )
            actions.append({"task_id": str(task.id), "action": "cancel_seq3_pending"})

        baseline_changes = []
        for round_id, target in ((SEQ4, False), (SEQ5, True)):
            row = rounds[round_id]
            baseline_changes.append(
                {
                    "round_id": str(round_id),
                    "name": row.name,
                    "from": row.is_baseline,
                    "to": target,
                }
            )
            if not args.dry_run and row.is_baseline != target:
                row.is_baseline = target
                db.flush()
                record_audit(
                    db,
                    project_id=PROJECT_ID,
                    actor_id=actor.id,
                    action="monitoring.round_baseline_set",
                    target_type="monitoring_round",
                    target_id=round_id,
                    payload={"from": not target, "to": target},
                )

        if not args.dry_run:
            if rounds[SEQ3].status == RoundStatus.CLOSED:
                pass
            db.commit()

        counts = {}
        for round_id in (SEQ3, SEQ4, SEQ5):
            counts[str(round_id)] = {
                getattr(status, "value", str(status)): int(count)
                for status, count in db.execute(
                    select(MonitoringTask.status, func.count())
                    .where(
                        MonitoringTask.project_id == PROJECT_ID,
                        MonitoringTask.round_id == round_id,
                    )
                    .group_by(MonitoringTask.status)
                ).all()
            }
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "actions": actions,
                    "baseline_changes": baseline_changes,
                    "task_counts": counts,
                    "round_status": {
                        str(r.id): r.status.value for r in rounds.values()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
