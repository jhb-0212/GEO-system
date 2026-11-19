"""内容接口：写正文要 content.write，审批要 content.review。

审核人员没有 content.write，改正文一律 403；审批必须写 content_hash_snapshot 留痕。
"""

import hashlib
import html
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import (
    COMMON_ERRORS,
    ContentBodyUpdated,
    ContentExportPackage,
    ContentItemCreated,
    ContentReviewData,
    ContentReviewQueueItem,
    ContentReviewCreated,
    ContentStatusChanged,
    ContentVersionCreated,
    ContentVersionDetail,
    ContentVersionLinksData,
    ContentVersionSubmitted,
    Envelope,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.errors import AppError, ResourceMissingError, ReviewStateError
from app.db.session import get_db
from app.models import (
    Channel,
    ContentItem,
    ContentReview,
    ContentVersion,
    ContentVersionCitation,
    ContentVersionFact,
    ContentVersionQuestion,
    Fact,
    MonitoringCitation,
    PublicPage,
    Question,
    User,
)
from app.models.enums import ContentKind, ContentStatus, FactStatus, ReviewDecision
from app.schemas import (
    ContentBodyUpdate,
    ContentItemCreate,
    ContentReviewRequest,
    ContentStatusUpdate,
    ContentVersionCreate,
    ContentVersionLinksUpdate,
)
from app.services.audit import record_audit
from app.services.content_status import content_status_label, mark_version_status
from app.services.project_scope import require_scoped_row
from app.services.state_machine import ensure_content_transition

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["内容与审核"],
    responses=COMMON_ERRORS,
)

_HEADING_RE = re.compile(r"^(#{1,3})[ \t\u3000]+", re.MULTILINE)
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")


def _sync_item_status(item: ContentItem, version: ContentVersion) -> None:
    """内容条目状态只由当前版本驱动，非当前版本不得污染 item.status。"""
    if item.current_version_id != version.id:
        return
    if item.status != version.status:
        item.status = version.status


def _content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _fact_link_warning(fact: Fact, linked_version_no: int, now: datetime) -> str | None:
    if fact.approval_status == FactStatus.DRAFT:
        return "事实未批准"
    if fact.approval_status == FactStatus.PENDING_REVIEW:
        return "事实待审批"
    if fact.approval_status == FactStatus.EXPIRED:
        return "事实已过期"
    if fact.effective_until is not None and fact.effective_until <= now:
        return "事实已过期"
    if fact.effective_from is not None and fact.effective_from > now:
        return "事实尚未生效"
    if fact.superseded_by is not None:
        return "事实已被新事实替代"
    if fact.version_no != linked_version_no:
        return f"事实已修订（关联 v{linked_version_no}，当前 v{fact.version_no}），需重新确认"
    return None


def _version_links(db: Session, version_id: uuid.UUID) -> dict:
    """版本级关联集合：题目、监测引用与权威事实分别来自三张关联表。"""
    question_ids = db.scalars(
        select(ContentVersionQuestion.question_id)
        .where(ContentVersionQuestion.version_id == version_id)
        .order_by(ContentVersionQuestion.question_id)
    ).all()
    citation_ids = db.scalars(
        select(ContentVersionCitation.citation_id)
        .where(ContentVersionCitation.version_id == version_id)
        .order_by(ContentVersionCitation.citation_id)
    ).all()
    now = datetime.now(timezone.utc)
    fact_rows = db.execute(
        select(ContentVersionFact, Fact)
        .join(Fact, Fact.id == ContentVersionFact.fact_id)
        .where(ContentVersionFact.version_id == version_id)
        .order_by(ContentVersionFact.fact_id)
    ).all()
    fact_links = []
    for link, fact in fact_rows:
        warning = _fact_link_warning(fact, link.fact_version_no, now)
        fact_links.append(
            {
                "fact_id": str(fact.id),
                "fact_type": fact.fact_type.value,
                "fact_key": fact.fact_key,
                "fact_value": fact.fact_value,
                "approval_status": fact.approval_status.value,
                "current_version_no": fact.version_no,
                "linked_version_no": link.fact_version_no,
                "stale": warning is not None,
                "warning": warning,
            }
        )
    return {
        "version_id": str(version_id),
        "question_ids": [str(row) for row in question_ids],
        "citation_ids": [str(row) for row in citation_ids],
        "fact_ids": [link["fact_id"] for link in fact_links],
        "fact_links": fact_links,
    }


