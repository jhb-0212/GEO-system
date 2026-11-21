"""把 seq5 首轮网页 4×6 轮次设为唯一基线，并同步修正已冻结快照。

只修被选为基线的 seq5 快照：scope.round.is_baseline 置 true，metrics 按当前库重算，
hash 重算，并写入 correction 说明。历史 captured_at 保留，便于审计。
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

import app.services.stat_snapshots as snap
from app.db.session import SessionLocal
from app.models import MonitoringRound, Project, StatSnapshot, User
from app.services.audit import record_audit

PROJECT_ID = uuid.UUID("154640d4-6356-4a1c-8bde-2d511cfb06cd")
SEQ5 = uuid.UUID("920460ab-6430-46db-ab91-0fbfba96bf9d")
SEQ4 = uuid.UUID("26ca0939-c87c-403a-a6d9-e6624d9e4711")


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
        round_row = db.get(MonitoringRound, SEQ5)
        snapshot = db.scalar(
            select(StatSnapshot).where(
                StatSnapshot.project_id == PROJECT_ID,
                StatSnapshot.round_id == SEQ5,
            )
        )
        if round_row is None or snapshot is None:
            raise SystemExit("seq5 轮次或快照不存在")
        if not round_row.is_baseline:
            raise SystemExit("seq5 轮次尚未设为基线，先运行 finalize_round_scopes.py --apply")

        scope = snap._jsonable(snap._scope(db, PROJECT_ID, round_row))
        metrics = snap._jsonable(snap._metrics(db, PROJECT_ID, SEQ5))
        scope["correction"] = {
            "reason": "baseline_scope_correction",
            "corrected_at": datetime.now(timezone.utc).isoformat(),
            "corrected_by": str(actor.id),
            "note": "seq4 API 轮取消基线标记；seq5 首轮网页人工采样 4×6=24 格设为唯一首月基线；快照按当前库重算。",
        }
        new_hash = snap.snapshot_hash(scope, metrics)
        before = {
            "snapshot_id": str(snapshot.id),
            "hash": snapshot.snapshot_hash,
            "round_baseline": (snapshot.scope or {}).get("round", {}).get("is_baseline"),
            "engine_entries": len((snapshot.scope or {}).get("engine_entries", [])),
            "tables": len((snapshot.metrics or {}).get("by_engine", [])),
        }
        after = {
            "hash": new_hash,
            "round_baseline": scope["round"]["is_baseline"],
            "engine_entries": len(scope["engine_entries"]),
            "overview": metrics.get("overview", {}),
        }
        if args.apply:
            snapshot.scope = scope
            snapshot.metrics = metrics
            snapshot.snapshot_hash = new_hash
            snapshot.definitions = {
                "stats": snap.STAT_RULE_VERSION,
                "matcher": snap.MATCHER_VERSION,
                "classifier": snap.CLASSIFIER_VERSION,
                "corrected": "baseline-scope-v1",
            }
            db.flush()
            record_audit(
                db,
                project_id=PROJECT_ID,
                actor_id=actor.id,
                action="stat.snapshot_correct",
                target_type="stat_snapshot",
                target_id=snapshot.id,
                payload={
                    "round_id": str(SEQ5),
                    "before": before,
                    "after": after,
                    "reason": "baseline_scope_correction",
                },
            )
            db.commit()

        seq4 = db.get(MonitoringRound, SEQ4)
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "seq4_is_baseline": seq4.is_baseline if seq4 else None,
                    "seq5_is_baseline": round_row.is_baseline,
                    "before": before,
                    "after": after,
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
