"""B5 体检引擎：逐项达成率，不出总分。

钉住五条：
1. 12 项全部返回，且顶层没有任何 score / total_percent 字段；
2. 空项目里「分母为 0」的项是 unknown，不是 fail（没有数据不等于没做）；
3. 补齐企业档案 6 段后该项从 fail 变 pass；
4. 跑两次留两条快照，历史可回看；单条快照能取回且项数一致；
5. 跨项目拿不到别人的体检记录（项目隔离）。
"""

import uuid

from app.core.security import create_access_token
from app.models import CompanyProfile, HealthCheckItem
from app.models.enums import HealthCheckStatus, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _setup(project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"hc-{suffix}")
    user = user_factory(f"hc-u-{suffix}")
    member_factory(project, user, RoleCode.EDITOR)
    return project, user


def _run(client, project, user) -> dict:
    resp = client.post(f"/api/v1/projects/{project.id}/health-checks", headers=_auth(user))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _item(data: dict, key: str) -> dict:
    return next(item for item in data["items"] if item["check_key"] == key)


def test_empty_project_marks_unknown_not_fail(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    data = _run(client, project, user)

    assert data["ruleset_version"] == "1"
    assert data["totals"]["total"] == 12
    # 顶层不给分：只有计数和逐项
    assert "score" not in data and "total_percent" not in data

    # 没有任何渠道 → 准入率无法计算，不能判成 0%
    channel_item = _item(data, "channel_approval")
    assert channel_item["denominator"] == 0
    assert channel_item["status"] == "unknown"
    assert channel_item["ratio"] is None

    # 企业档案一条都没有 → 有分母（6 段），所以是 fail 而不是 unknown
    company_item = _item(data, "company_profile_segments")
    assert company_item["numerator"] == 0
    assert company_item["denominator"] == 6
    assert company_item["status"] == "fail"
    assert "企业档案" in company_item["hint"]


def test_company_profile_filled_flips_to_pass(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    db.add(
        CompanyProfile(
            project_id=project.id,
            legal_name="广东省 AI 数字人才就业实训基地",
            description="面向应届生的 AI 实训基地，三个月项目制。",
            highlights="真实项目、企业导师、就业推荐。",
            products=[{"name": "AI 数据标注实训"}],
            official_urls=["https://gdccai.com"],
            industries=["教育", "人工智能"],
        )
    )
    db.commit()

    data = _run(client, project, user)
    item = _item(data, "company_profile_segments")
    assert item["numerator"] == 6
    assert item["status"] == "pass"
    assert item["ratio"] == 1.0


def test_runs_are_persisted_and_listable(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    first = _run(client, project, user)
    second = _run(client, project, user)

    history = client.get(f"/api/v1/projects/{project.id}/health-checks", headers=_auth(user))
    assert history.status_code == 200, history.text
    runs = history.json()["data"]
    assert len(runs) == 2
    assert {run["run_id"] for run in runs} == {str(first["run_id"]), str(second["run_id"])}

    detail = client.get(
        f"/api/v1/projects/{project.id}/health-checks/{first['run_id']}", headers=_auth(user)
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()["data"]
    assert len(body["items"]) == 12
    # 快照是落库的，不是每次现算：项数与库里一致
    stored = db.query(HealthCheckItem).filter(HealthCheckItem.run_id == first["run_id"]).count()
    assert stored == 12


def test_all_status_values_are_known(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    data = _run(client, project, user)
    allowed = {status.value for status in HealthCheckStatus}
    assert {item["status"] for item in data["items"]} <= allowed
    # 计数一致：total = pass + fail + unknown
    totals = data["totals"]
    assert totals["passed"] + totals["failed"] + totals["unknown"] == totals["total"]


def test_run_is_project_scoped(client, db, project_factory, user_factory, member_factory, two_projects):
    project_a, project_b = two_projects
    user = user_factory(f"hc-scoped-{uuid.uuid4().hex[:6]}")
    member_factory(project_a, user, RoleCode.EDITOR)
    member_factory(project_b, user, RoleCode.EDITOR)

    run = _run(client, project_a, user)
    # 同一个用户、同一个 token，换项目号取不到 A 的体检
    resp = client.get(
        f"/api/v1/projects/{project_b.id}/health-checks/{run['run_id']}", headers=_auth(user)
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "health_run_not_found"
