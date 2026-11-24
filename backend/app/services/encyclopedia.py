"""K4 百科词条服务：草稿 → 待审 → 通过/驳回 → 登记外链。

状态机（其余迁移一律 400，不做"想跳就跳"）：

    draft ──submit──> pending_review ──approve──> published
      ^                     │
      └────── reject ───────┘ (回到 draft？不，落 rejected，可编辑后重新提交)

已驳回仍可编辑并再次提交；已发布不可编辑，改内容必须另起新版（version+1 目前只做展示位，
真实改版流程等运营提出再扩）。
"""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.services.state_machine import ensure_encyclopedia_transition
from app.models import EncyclopediaEntry
from app.models.enums import EncyclopediaStatus

PUBLISHABLE_PLATFORMS = {
    "baidu_baike": "百度百科",
    "sogou_baike": "搜狗百科",
    "douyin_baike": "抖音百科",
    "wikipedia": "维基百科",
    "other": "其他平台",
}

STATUS_LABELS = {
    EncyclopediaStatus.DRAFT: "草稿",
    EncyclopediaStatus.PENDING_REVIEW: "待审核",
    EncyclopediaStatus.PUBLISHED: "已发布",
    EncyclopediaStatus.REJECTED: "已驳回",
}


def slugify(title: str, fallback: str = "entry") -> str:
    """词条名转 slug：中文直接保留（URL 用不到），只压空格与标点为连字符。"""
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", (title or "").strip().lower()).strip("-")
    return text[:120] or fallback


def _entry_snapshot(entry: EncyclopediaEntry) -> dict:
    return {
        "entry_id": str(entry.id),
        "slug": entry.slug,
        "title": entry.title,
        "platform": entry.platform,
        "platform_label": PUBLISHABLE_PLATFORMS.get(entry.platform, entry.platform),
        "summary": entry.summary,
        "body": entry.body,
        "references": entry.references or [],
        "status": entry.status.value,
        "status_label": STATUS_LABELS.get(entry.status, entry.status.value),
        "version": entry.version,
        "review_note": entry.review_note,
        "reviewed_at": entry.reviewed_at.isoformat() if entry.reviewed_at else None,
        "published_url": entry.published_url,
        "published_at": entry.published_at.isoformat() if entry.published_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }


def list_entries(db: Session, project_id: uuid.UUID, limit: int = 50) -> list[dict]:
    rows = db.scalars(
        select(EncyclopediaEntry)
        .where(EncyclopediaEntry.project_id == project_id)
        .order_by(EncyclopediaEntry.created_at.desc())
        .limit(limit)
    ).all()
    return [_entry_snapshot(row) for row in rows]


def get_entry(db: Session, project_id: uuid.UUID, entry_id: uuid.UUID) -> EncyclopediaEntry:
    row = db.scalar(
        select(EncyclopediaEntry).where(
            EncyclopediaEntry.project_id == project_id, EncyclopediaEntry.id == entry_id
        )
    )
    if row is None:
        raise AppError("词条不存在或不属于当前项目", code="encyclopedia_entry_not_found")
    return row


def create_entry(
    db: Session,
    project_id: uuid.UUID,
    *,
    title: str,
    platform: str,
    body: str,
    summary: str | None = None,
    references: list | None = None,
    slug: str | None = None,
) -> EncyclopediaEntry:
    if platform not in PUBLISHABLE_PLATFORMS:
        raise AppError("目标平台不在支持范围内", code="encyclopedia_platform_invalid")
    base = slugify(slug or title)
    candidate = base
    suffix = 1
    while db.scalar(
        select(EncyclopediaEntry.id).where(
            EncyclopediaEntry.project_id == project_id, EncyclopediaEntry.slug == candidate
        )
    ) is not None:
        suffix += 1
        candidate = f"{base}-{suffix}"[:128]
    row = EncyclopediaEntry(
        project_id=project_id,
        slug=candidate,
        title=title.strip()[:255],
        platform=platform,
        summary=(summary or "").strip() or None,
        body=body.strip(),
        references=references or [],
        status=EncyclopediaStatus.DRAFT,
    )
    db.add(row)
    db.flush()
    return row


def update_entry(db: Session, entry: EncyclopediaEntry, changes: dict) -> EncyclopediaEntry:
    if entry.status in (EncyclopediaStatus.PENDING_REVIEW, EncyclopediaStatus.PUBLISHED):
        raise AppError(
            "待审或已发布的词条不可直接改，先撤回或另起新版",
            code="encyclopedia_entry_locked",
        )
    if "platform" in changes and changes["platform"] not in PUBLISHABLE_PLATFORMS:
        raise AppError("目标平台不在支持范围内", code="encyclopedia_platform_invalid")
    for field in ("title", "platform", "summary", "body", "references"):
        if field in changes and changes[field] is not None:
            setattr(entry, field, changes[field])
    # 驳回后改动视为新稿，状态回草稿，审核意见保留可查
    if entry.status is EncyclopediaStatus.REJECTED:
        entry.status = ensure_encyclopedia_transition(entry.status, EncyclopediaStatus.DRAFT)
    db.flush()
    return entry


def submit_entry(db: Session, entry: EncyclopediaEntry) -> EncyclopediaEntry:
    if entry.status not in (EncyclopediaStatus.DRAFT, EncyclopediaStatus.REJECTED):
        raise AppError("只有草稿或已驳回的词条可以提交审核", code="encyclopedia_status_invalid")
    if not entry.body.strip():
        raise AppError("正文不能为空", code="encyclopedia_body_required")
    if len(entry.references or []) == 0:
        raise AppError("至少填一条参考资料，否则审核无从核验", code="encyclopedia_references_required")
    entry.status = ensure_encyclopedia_transition(entry.status, EncyclopediaStatus.PENDING_REVIEW)
    db.flush()
    return entry


def review_entry(
    db: Session, entry: EncyclopediaEntry, *, approve: bool, reviewer_id: uuid.UUID, note: str | None
) -> EncyclopediaEntry:
    if entry.status is not EncyclopediaStatus.PENDING_REVIEW:
        raise AppError("只有待审词条可以审", code="encyclopedia_status_invalid")
    entry.status = ensure_encyclopedia_transition(
        entry.status,
        EncyclopediaStatus.PUBLISHED if approve else EncyclopediaStatus.REJECTED,
    )
    entry.reviewer_id = reviewer_id
    entry.review_note = (note or "").strip() or None
    entry.reviewed_at = datetime.now(UTC)
    db.flush()
    return entry


def register_publication(
    db: Session, entry: EncyclopediaEntry, *, published_url: str
) -> EncyclopediaEntry:
    if entry.status is not EncyclopediaStatus.PUBLISHED:
        raise AppError("只有审核通过的词条可以登记外链", code="encyclopedia_status_invalid")
    entry.published_url = published_url.strip()
    entry.published_at = datetime.now(UTC)
    db.flush()
    return entry


def entry_snapshot(entry: EncyclopediaEntry) -> dict:
    return _entry_snapshot(entry)
