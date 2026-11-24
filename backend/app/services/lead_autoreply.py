"""留言固定话术自动回复：**模板句，不是生成式**。

边界（这是本模块存在的理由）：

- 只发一句**预先写好、品牌已确认**的话术，不调用任何模型，不做意图识别，
  不改写、不追问、不承诺、不报价；
- 一句话只发一次：同一线索已经回过自动回复就不再发，避免机器人刷屏；
- 开关与正文都存在 `project_policies` 的 `lead.autoreply` 键下，
  默认 **关闭**，且默认正文不含任何数字与承诺，只有「已收到 + 人工会在工作时间联系 + 官方联系方式」；
- 联系方式从已启用的项目联系人里取，取不到就省略该行，不编造。

它替代的是「数字员工 7×24 对话」那类模块：访客要的不是陪聊，是「有人收到我说话了」。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LeadMessage, ProjectContact, ProjectPolicy

POLICY_KEY = "lead.autoreply"
AUTO_ROLE = "auto"

DEFAULT_SCRIPT = (
    "已收到您的留言，我们会在工作时间（周一至周五 9:00-18:00）由人工回复您。"
    "如需更快联系，请使用页面上标注的官方联系方式。"
)


def default_policy() -> dict:
    return {
        "enabled": False,
        "script": DEFAULT_SCRIPT,
        "include_contact": True,
        "note": "固定话术：不调用模型、不做意图识别、不含数字与承诺；每条线索只发一次。",
    }


def policy(db: Session, project_id: uuid.UUID) -> dict:
    row = db.scalar(
        select(ProjectPolicy).where(
            ProjectPolicy.project_id == project_id, ProjectPolicy.key == POLICY_KEY
        )
    )
    merged = default_policy()
    if row is not None and isinstance(row.value, dict):
        merged.update({key: row.value[key] for key in row.value if key in merged})
    return merged


def save_policy(
    db: Session,
    project_id: uuid.UUID,
    *,
    enabled: bool,
    script: str,
    include_contact: bool,
    note: str | None,
    actor_id: uuid.UUID | None,
) -> dict:
    row = db.scalar(
        select(ProjectPolicy).where(
            ProjectPolicy.project_id == project_id, ProjectPolicy.key == POLICY_KEY
        )
    )
    value = {
        "enabled": enabled,
        "script": script,
        "include_contact": include_contact,
    }
    if row is None:
        row = ProjectPolicy(project_id=project_id, key=POLICY_KEY, value=value)
        db.add(row)
    else:
        # 显式赋值（不是原地改 dict）：JSONB 的原地修改不会被 SQLAlchemy 认作变更
        row.value = value
    row.note = note
    row.updated_by = actor_id
    db.flush()
    return policy(db, project_id)


def _contact_line(db: Session, project_id: uuid.UUID) -> str | None:
    # 只用对外公开、已启用的联系人：自动回复是发给访客的，内部对接方式不能外露
    contacts = db.scalars(
        select(ProjectContact)
        .where(
            ProjectContact.project_id == project_id,
            ProjectContact.is_active.is_(True),
            ProjectContact.is_public.is_(True),
        )
        .order_by(ProjectContact.sort_order.asc(), ProjectContact.created_at.asc())
        .limit(1)
    ).all()
    if not contacts:
        return None
    contact = contacts[0]
    label = contact.label or contact.channel
    parts = [part for part in (label, contact.value) if part]
    return "联系方式：" + " / ".join(parts) if parts else None


def compose(db: Session, project_id: uuid.UUID) -> str:
    payload = policy(db, project_id)
    lines = [str(payload["script"]).strip()]
    if payload.get("include_contact"):
        line = _contact_line(db, project_id)
        if line:
            lines.append(line)
    return "\n".join(line for line in lines if line)


def maybe_reply(
    db: Session, project_id: uuid.UUID, lead_id: uuid.UUID
) -> LeadMessage | None:
    """访客留言后调用：开关打开、且这条线索还没发过自动回复时，落一条固定话术。"""
    payload = policy(db, project_id)
    if not payload.get("enabled"):
        return None
    already = db.scalar(
        select(LeadMessage).where(
            LeadMessage.project_id == project_id,
            LeadMessage.lead_id == lead_id,
            LeadMessage.author_role == AUTO_ROLE,
        )
    )
    if already is not None:
        return None
    message = LeadMessage(
        project_id=project_id,
        lead_id=lead_id,
        author_role=AUTO_ROLE,
        body=compose(db, project_id),
        is_read=True,
        created_by=None,
    )
    db.add(message)
    db.flush()
    return message


def replied_at(db: Session, project_id: uuid.UUID, lead_id: uuid.UUID) -> datetime | None:
    row = db.scalar(
        select(LeadMessage)
        .where(
            LeadMessage.project_id == project_id,
            LeadMessage.lead_id == lead_id,
            LeadMessage.author_role == AUTO_ROLE,
        )
        .order_by(LeadMessage.created_at.desc())
    )
    return row.created_at if row is not None else None


def stamp() -> datetime:
    return datetime.now(UTC)
