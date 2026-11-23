"""公开只读接口：公开站 FAQ 不经过登录，只返回已上架条目。

无需登录意味着任何人都能刷，所以按来源 IP 每分钟限额；取 IP 的口径必须与登录
限流共用 `app.core.net.client_ip`，不做第二套解析，否则伪造转发头就能挑宽松的
那一套绕过。
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.responses import COMMON_ERRORS, Envelope, PublicFaqData, ok
from app.core.config import settings
from app.core.errors import ResourceMissingError, TooManyRequestsError
from app.core.net import client_ip
from app.db.session import get_db
from app.models import Faq, Project
from app.models.enums import FaqStatus, ProjectStatus
from app.services.microsite import public_snapshot
from app.services.rate_limit import IpWindowLimiter

router = APIRouter(prefix="/api/v1/public", tags=["公开接口"], responses=COMMON_ERRORS)

# 模块级实例便于测试注入 FakeRedis；额度来自配置，生产与登录限流共用同一 Redis。
_faq_limiter = IpWindowLimiter(
    namespace="public:faq",
    per_minute=settings.public_faq_per_minute,
)


@router.get("/projects/{project_code}/faqs", response_model=Envelope[list[PublicFaqData]])
def public_faqs(
    project_code: str,
    request: Request,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=200),
) -> dict:
    # 模块级实例在 import 时读到的额度可能已经过时（改配置或测试替换 settings），
    # 每请求同步一次，避免「改了配额必须重启」。
    _faq_limiter.per_minute = settings.public_faq_per_minute
    if not _faq_limiter.consume(client_ip(request)):
        raise TooManyRequestsError(
            "公开 FAQ 请求过于频繁，请稍后再试", code="public_rate_limited"
        )

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


# 微站渲染与 FAQ 同源限流口径；单独命名空间，避免两种流量互相抢额度
_site_limiter = IpWindowLimiter(
    namespace="public:site",
    per_minute=settings.public_faq_per_minute,
)


@router.get("/sites/{slug}", response_model=Envelope[dict])
def public_site(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """公开微站：未发布与不存在都返回同一句 404，不暴露站点是否已建。"""
    _site_limiter.per_minute = settings.public_faq_per_minute
    if not _site_limiter.consume(client_ip(request)):
        raise TooManyRequestsError("公开站请求过于频繁，请稍后再试", code="public_rate_limited")
    snapshot = public_snapshot(db, slug)
    if snapshot is None:
        raise ResourceMissingError("站点不存在或未发布", code="site_not_found")
    return ok(snapshot)