@router.get("/content-versions", response_model=PagedEnvelope[ContentReviewQueueItem])
def list_content_versions(
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    status: ContentStatus | None = Query(None, description="按状态过滤；不传返回全部版本"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    filters = [ContentVersion.project_id == ctx.project.id]
    if status is not None:
        filters.append(ContentVersion.status == status)
    if status == ContentStatus.PENDING_REVIEW:
        # 审核队列只列当前版本；历史遗留的非当前 pending_review 不再出现在队列里。
        filters.append(ContentVersion.id == ContentItem.current_version_id)
    count_stmt = (
        select(func.count())
        .select_from(ContentVersion)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .where(*filters, ContentItem.project_id == ctx.project.id)
    )
    total = db.scalar(count_stmt) or 0
    rows = db.execute(
        select(ContentVersion, ContentItem, User.display_name)
        .join(ContentItem, ContentItem.id == ContentVersion.item_id)
        .outerjoin(User, User.id == func.coalesce(ContentVersion.submitted_by, ContentVersion.created_by))
        .where(*filters, ContentItem.project_id == ctx.project.id)
        .order_by(ContentVersion.submitted_at.desc().nullslast(), ContentVersion.created_at.desc(), ContentVersion.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "version_id": str(version.id),
                "item_id": str(item.id),
                "title": item.title,
                "version_no": version.version_no,
                "status": version.status.value,
                "status_label": content_status_label(version.status),
                "kind": item.kind.value,
                "channel_id": str(item.channel_id) if item.channel_id else None,
                "author_id": str(version.submitted_by or version.created_by) if version.submitted_by or version.created_by else None,
                "author_name": author_name,
                "submitted_at": version.submitted_at,
            }
            for version, item, author_name in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/content-versions/{version_id}", response_model=Envelope[ContentVersionDetail])
def get_content_version(
    version_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    version = require_scoped_row(db, ContentVersion, ctx.project.id, resource="content_version", id=version_id)
    item = require_scoped_row(db, ContentItem, ctx.project.id, resource="content_item", id=version.item_id)
    links = _version_links(db, version.id)
    return ok({
        "version_id": str(version.id), "item_id": str(item.id), "title": item.title,
        "kind": item.kind.value, "channel_id": str(item.channel_id) if item.channel_id else None,
        "version_no": version.version_no, "status": version.status.value,
        "status_label": content_status_label(version.status),
        "body": version.body, "content_hash": version.content_hash, "change_note": version.change_note,
        "question_ids": links["question_ids"], "citation_ids": links["citation_ids"],
        "fact_ids": links["fact_ids"], "fact_links": links["fact_links"],
    })


@router.post("/contents", status_code=201, response_model=Envelope[ContentItemCreated])
def create_content_item(
    payload: ContentItemCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    if payload.channel_id is not None:
        require_scoped_row(db, Channel, ctx.project.id, resource="channel", id=payload.channel_id)
    if payload.parent_id is not None:
        parent = require_scoped_row(
            db, ContentItem, ctx.project.id, resource="parent_content", id=payload.parent_id
        )
        if parent.kind != ContentKind.MASTER:
            raise ReviewStateError("渠道稿的 parent_id 必须指向母稿")
    item = ContentItem(
        project_id=ctx.project.id,
        kind=payload.kind,
        title=payload.title,
        channel_id=payload.channel_id,
        parent_id=payload.parent_id,
        status=ContentStatus.DRAFT,
        created_by=ctx.user.id,
    )
    db.add(item)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.item_create",
        target_type="content_item",
        target_id=item.id,
        payload={"kind": payload.kind.value, "title": payload.title},
    )
    db.commit()
    return ok({"item_id": str(item.id)})


@router.post(
    "/contents/{item_id}/versions",
    status_code=201,
    response_model=Envelope[ContentVersionCreated],
)
def create_content_version(
    item_id: uuid.UUID,
    payload: ContentVersionCreate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    item = require_scoped_row(
        db, ContentItem, ctx.project.id, resource="content_item", for_update=True, id=item_id
    )
    if item.current_version_id is not None:
        current = db.get(ContentVersion, item.current_version_id)
        if current is not None and current.status == ContentStatus.PENDING_REVIEW:
            raise ReviewStateError("当前版本仍在审核中，不能创建新版本；请先审批或撤回")
    current_max = db.scalar(
        select(func.max(ContentVersion.version_no)).where(ContentVersion.item_id == item.id)
    )
    next_no = (current_max or 0) + 1

    version = ContentVersion(
        project_id=ctx.project.id,
        item_id=item.id,
        version_no=next_no,
        body=payload.body,
        content_hash=_content_hash(payload.body),
        change_note=payload.change_note,
        status=ContentStatus.DRAFT,
        created_by=ctx.user.id,
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    _sync_item_status(item, version)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.version_create",
        target_type="content_version",
        target_id=version.id,
        payload={"version_no": next_no, "content_hash": version.content_hash},
    )
    db.commit()
    return ok({"version_id": str(version.id), "version_no": next_no})


@router.patch("/content-versions/{version_id}/body", response_model=Envelope[ContentBodyUpdated])
def update_content_body(
    version_id: uuid.UUID,
    payload: ContentBodyUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    """只有 content.write 能改正文；审核人员调用在这里被 403 挡下。"""
    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", for_update=True, id=version_id
    )
    if version.status != ContentStatus.DRAFT:
        raise ReviewStateError("只有草稿版本能修改正文，请创建新版本")
    item = require_scoped_row(db, ContentItem, ctx.project.id, resource="content_item", id=version.item_id)
    if item.current_version_id != version.id:
        raise ReviewStateError("只能修改当前内容版本")
    previous_hash = version.content_hash
    version.body = payload.body
    version.content_hash = _content_hash(payload.body)
    if payload.change_note:
        version.change_note = payload.change_note
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.body_update",
        target_type="content_version",
        target_id=version.id,
        payload={"before_hash": previous_hash, "after_hash": version.content_hash},
    )
    db.commit()
    return ok({"version_id": str(version.id), "content_hash": version.content_hash})


@router.post(
    "/content-versions/{version_id}/submit",
    response_model=Envelope[ContentVersionSubmitted],
)
def submit_content_version(
    version_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", for_update=True, id=version_id
    )
    item = require_scoped_row(db, ContentItem, ctx.project.id, resource="content_item", id=version.item_id)
    if item.current_version_id != version.id:
        raise ReviewStateError("只能提交当前内容版本")
    if version.status not in (ContentStatus.DRAFT, ContentStatus.REJECTED):
        raise ReviewStateError("当前版本不能重复提交审核")
    if not version.body.strip():
        raise ReviewStateError("版本正文为空，不能提交审核")
    target = ensure_content_transition(version.status, ContentStatus.PENDING_REVIEW)
    version.status = target
    version.submitted_by = ctx.user.id
    version.submitted_at = datetime.now(timezone.utc)
    _sync_item_status(item, version)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.submit",
        target_type="content_version",
        target_id=version.id,
        payload={"content_hash": version.content_hash},
    )
    db.commit()
    return ok({"version_id": str(version.id), "status": version.status.value, "submitted_at": version.submitted_at})


@router.get(
    "/content-versions/{version_id}/reviews",
    response_model=PagedEnvelope[ContentReviewData],
)
def list_content_reviews(
    version_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    require_scoped_row(db, ContentVersion, ctx.project.id, resource="content_version", id=version_id)
    filters = [ContentReview.project_id == ctx.project.id, ContentReview.version_id == version_id]
    total = db.scalar(select(func.count()).select_from(ContentReview).where(*filters)) or 0
    rows = db.execute(
        select(ContentReview, User.display_name)
        .outerjoin(User, User.id == ContentReview.reviewer_id)
        .where(*filters)
        .order_by(ContentReview.created_at.desc(), ContentReview.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [
            {
                "id": str(review.id),
                "version_id": str(review.version_id),
                "reviewer_id": str(review.reviewer_id),
                "reviewer_name": reviewer_name,
                "decision": review.decision.value,
                "comment": review.comment,
                "content_hash_snapshot": review.content_hash_snapshot,
                "created_at": review.created_at,
            }
            for review, reviewer_name in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/content-versions/{version_id}/review",
    response_model=Envelope[ContentReviewCreated],
)
def review_content_version(
    version_id: uuid.UUID,
    payload: ContentReviewRequest,
    ctx: ProjectContext = Depends(require_permission("content.review")),
    db: Session = Depends(get_db),
) -> dict:
    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", for_update=True, id=version_id
    )
    item = require_scoped_row(
        db, ContentItem, ctx.project.id, resource="content_item", id=version.item_id
    )
    if version.status != ContentStatus.PENDING_REVIEW:
        raise ReviewStateError("内容版本尚未提交审核或已处理")
    if item.current_version_id != version.id:
        raise ReviewStateError("只能审批当前内容版本")
    if not version.body:
        raise ResourceMissingError("版本正文为空，不能审批", code="empty_version")
    # 职责分离：提交人不能审批自己提交的版本（防止后续放宽 content.write 后出现自写自批）
    author_id = version.submitted_by or version.created_by
    if author_id is not None and author_id == ctx.user.id:
        raise AppError("不能审批自己提交的内容版本", code="review_self_not_allowed")
    if payload.decision == ReviewDecision.APPROVED:
        blocked = [link for link in _version_links(db, version.id)["fact_links"] if link["stale"]]
        if blocked:
            detail = "；".join(f"{link['fact_key']}：{link['warning']}" for link in blocked)
            raise ReviewStateError(
                f"关联事实未通过核验，不能批准：{detail}",
                code="content_fact_unverified",
            )

    review = ContentReview(
        project_id=ctx.project.id,
        version_id=version.id,
        reviewer_id=ctx.user.id,
        decision=payload.decision,
        comment=payload.comment,
        content_hash_snapshot=version.content_hash,
    )
    db.add(review)
    target = (
        ContentStatus.APPROVED
        if payload.decision == ReviewDecision.APPROVED
        else ContentStatus.REJECTED
    )
    version.status = ensure_content_transition(version.status, target)
    _sync_item_status(item, version)
    db.flush()
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.review",
        target_type="content_version",
        target_id=version.id,
        payload={
            "decision": payload.decision.value,
            "content_hash_snapshot": review.content_hash_snapshot,
            "review_id": str(review.id),
        },
    )
    db.commit()
    return ok({"review_id": str(review.id), "decision": payload.decision.value})


@router.get(
    "/content-versions/{version_id}/links",
    response_model=Envelope[ContentVersionLinksData],
)
def get_content_links(
    version_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", id=version_id
    )
    return ok(_version_links(db, version.id))


@router.put(
    "/content-versions/{version_id}/links",
    response_model=Envelope[ContentVersionLinksData],
)
def replace_content_links(
    version_id: uuid.UUID,
    payload: ContentVersionLinksUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    """整版替换题目/证据/事实关联；只允许当前版本，避免历史稿被误改。

    关联是版本级元数据，不改变正文与原子的 content_hash；审批后的版本也可
    补挂证据，供发布侧 trace 与覆盖巡检反查。事实修订后只有显式
    `confirm_fact_revisions=true` 才把关联版本推进到当前值，普通保存不静默确认。
    """
    version = require_scoped_row(
        db,
        ContentVersion,
        ctx.project.id,
        resource="content_version",
        for_update=True,
        id=version_id,
    )
    item = require_scoped_row(
        db, ContentItem, ctx.project.id, resource="content_item", id=version.item_id
    )
    if item.current_version_id != version.id:
        raise ReviewStateError("只能维护当前内容版本的题目/证据关联")

    question_ids = list(dict.fromkeys(payload.question_ids))
    citation_ids = list(dict.fromkeys(payload.citation_ids))
    fact_ids = list(dict.fromkeys(payload.fact_ids))

    if question_ids:
        rows = db.scalars(
            select(Question).where(
                Question.project_id == ctx.project.id,
                Question.id.in_(question_ids),
            )
        ).all()
        if {row.id for row in rows} != set(question_ids):
            raise ResourceMissingError("题目不存在或不属于本项目")

    if citation_ids:
        rows = db.scalars(
            select(MonitoringCitation).where(
                MonitoringCitation.project_id == ctx.project.id,
                MonitoringCitation.id.in_(citation_ids),
            )
        ).all()
        if {row.id for row in rows} != set(citation_ids):
            raise ResourceMissingError("引用证据不存在或不属于本项目")

    facts_by_id: dict[uuid.UUID, Fact] = {}
    if fact_ids:
        rows = db.scalars(
            select(Fact).where(
                Fact.project_id == ctx.project.id,
                Fact.id.in_(fact_ids),
            )
        ).all()
        if {row.id for row in rows} != set(fact_ids):
            raise ResourceMissingError("事实不存在或不属于本项目")
        facts_by_id = {row.id: row for row in rows}

    question_rows = db.scalars(
        select(ContentVersionQuestion).where(
            ContentVersionQuestion.version_id == version.id
        )
    ).all()
    existing_questions = {row.question_id for row in question_rows}
    desired_questions = set(question_ids)
    for row in question_rows:
        if row.question_id not in desired_questions:
            db.delete(row)
    for question_id in desired_questions - existing_questions:
        db.add(
            ContentVersionQuestion(
                project_id=ctx.project.id,
                version_id=version.id,
                question_id=question_id,
            )
        )

    citation_rows = db.scalars(
        select(ContentVersionCitation).where(
            ContentVersionCitation.version_id == version.id
        )
    ).all()
    existing_citations = {row.citation_id for row in citation_rows}
    desired_citations = set(citation_ids)
    for row in citation_rows:
        if row.citation_id not in desired_citations:
            db.delete(row)
    for citation_id in desired_citations - existing_citations:
        db.add(
            ContentVersionCitation(
                project_id=ctx.project.id,
                version_id=version.id,
                citation_id=citation_id,
            )
        )

    fact_rows = db.scalars(
        select(ContentVersionFact).where(ContentVersionFact.version_id == version.id)
    ).all()
    existing_facts = {row.fact_id: row for row in fact_rows}
    desired_facts = set(fact_ids)
    for fact_id, row in existing_facts.items():
        if fact_id not in desired_facts:
            db.delete(row)
    confirmed_revisions: list[str] = []
    for fact_id in desired_facts:
        fact = facts_by_id[fact_id]
        row = existing_facts.get(fact_id)
        if row is None:
            db.add(
                ContentVersionFact(
                    project_id=ctx.project.id,
                    version_id=version.id,
                    fact_id=fact_id,
                    fact_version_no=fact.version_no,
                )
            )
        elif row.fact_version_no != fact.version_no and payload.confirm_fact_revisions:
            row.fact_version_no = fact.version_no
            confirmed_revisions.append(str(fact_id))

    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.links_update",
        target_type="content_version",
        target_id=version.id,
        payload={
            "question_ids": [str(row) for row in question_ids],
            "citation_ids": [str(row) for row in citation_ids],
            "fact_ids": [str(row) for row in fact_ids],
            "confirmed_fact_revisions": confirmed_revisions,
        },
    )
    db.commit()
    return ok(_version_links(db, version.id))


@router.post(
    "/content-versions/{version_id}/status",
    response_model=Envelope[ContentStatusChanged],
)
def change_content_status(
    version_id: uuid.UUID,
    payload: ContentStatusUpdate,
    ctx: ProjectContext = Depends(require_permission("content.write")),
    db: Session = Depends(get_db),
) -> dict:
    """手动触发排期/需关注；已发布只能由发布回执或核实结案。"""
    if payload.status not in (ContentStatus.PENDING_PUBLISH, ContentStatus.NEEDS_ATTENTION):
        raise ReviewStateError("只支持手动切换为 scheduled 或 needs_attention；published 由发布回执自动结案")

    version = require_scoped_row(
        db,
        ContentVersion,
        ctx.project.id,
        resource="content_version",
        for_update=True,
        id=version_id,
    )
    item = require_scoped_row(
        db, ContentItem, ctx.project.id, resource="content_item", id=version.item_id
    )
    if item.current_version_id != version.id:
        raise ReviewStateError("只能切换当前内容版本的状态")

    from_status = version.status
    target = mark_version_status(db, version, payload.status)
    record_audit(
        db,
        project_id=ctx.project.id,
        actor_id=ctx.user.id,
        action="content.status_change",
        target_type="content_version",
        target_id=version.id,
        payload={"from": from_status.value, "to": target.value},
    )
    db.commit()
    return ok(
        {
            "version_id": str(version.id),
            "status": version.status.value,
            "item_status": item.status.value,
        }
    )


def _body_to_html(body: str) -> str:
    """纯文本正文 → 基础 HTML：空行分段、`#`/`##`/`###` 作标题、`- `/`* ` 作列表项。

    正文存的是纯文本，这里只做到"粘进 CMS 编辑器结构不丢"，不做富文本保真。
    """
    blocks: list[str] = []
    items: list[str] = []

    def flush_list() -> None:
        if items:
            blocks.append("<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>")
            items.clear()

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            flush_list()
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1)) + 1
            line = line[heading.end():].strip()
            flush_list()
            blocks.append(f"<h{level}>{html.escape(line)}</h{level}>")
            continue
        if line.startswith("- ") or line.startswith("* "):
            items.append(html.escape(line[2:].strip()))
            continue
        flush_list()
        blocks.append(f"<p>{html.escape(line)}</p>")
    flush_list()
    return "\n".join(blocks)


def _meta_description(body: str, limit: int = 120) -> str:
    """把正文压成一行摘要建议值：去掉行首 markdown 标记与 HTML 标签。"""
    lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        line = _HEADING_RE.sub("", line, count=1)
        for prefix in ("- ", "* "):
            if line.startswith(prefix):
                line = line[len(prefix):].strip()
                break
        if line:
            lines.append(line)
    compact = re.sub(r"<[^>]+>", "", " ".join(lines))
    compact = re.sub(r"\s+", " ", compact).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "…"


def _demote_h1(body: str) -> str:
    """正文里的 `# 小标题` 降为 `## `：交付包自身已有一级标题，不能出现两个 h1。

    HTML 侧 `_body_to_html` 本来就把 `# ` 转成 h2，这里让 markdown 与之一致。
    """
    return re.sub(r"(?m)^#[ \t\u3000]+", "## ", body)


def _word_count(body: str) -> int:
    """估算 JSON-LD wordCount：中文按字符数 / 1.5，英文按词数计。

    schema.org 的 wordCount 是词数，中文不能直接拿 len(body) 当词数；这里只
    做交付包的建议值，不承诺与官网 CMS 的分词器完全一致。
    """
    text = re.sub(r"<[^>]+>", " ", body)
    text = _HEADING_RE.sub("", text)
    cjk = len(_CJK_RE.findall(text))
    latin = len(_LATIN_WORD_RE.findall(text))
    return round(cjk / 1.5) + latin


def _slug_suggestion(title: str, item_id: uuid.UUID) -> str:
    """CMS slug 建议：只取标题里的英文单词，取不到就退回 item id 前 8 位。

    纯数字（日期、价格、电话）不参与拼 slug——否则标题"交付包联调 2026-11-17"
    会被拼成 slug `2026-11-17`。
    """
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", title.lower())
    if words:
        return "-".join(words)[:64]
    return f"content-{str(item_id)[:8]}"


@router.get(
    "/content-versions/{version_id}/export",
    response_model=Envelope[ContentExportPackage],
)
def export_content_version(
    version_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("content.read")),
    db: Session = Depends(get_db),
) -> dict:
    """交付包：把版本正文整理成可直接粘进公司官网 CMS 的成品。

    公开页由公司官网渲染（2026-11-17 决策），本接口只出"内容 + 结构化片段"，
    不生成页面、不写 public_pages；发布后由人回填 URL 与状态。
    """
    version = require_scoped_row(
        db, ContentVersion, ctx.project.id, resource="content_version", id=version_id
    )
    item = require_scoped_row(db, ContentItem, ctx.project.id, resource="content_item", id=version.item_id)
    page = db.scalar(
        select(PublicPage)
        .where(
            PublicPage.project_id == ctx.project.id,
            PublicPage.content_item_id == item.id,
        )
        .order_by(PublicPage.created_at.desc())
    )
    canonical = page.url if page is not None else None
    description = _meta_description(version.body)
    jsonld: list[dict] = [
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": item.title,
            "description": description,
            "inLanguage": "zh-CN",
            "wordCount": _word_count(version.body),
            "publisher": {"@type": "Organization", "name": ctx.project.name},
            **({"url": canonical} if canonical else {}),
            **(
                {"mainEntityOfPage": {"@type": "WebPage", "@id": canonical}}
                if canonical
                else {}
            ),
        }
    ]
    checklist = [
        "标题：粘到公司站文章标题（不要改事实数字）",
        "正文：在编辑器 HTML 模式下粘入 html 字段",
        "摘要：用 meta_description 填 description/SEO 摘要",
        "canonical：指向公司站该页最终 URL",
        "发布后回填：PATCH /pages 的 url 与 publish_status",
    ]
    return ok(
        {
            "version_id": str(version.id),
            "item_id": str(item.id),
            "title": item.title,
            "slug_suggestion": _slug_suggestion(item.title, item.id),
            "version_no": version.version_no,
            "status": version.status,
            "content_hash": version.content_hash,
            "markdown": f"# {item.title}\n\n{_demote_h1(version.body)}",
            "html": _body_to_html(version.body),
            "meta_description": description,
            "canonical_hint": canonical,
            "jsonld": jsonld,
            "checklist": checklist,
        }
    )
