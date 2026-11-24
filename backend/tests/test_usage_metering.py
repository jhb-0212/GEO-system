"""消耗计量：六项口径、账本幂等、额度只提示不拦截。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import Lead, UsageEvent
from app.models.enums import RoleCode
from app.models.industry import Organization
from app.services import usage_metering
from app.services.audit import record_export

SIX_METRICS = {"collection", "generation", "publishing", "reachability", "report_export", "microsite_lead"}


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _suffix() -> str:
    return uuid.uuid4().hex[:6]


def test_record_is_idempotent_and_fills_org(db, project_factory):
    project = project_factory(f"usage-rec-{_suffix()}")

    assert usage_metering.record(
        db, project_id=project.id, metric="reachability", quantity=3,
        source_type="reachability_batch", source_id="batch-1",
    ) is True
    # 同一业务事实重放：不重复计数
    assert usage_metering.record(
        db, project_id=project.id, metric="reachability", quantity=3,
        source_type="reachability_batch", source_id="batch-1",
    ) is False

    rows = db.scalars(select(UsageEvent).where(UsageEvent.project_id == project.id)).all()
    assert len(rows) == 1
    assert rows[0].quantity == 3
    assert rows[0].organization_id == project.organization_id


def test_summary_covers_six_metrics_with_units(db, project_factory, user_factory, member_factory, client):
    suffix = _suffix()
    project = project_factory(f"usage-sum-{suffix}")
    admin = user_factory(f"usage-sum-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    db.add(Lead(project_id=project.id, lead_source="microsite"))
    usage_metering.record(
        db, project_id=project.id, metric="report_export", quantity=1,
        source_type="audit_export", source_id=str(uuid.uuid4()),
        meta={"export_type": "stats"},
    )
    db.commit()

    summary = usage_metering.summarize(db, project_id=project.id)
    metrics = {row["metric"]: row for row in summary["metrics"]}
    assert set(metrics) == SIX_METRICS
    assert metrics["microsite_lead"]["quantity"] == 1
    assert metrics["microsite_lead"]["unit"] == "条"
    assert metrics["microsite_lead"]["basis"] == "facts"
    assert metrics["report_export"]["quantity"] == 1
    assert metrics["report_export"]["basis"] == "events"
    assert metrics["report_export"]["detail"][0]["key"] == "stats"
    assert metrics["collection"]["basis"] == "facts"
    # 单位不同，不给合计，避免把「篇」和「条」相加
    assert "total" not in summary

    response = client.get(f"/api/v1/projects/{project.id}/consumption", headers=_auth(admin))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert {row["metric"] for row in data["metrics"]} == SIX_METRICS
    assert data["scope"] == "project"


def test_quota_only_warns_never_blocks(db, project_factory):
    project = project_factory(f"usage-quota-{_suffix()}")
    organization = db.scalar(select(Organization).where(Organization.id == project.organization_id))
    assert organization is not None
    organization.settings = {"quotas": {"consumption": {"microsite_lead": 1}}}

    db.add(Lead(project_id=project.id, lead_source="microsite"))
    db.flush()

    summary = usage_metering.summarize(db, project_id=project.id)
    lead_row = next(row for row in summary["metrics"] if row["metric"] == "microsite_lead")
    assert lead_row["quantity"] == 1
    assert lead_row["quota"]["level"] == "exceeded"
    assert "不拦截" in lead_row["quota"]["message"]
    assert any(alert["metric"] == "microsite_lead" for alert in summary["alerts"])


def test_export_audit_writes_usage_event(db, project_factory, user_factory):
    suffix = _suffix()
    project = project_factory(f"usage-exp-{suffix}")
    user = user_factory(f"usage-exp-user-{suffix}")

    audit = record_export(db, project_id=project.id, actor_id=user.id, export_type="stats", row_count=10)
    db.commit()

    rows = db.scalars(
        select(UsageEvent).where(UsageEvent.project_id == project.id, UsageEvent.metric == "report_export")
    ).all()
    assert len(rows) == 1
    assert rows[0].source_id == str(audit.id)
    assert rows[0].meta["export_type"] == "stats"


def test_range_validation_is_explicit(db, project_factory):
    project = project_factory(f"usage-range-{_suffix()}")
    try:
        usage_metering.summarize(db, "2026-11-24", "2026-11-01", project_id=project.id)
    except ValueError as exc:
        assert "start 不能晚于 end" in str(exc)
    else:
        raise AssertionError("非法区间必须报错，不能静默返回空数据")
