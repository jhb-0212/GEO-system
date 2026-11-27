"""知识库接口：素材解析、切块回查、检索与候选事实人工确认。

解析同步执行（20 页文本 PDF 的验收线是 2 分钟），不把长任务塞进请求之外；
候选事实采纳只创建 draft 事实，仍走现有事实审批链，不自动批准。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, require_permission
from app.api.responses import COMMON_ERRORS, Envelope, PagedEnvelope, ok, ok_page
from app.db.session import get_db
from app.models import KnowledgeCandidateFact, KnowledgeDocument, Material
from app.models.enums import KnowledgeCandidateStatus
from app.schemas import KnowledgeCandidateAccept, KnowledgeCandidateReject
from app.services import knowledge_base, knowledge_search
from app.services.project_scope import require_scoped_row

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/knowledge",
    tags=["知识库"],
    responses=COMMON_ERRORS,
)


@router.post("/documents/{material_id}/parse", response_model=Envelope[dict])
def parse_material(
    material_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("knowledge.write")),
    db: Session = Depends(get_db),
) -> dict:
    material = require_scoped_row(
        db, Material, ctx.project.id, resource="material", id=material_id
    )
    return ok(
        knowledge_base.parse_material(
            db, project_id=ctx.project.id, material=material, actor_id=ctx.user.id
        )
    )


@router.get("/documents", response_model=PagedEnvelope[dict])
def list_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    ctx: ProjectContext = Depends(require_permission("knowledge.read")),
    db: Session = Depends(get_db),
) -> dict:
    rows, total = knowledge_base.list_documents(
        db, ctx.project.id, page=page, page_size=page_size
    )
    return ok_page(rows, page=page, page_size=page_size, total=total)


@router.get("/documents/{document_id}/chunks", response_model=PagedEnvelope[dict])
def list_chunks(
    document_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    ctx: ProjectContext = Depends(require_permission("knowledge.read")),
    db: Session = Depends(get_db),
) -> dict:
    require_scoped_row(
        db, KnowledgeDocument, ctx.project.id, resource="knowledge_document", id=document_id
    )
    rows, total = knowledge_base.list_chunks(
        db, ctx.project.id, document_id, page=page, page_size=page_size
    )
    return ok_page(rows, page=page, page_size=page_size, total=total)


@router.get("/search", response_model=Envelope[dict])
def search(
    q: str = Query(min_length=1, max_length=200),
    top_k: int = Query(default=8, ge=1, le=20),
    ctx: ProjectContext = Depends(require_permission("knowledge.read")),
    db: Session = Depends(get_db),
) -> dict:
    return ok(knowledge_search.search_chunks(db, project_id=ctx.project.id, query=q, top_k=top_k))


@router.get("/candidate-facts", response_model=PagedEnvelope[dict])
def list_candidate_facts(
    status: KnowledgeCandidateStatus | None = Query(default=None),
    document_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    ctx: ProjectContext = Depends(require_permission("knowledge.read")),
    db: Session = Depends(get_db),
) -> dict:
    rows, total = knowledge_base.list_candidates(
        db,
        ctx.project.id,
        status=status,
        document_id=document_id,
        page=page,
        page_size=page_size,
    )
    return ok_page(rows, page=page, page_size=page_size, total=total)


@router.post("/candidate-facts/{candidate_id}/accept", response_model=Envelope[dict])
def accept_candidate_fact(
    candidate_id: uuid.UUID,
    payload: KnowledgeCandidateAccept,
    ctx: ProjectContext = Depends(require_permission("knowledge.write")),
    db: Session = Depends(get_db),
) -> dict:
    candidate = require_scoped_row(
        db,
        KnowledgeCandidateFact,
        ctx.project.id,
        resource="knowledge_candidate_fact",
        id=candidate_id,
    )
    return ok(
        knowledge_base.accept_candidate(
            db,
            project_id=ctx.project.id,
            candidate=candidate,
            actor_id=ctx.user.id,
            fact_type=payload.fact_type,
            fact_key=payload.fact_key,
            fact_value=payload.fact_value,
            change_note=payload.change_note,
        )
    )


@router.post("/candidate-facts/{candidate_id}/reject", response_model=Envelope[dict])
def reject_candidate_fact(
    candidate_id: uuid.UUID,
    payload: KnowledgeCandidateReject,
    ctx: ProjectContext = Depends(require_permission("knowledge.write")),
    db: Session = Depends(get_db),
) -> dict:
    candidate = require_scoped_row(
        db,
        KnowledgeCandidateFact,
        ctx.project.id,
        resource="knowledge_candidate_fact",
        id=candidate_id,
    )
    return ok(
        knowledge_base.reject_candidate(
            db,
            project_id=ctx.project.id,
            candidate=candidate,
            actor_id=ctx.user.id,
            note=payload.note,
        )
    )
