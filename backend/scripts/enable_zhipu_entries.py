"""启用智谱 GLM-4-Flash 入口，并为 GLM-5.3-FlashX 建独立入口（资源包绑定前不启用）。

模型不写死在适配器：入口的 model_name 决定调用模型；同一平台用多条入口承载不同模型。
"""

from __future__ import annotations

import argparse
import json
import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import AiEngine, AiEngineEntry, User
from app.models.enums import EngineEntryType, EngineProtocol
from app.services.audit import record_audit
from app.services.engine_connectors import test_entry_connection

ENGINE_ID = uuid.UUID("a69e042b-737f-4b2d-af20-427cb85bb6db")
ENTRY_ID = uuid.UUID("5f1c5652-3f88-4389-b395-84f5f6704892")
NEW_NAME = "智谱 GLM-5.3-FlashX（资源包待绑定）"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        parser.error("必须指定 --dry-run 或 --apply")

    db = SessionLocal()
    try:
        engine = db.get(AiEngine, ENGINE_ID)
        entry = db.get(AiEngineEntry, ENTRY_ID)
        actor = db.scalar(select(User).where(User.username == "geo_admin"))
        if not engine or not entry or not actor:
            raise SystemExit("智谱引擎、入口或执行人不存在")
        if not entry.encrypted_secret:
            raise SystemExit("智谱入口没有库内密文 Key")

        existing = db.scalar(
            select(AiEngineEntry).where(
                AiEngineEntry.engine_id == ENGINE_ID,
                AiEngineEntry.entry_type == EngineEntryType.API,
                AiEngineEntry.name == NEW_NAME,
            )
        )
        created = False
        if existing is None and args.apply:
            existing = AiEngineEntry(
                engine_id=ENGINE_ID,
                entry_type=EngineEntryType.API,
                name=NEW_NAME,
                entry_url=entry.entry_url,
                protocol=EngineProtocol.OPENAI_COMPATIBLE,
                model_name="glm-5.3-flashx",
                credential_ref=entry.credential_ref,
                encrypted_secret=entry.encrypted_secret,
                encrypted_secret_secondary=entry.encrypted_secret_secondary,
                credential_updated_at=entry.credential_updated_at,
                supports_search=True,
                is_active=False,
                access_note=(
                    "独立模型入口，复用同一 Key；300 万 GLM-5.3-FlashX 资源包尚未绑定该 Key 账户，"
                    "2026-11-21 实测 /chat/completions 返回 429 code 1113，绑定后再启用。"
                ),
            )
            db.add(existing)
            db.flush()
            created = True

        test_result = None
        if args.apply:
            entry.is_active = True
            db.flush()
            test_result = test_entry_connection(entry)
            if test_result["success"]:
                from datetime import datetime, timezone

                entry.last_verified_at = datetime.now(timezone.utc)
            record_audit(
                db,
                project_id=None,
                actor_id=actor.id,
                action="engine.entry.activate",
                target_type="ai_engine_entry",
                target_id=entry.id,
                payload={
                    "engine_id": str(ENGINE_ID),
                    "model_name": entry.model_name,
                    "test_success": bool(test_result["success"]),
                    "test_error_code": test_result.get("error_code"),
                    "note": "启用 GLM-4-Flash；GLM-5.3-FlashX 独立入口保持停用",
                },
            )
            if created and existing is not None:
                record_audit(
                    db,
                    project_id=None,
                    actor_id=actor.id,
                    action="engine.entry.create",
                    target_type="ai_engine_entry",
                    target_id=existing.id,
                    payload={
                        "engine_id": str(ENGINE_ID),
                        "model_name": existing.model_name,
                        "is_active": False,
                        "reason": "resource_pack_not_bound",
                    },
                )
            db.commit()

        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "active_entry": {
                        "entry_id": str(entry.id),
                        "name": entry.name,
                        "model_name": entry.model_name,
                        "was_active": not entry.is_active if args.dry_run else True,
                        "is_active": entry.is_active,
                    },
                    "new_model_entry": {
                        "exists": existing is not None,
                        "created": created,
                        "name": existing.name if existing else NEW_NAME,
                        "model_name": existing.model_name if existing else "glm-5.3-flashx",
                        "is_active": existing.is_active if existing else False,
                    },
                    "test_result": test_result,
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
