"""公开只读接口：公开站 FAQ 不经过登录，只返回已上架条目。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.responses import COMMON_ERRORS, Envelope, PublicFaqData, ok
from app.core.errors import ResourceMissingError
from app.db.session import get_db
from app.models import Faq, Project
from app.models.enums import FaqStatus, ProjectStatus

router = APIRouter(prefix="/api/v1/public", tags=["公开接口"], responses=COMMON_ERRORS)


@router.get("/projects/{project_code}/faqs", response_model=Envelope[list[PublicFaqData]])
def public_faqs(
    project_code: str,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=200),
) -> dict:
    project = db.scalar(
        select(Project).where(
            Project.code == project_code,
            Project.status == ProjectStatus.ACTIVE,
        )
    )
    if project is None:
        # 非 active 项目同样按不存在处理，不暴露项目是否曾经存在。
        raise ResourceMissingError("项目不存在", code="project_missing")
    rows = db.scalars(
        select(Faq)
        .where(
            Faq.project_id == project.id,
            Faq.status == FaqStatus.PUBLISHED,
            Faq.deleted_at.is_(None),
        )
        .order_by(Faq.sort_order, Faq.created_at)
        .limit(limit)
    ).all()
    return ok(
        [
            {
                "id": str(row.id),
                "question": row.question,
                "answer": row.answer,
                "category": row.category,
                "sort_order": row.sort_order,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]
    )
