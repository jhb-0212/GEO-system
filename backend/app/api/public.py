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
from app.schemas.report_shares import ReportSharePassword
from app.services.branding import organization_branding
from app.services.queries import fetch_many, fetch_one
from app.services.rate_limit import IpWindowLimiter
from app.services.report_shares import public_share_meta, public_share_payload

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

    project = fetch_one(db, Project, code=project_code, status=ProjectStatus.ACTIVE)
    if project is None:
        # 非 active 项目同样按不存在处理，不暴露项目是否曾经存在。
        raise ResourceMissingError("项目不存在", code="project_missing")
    rows = fetch_many(
        db,
        Faq,
        [
            Faq.project_id == project.id,
            Faq.status == FaqStatus.PUBLISHED,
            Faq.deleted_at.is_(None),
        ],
        order_by=(Faq.sort_order, Faq.created_at),
        limit=limit,
    )
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


# 白标配置与 FAQ 同源限流口径；单独命名空间，避免两种流量互相抢额度
_branding_limiter = IpWindowLimiter(
    namespace="public:branding",
    per_minute=settings.public_faq_per_minute,
)


# ---- 月报只读分享：链接持有者可见，密码校验与正文访问共用同一限流命名空间 ----
_report_limiter = IpWindowLimiter(
    namespace="public:report-share",
    per_minute=settings.public_report_per_minute,
)


def _consume_report_limit(request: Request) -> None:
    _report_limiter.per_minute = settings.public_report_per_minute
    if not _report_limiter.consume(client_ip(request)):
        raise TooManyRequestsError(
            "报告访问过于频繁，请稍后再试", code="public_report_rate_limited"
        )


@router.get("/reports/{token}", response_model=Envelope[dict])
def public_report_meta(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """分享页的公开元信息：品牌、月份、是否需要密码。

    不返回报告正文；无效、过期、吊销的令牌统一 404，不区分原因。
    """
    _consume_report_limit(request)
    return ok(public_share_meta(db, token))


@router.post("/reports/{token}/access", response_model=Envelope[dict])
def public_report_access(
    token: str,
    payload: ReportSharePassword,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """校验密码并返回冻结月报正文；成功后累加访问次数并记录最近访问时间。"""
    _consume_report_limit(request)
    result = public_share_payload(db, token=token, password=payload.password)
    db.commit()
    return ok(result)



@router.get("/projects/{project_code}/branding", response_model=Envelope[dict])
def public_branding(
    project_code: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """登录页/公开页白标：只返回展示字段，不返回客户内部配置。

    `hide_vendor_brand` 只影响客户可见页；系统内部工作台始终保留产品标识。
    """
    _branding_limiter.per_minute = settings.public_faq_per_minute
    if not _branding_limiter.consume(client_ip(request)):
        raise TooManyRequestsError("白标配置请求过于频繁，请稍后再试", code="public_rate_limited")
    project = fetch_one(db, Project, code=project_code, status=ProjectStatus.ACTIVE)
    if project is None:
        raise ResourceMissingError("项目不存在", code="project_not_found")
    branding = organization_branding(db, project.id)
    return ok({
        "project_name": project.name,
        "branding": branding,
        "hide_vendor_brand": bool(branding.get("hide_vendor_brand")),
    })
