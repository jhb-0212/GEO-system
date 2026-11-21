"""月报与线索漏斗只读接口回归。"""

import uuid
from datetime import datetime, timezone

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_monthly_report_markdown_export(
    client, project_factory, user_factory, member_factory
):
    """P33 首月报告 Markdown：真实月报接口 + 证据覆盖 + 下月选题。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"report-md-{suffix}")
    admin = user_factory(f"report-md-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    resp = client.get(
        f"/api/v1/projects/{project.id}/stats/monthly-report.md?month=2026-11",
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    assert "text/markdown" in resp.headers["content-type"]
    assert "首月报告" in resp.text
    assert "监测完成情况" in resp.text
    assert "样本证据覆盖" in resp.text
    assert "通用题" in resp.text
    assert "品牌题" in resp.text
    assert "引用可观测" in resp.text
    assert "不可观测" in resp.text
    assert "下月选题" in resp.text


def test_monthly_report_markdown_without_lead_permission(
    client, project_factory, user_factory, member_factory
):
    """无线索权限时月报仍可导出，但线索段必须显式裁剪。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"report-md-no-lead-{suffix}")
    editor = user_factory(f"report-md-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    resp = client.get(
        f"/api/v1/projects/{project.id}/stats/monthly-report.md?month=2026-11",
        headers=_auth(editor),
    )
    assert resp.status_code == 200, resp.text
    assert "没有线索查看权限" in resp.text
    assert "线索总数" not in resp.text


def test_lead_funnel_and_monthly_report(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"report-{suffix}")
    lead_ops = user_factory(f"report-lead-{suffix}")
    admin = user_factory(f"report-admin-{suffix}")
    reviewer = user_factory(f"report-reviewer-{suffix}")
    member_factory(project, lead_ops, RoleCode.LEAD_OPS)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    member_factory(project, reviewer, RoleCode.REVIEWER)

    leads = []
    for name, source, valid in (
        ("已报名", "官网", True),
        ("已联系", "到校", True),
        ("无效", "官网", False),
    ):
        response = client.post(
            f"/api/v1/projects/{project.id}/leads",
            json={
                "contact_name": name,
                "contact_phone": "13800000000",
                "lead_source": source,
                "is_valid": valid,
            },
            headers=_auth(lead_ops),
        )
        assert response.status_code == 201, response.text
        leads.append(response.json()["data"]["id"])

    enrolled = client.patch(
        f"/api/v1/projects/{project.id}/leads/{leads[0]}",
        json={"enrollment_status": "enrolled"},
        headers=_auth(lead_ops),
    )
    assert enrolled.status_code == 200, enrolled.text
    contacted = client.patch(
        f"/api/v1/projects/{project.id}/leads/{leads[1]}",
        json={"enrollment_status": "contacted"},
        headers=_auth(lead_ops),
    )
    assert contacted.status_code == 200, contacted.text

    funnel = client.get(f"/api/v1/projects/{project.id}/leads/funnel", headers=_auth(lead_ops))
    assert funnel.status_code == 200, funnel.text
    data = funnel.json()["data"]
    assert (data["total"], data["valid"], data["contacted"], data["enrolled"], data["lost"]) == (
        3,
        2,
        2,
        1,
        0,
    )
    assert data["status_counts"] == {
        "unknown": 1,
        "contacted": 1,
        "enrolled": 1,
        "lost": 0,
    }
    assert data["stages"][-1] == {
        "key": "enrolled",
        "label": "已报名",
        "count": 1,
        "rate": 0.3333,
        "step_rate": 0.5,
    }
    source_rows = {row["label"]: row for row in data["by_source"]}
    assert source_rows["官网"]["total"] == 2
    assert source_rows["官网"]["valid"] == 1
    assert source_rows["到校"]["enrolled"] == 0

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    monthly = client.get(
        f"/api/v1/projects/{project.id}/stats/monthly",
        params={"month": month},
        headers=_auth(admin),
    )
    assert monthly.status_code == 200, monthly.text
    report = monthly.json()["data"]
    assert report["month"] == month
    assert report["tasks"]["total"] == 0
    assert report["tasks"]["completion_rate"] is None
    assert report["leads"]["total"] == 3
    assert report["published_receipts"] == 0

    # 审核只有 stats.read、没有 lead.read：月报仍可读，但线索段必须为空。
    reviewer_monthly = client.get(
        f"/api/v1/projects/{project.id}/stats/monthly",
        params={"month": month},
        headers=_auth(reviewer),
    )
    assert reviewer_monthly.status_code == 200, reviewer_monthly.text
    assert reviewer_monthly.json()["data"]["leads"] is None

    bad_month = client.get(
        f"/api/v1/projects/{project.id}/stats/monthly",
        params={"month": "2026-13"},
        headers=_auth(admin),
    )
    assert bad_month.status_code == 400, bad_month.text
    assert bad_month.json()["error"]["code"] == "invalid_month"
