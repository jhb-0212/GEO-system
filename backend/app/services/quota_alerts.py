"""客户配额告警外发：只推「级别变化」，不重复刷同一条。

阈值判定仍在 `organization_settings.get_settings`；这里负责：
1. 把上次级别存到 `organizations.settings.quota_alert_state`，用于去重；
2. 级别升高（无 → warning → exceeded）时写审计，并按部署配置推 webhook；
3. 回落到正常只清状态，不推送。
"""

import json
import logging
import urllib.request
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.industry import Organization
from app.services.audit import record_audit

logger = logging.getLogger("geo.quota_alert")

STATE_KEY = "quota_alert_state"
_ORDER = {"warning": 1, "exceeded": 2}


def _post(payload: dict[str, Any]) -> None:
    url = settings.quota_alert_webhook
    if not url:
        logger.info("quota alert not pushed (webhook not configured)", extra={"fields": payload})
        return
    if settings.quota_alert_format == "feishu":
        text = payload.get("message") or json.dumps(payload, ensure_ascii=False)
        body = {"msg_type": "text", "content": {"text": text}}
    else:
        body = payload
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - 部署方指定地址
            response.read()
    except Exception as exc:  # noqa: BLE001 - 外发失败不能影响业务写入
        logger.warning("quota alert push failed", extra={"fields": {**payload, "error": str(exc)}})


def sync(db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None, alerts: list[dict]) -> list[dict]:
    """记录本次告警级别，仅对新增/升级项推送。返回本次需要外发的告警。"""
    org = db.get(Organization, organization_id)
    if org is None:
        return []
    previous = (org.settings or {}).get(STATE_KEY)
    previous = previous if isinstance(previous, dict) else {}
    next_state = {item["key"]: item["level"] for item in alerts}
    fresh: list[dict] = []
    for item in alerts:
        before = previous.get(item["key"])
        if before == item["level"]:
            continue
        if _ORDER.get(item["level"], 0) > _ORDER.get(before or "", 0):
            fresh.append(item)
    state = dict(org.settings or {})
    state[STATE_KEY] = next_state
    org.settings = state
    if not fresh:
        db.flush()
        return []
    messages = [item["message"] for item in fresh]
    payload = {
        "event": "organization.quota_alert",
        "organization": {"id": str(org.id), "code": org.code, "name": org.name},
        "level": max(fresh, key=lambda item: _ORDER.get(item["level"], 0))["level"],
        "message": "；".join(messages),
        "alerts": fresh,
    }
    for item in fresh:
        record_audit(
            db,
            project_id=project_id,
            actor_id=None,
            action="organization.quota_alert",
            target_type="organization",
            target_id=org.id,
            payload={"key": item["key"], "used": item["used"], "limit": item["limit"], "level": item["level"]},
        )
    _post(payload)
    db.flush()
    return fresh
