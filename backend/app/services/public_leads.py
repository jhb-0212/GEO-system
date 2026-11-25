"""公开微站线索提交：按 slug 定位项目，不经过工作台权限。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import Lead, MonitoringSample, Project, Question, SiteSite
from app.models.enums import ProjectStatus
from app.schemas import PublicLeadCreate
from app.services import lead_attribution
from app.services.lead_visitors import hash_visitor


def _project_of_site(db: Session, slug: str) -> tuple[SiteSite, Project]:
    site = db.scalar(select(SiteSite).where(SiteSite.slug == slug, SiteSite.is_published.is_(True)))
    if site is None:
        raise ResourceMissingError("站点不存在", code="site_missing")
    project = db.scalar(select(Project).where(
        Project.id == site.project_id, Project.status == ProjectStatus.ACTIVE
    ))
    if project is None:
        raise ResourceMissingError("站点不存在", code="site_missing")
    return site, project


def _resolve_attribution(db: Session, project_id, body: PublicLeadCreate) -> tuple:
    sample_id = body.source_sample_id
    question_id = body.source_question_id
    if sample_id is not None:
        sample = db.scalar(select(MonitoringSample).where(
            MonitoringSample.id == sample_id, MonitoringSample.project_id == project_id
        ))
        if sample is None:
            sample_id = None
    if question_id is not None:
        question = db.scalar(select(Question).where(
            Question.id == question_id, Question.project_id == project_id
        ))
        if question is None:
            question_id = None
    return sample_id, question_id


def create_public_lead(db: Session, *, slug: str, body: PublicLeadCreate, ip: str | None, landing_url: str) -> dict:
    site, project = _project_of_site(db, slug)
    sample_id, question_id = _resolve_attribution(db, project.id, body)
    lead = Lead(
        project_id=project.id,
        lead_source="microsite",
        source_question_id=question_id,
        landing_url=landing_url[:512],
        utm_campaign=(body.utm_campaign or "").strip()[:128] or None,
        contact_name=(body.contact_name or "").strip()[:64] or None,
        contact_phone=(body.contact_phone or "").strip()[:64] or None,
        contact_wechat=(body.contact_wechat or "").strip()[:64] or None,
        note=(body.note or "").strip()[:1000] or None,
        ip_hash=hash_visitor(ip),
    )
    db.add(lead)
    db.flush()
    attribution = lead_attribution.create_for_lead(
        db, lead,
        sample_id=sample_id, content_item_id=None, article_url=landing_url,
        question_id=question_id,
    )
    db.commit()
    return {
        "lead_id": str(lead.id),
        "serial_no": lead.serial_no,
        "attribution_confidence": attribution.confidence.value if attribution else "low",
    }
