"""渠道台账的读写规则：别名、主域名唯一性、准入历史、删除前置统计。

`api/channels.py` 只负责参数校验与事务边界，渠道自身的口径集中在这里：

- `ensure_primary_domain` / `ensure_alias`：一个域名（主域名或别名）只能属于一个渠道，
  改主域名或改名时旧身份会落别名，避免历史引用断链。
- `reference_counts`：删除前统计真实业务引用，有引用只能停用，不能物理删除。
- `delete_snapshot`：删除审计只留可追溯摘要，不复制令牌或正文。
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ResourceMissingError
from app.models import (
    Channel,
    ChannelAlias,
    ChannelApproval,
    ContentItem,
    ContentPlan,
    Lead,
    MediaQuote,
    MonitoringCitation,
    OAuthConnection,
    PublishAccount,
    PublishTask,
    User,
)

REFERENCE_MODELS = (
    ("发布账号", PublishAccount, "channel_id"),
    ("发布任务", PublishTask, "channel_id"),
    ("AI 引用", MonitoringCitation, "channel_id"),
    ("内容项", ContentItem, "channel_id"),
    ("内容计划", ContentPlan, "channel_id"),
    ("媒体报价", MediaQuote, "channel_id"),
    ("线索", Lead, "source_channel_id"),
    ("OAuth 连接", OAuthConnection, "channel_id"),
)


def channel_payload(channel: Channel) -> dict:
    return {
        "id": str(channel.id),
        "code": channel.code,
        "name": channel.name,
        "category": str(channel.category),
        "status": str(channel.status),
        "approval_status": str(channel.approval_status),
        "primary_domain": channel.primary_domain,
        "publish_url": channel.publish_url,
        "login_url": channel.login_url,
        "owner_name": channel.owner_name,
        "owner_contact": channel.owner_contact,
    }


def user_names(db: Session, user_ids) -> dict:
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    return {
        user_id: display_name or username
        for user_id, display_name, username in db.execute(
            select(User.id, User.display_name, User.username).where(User.id.in_(ids))
        ).all()
    }


def approval_payload(row: ChannelApproval, names: dict) -> dict:
    return {
        "id": str(row.id),
        "submitted_by": str(row.submitted_by) if row.submitted_by else None,
        "submitted_by_name": names.get(row.submitted_by),
        "submitted_at": row.submitted_at,
        "reviewed_by": str(row.reviewed_by) if row.reviewed_by else None,
        "reviewed_by_name": names.get(row.reviewed_by),
        "reviewed_at": row.reviewed_at,
        "decision": str(row.decision) if row.decision else None,
        "comment": row.comment,
        "created_at": row.created_at,
    }


def approval_history(db: Session, channel_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(
        select(ChannelApproval)
        .where(ChannelApproval.channel_id == channel_id)
        .order_by(ChannelApproval.submitted_at.asc(), ChannelApproval.id.asc())
    ).all()
    names = user_names(
        db,
        [row.submitted_by for row in rows] + [row.reviewed_by for row in rows],
    )
    return [approval_payload(row, names) for row in rows]


def aliases_for(db: Session, channel: Channel) -> list[ChannelAlias]:
    return list(
        db.scalars(
            select(ChannelAlias)
            .where(
                ChannelAlias.project_id == channel.project_id,
                ChannelAlias.channel_id == channel.id,
            )
            .order_by(ChannelAlias.domain)
        ).all()
    )


def _alias_payloads(aliases: list[ChannelAlias]) -> list[dict]:
    return [{"domain": alias.domain, "alias_name": alias.alias_name} for alias in aliases]


def edit_payload(db: Session, channel: Channel) -> dict:
    return {
        **channel_payload(channel),
        "notes": channel.notes,
        "is_active": channel.is_active,
        "submitted_by": str(channel.submitted_by) if channel.submitted_by else None,
        "reviewed_by": str(channel.reviewed_by) if channel.reviewed_by else None,
        "reviewed_at": channel.reviewed_at,
        "decision_comment": channel.decision_comment,
        "aliases": _alias_payloads(aliases_for(db, channel)),
    }


def reference_counts(db: Session, project_id: uuid.UUID, channel_id: uuid.UUID) -> dict[str, int]:
    """删除前统计真实业务引用：任一关联存在都只能停用，不能物理删除。

    渠道别名与准入审批属于渠道自身生命周期，随渠道一起 CASCADE；这里只统计
    会丢失业务历史或让其他单据悬空的外部引用。
    """
    counts: dict[str, int] = {}
    for label, model, column_name in REFERENCE_MODELS:
        count = (
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.project_id == project_id,
                    getattr(model, column_name) == channel_id,
                )
            )
            or 0
        )
        if count:
            counts[label] = int(count)
    return counts


def delete_snapshot(db: Session, channel: Channel) -> dict:
    approvals = approval_history(db, channel.id)
    return {
        "code": channel.code,
        "name": channel.name,
        "category": str(channel.category),
        "status": str(channel.status),
        "approval_status": str(channel.approval_status),
        "primary_domain": channel.primary_domain,
        "owner_name": channel.owner_name,
        "owner_contact": channel.owner_contact,
        "notes": channel.notes,
        "is_active": channel.is_active,
        "aliases": _alias_payloads(aliases_for(db, channel)),
        "approvals": [
            {
                "submitted_at": row["submitted_at"].isoformat()
                if row["submitted_at"]
                else None,
                "decision": row["decision"],
                "reviewed_at": row["reviewed_at"].isoformat()
                if row["reviewed_at"]
                else None,
                "comment": row["comment"],
            }
            for row in approvals
        ],
    }


def ensure_primary_domain(
    db: Session,
    *,
    project_id: uuid.UUID,
    channel: Channel | None,
    domain: str | None,
) -> None:
    """主域名同样要全局唯一：不能占用其他渠道的主域名或别名。"""
    if domain is None:
        return
    channel_filters = [
        Channel.project_id == project_id,
        Channel.primary_domain == domain,
    ]
    alias_filters = [
        ChannelAlias.project_id == project_id,
        ChannelAlias.domain == domain,
    ]
    if channel is not None:
        channel_filters.append(Channel.id != channel.id)
        alias_filters.append(ChannelAlias.channel_id != channel.id)
    if db.scalar(select(Channel).where(*channel_filters)) is not None:
        raise AppError("域名已作为其他渠道主域名", code="channel_domain_conflict")
    if db.scalar(select(ChannelAlias).where(*alias_filters)) is not None:
        raise AppError("域名已归属其他渠道", code="channel_domain_conflict")


def ensure_alias(
    db: Session,
    *,
    project_id: uuid.UUID,
    channel: Channel,
    domain: str | None,
    alias_name: str | None,
) -> None:
    """旧域名/旧名称落别名；域名归属别的渠道时拒绝，避免静默覆盖。

    `domain=None` 表示这条只记录历史名称，不参与域名观测与归因。
    """
    if domain is None:
        if not alias_name:
            return
        existing_name = db.scalar(
            select(ChannelAlias).where(
                ChannelAlias.project_id == project_id,
                ChannelAlias.channel_id == channel.id,
                ChannelAlias.domain.is_(None),
                ChannelAlias.alias_name == alias_name,
            )
        )
        if existing_name is None:
            db.add(
                ChannelAlias(
                    project_id=project_id,
                    channel_id=channel.id,
                    domain=None,
                    alias_name=alias_name,
                )
            )
        return
    other_channel = db.scalar(
        select(Channel).where(
            Channel.project_id == project_id,
            Channel.primary_domain == domain,
            Channel.id != channel.id,
        )
    )
    if other_channel is not None:
        raise AppError("域名已作为其他渠道主域名", code="channel_domain_conflict")
    existing = db.scalar(
        select(ChannelAlias).where(
            ChannelAlias.project_id == project_id,
            ChannelAlias.domain == domain,
        )
    )
    if existing is not None:
        if existing.channel_id != channel.id:
            raise AppError("域名已归属其他渠道", code="channel_domain_conflict")
        if alias_name:
            existing.alias_name = alias_name
        return
    db.add(
        ChannelAlias(
            project_id=project_id,
            channel_id=channel.id,
            domain=domain,
            alias_name=alias_name,
        )
    )


def preserve_old_identity(
    db: Session,
    *,
    project_id: uuid.UUID,
    channel: Channel,
    old_name: str,
    old_domain: str | None,
) -> None:
    """改名/换主域名时保留旧名称和旧域名。

    有旧域名时落 `domain + alias_name`；没有旧域名时同样落 `alias_name` 行，
    `domain` 留空，旧名称不再只存在于备注自由文本。
    """
    ensure_alias(
        db,
        project_id=project_id,
        channel=channel,
        domain=old_domain,
        alias_name=old_name,
    )


def add_aliases(
    db: Session,
    *,
    project_id: uuid.UUID,
    channel: Channel,
    aliases: list[str],
) -> None:
    for domain in aliases:
        if domain == channel.primary_domain:
            continue
        ensure_alias(
            db,
            project_id=project_id,
            channel=channel,
            domain=domain,
            alias_name=channel.name,
        )


def channel_by_code(db: Session, project_id: uuid.UUID, code: str) -> Channel | None:
    return db.scalar(
        select(Channel).where(Channel.project_id == project_id, Channel.code == code)
    )


def page_channels(db: Session, filters, *, page: int, page_size: int) -> tuple[list[Channel], int]:
    total = db.scalar(select(func.count()).select_from(Channel).where(*filters)) or 0
    rows = db.scalars(
        select(Channel)
        .where(*filters)
        .order_by(Channel.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), int(total)


def latest_approval(db: Session, channel_id: uuid.UUID) -> ChannelApproval | None:
    """渠道最新一个审批周期（审批时回填 reviewed_by/decision/comment 用）。"""
    return db.scalars(
        select(ChannelApproval)
        .where(ChannelApproval.channel_id == channel_id)
        .order_by(ChannelApproval.submitted_at.desc(), ChannelApproval.id.desc())
    ).first()


def all_channels(db: Session, project_id: uuid.UUID) -> list[Channel]:
    return list(
        db.scalars(
            select(Channel)
            .where(Channel.project_id == project_id)
            .order_by(Channel.code)
        ).all()
    )


def count_rows(db: Session, statement) -> int:
    """把任意语句包成子查询计数：导出前卡同步上限用。"""
    return int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)


def channel_detail_row(db: Session, project_id: uuid.UUID, channel_id: uuid.UUID) -> Channel:
    """详情页取渠道：不存在就是 404（详情不承担枚举防泄漏，语义与列表一致）。"""
    row = db.scalar(
        select(Channel).where(
            Channel.id == channel_id,
            Channel.project_id == project_id,
        )
    )
    if row is None:
        raise ResourceMissingError("渠道不存在")
    return row
