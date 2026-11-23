"""B4 获客：访客哈希去重 + 留言。

钉住四条边界：
1. 只存 IP 哈希，不存原文；对外只露 8 位前缀；
2. 同一 IP 两条线索 = 1 个去重访客，重复率可算；
3. 访客留言默认未读，运营回复默认已读，标记已读后未读归零；
4. 留言读写按项目隔离，跨项目 403。
"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import Lead, LeadMessage
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _project_and_ops(project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"lead-b4-{suffix}")
    ops = user_factory(f"lead-b4-ops-{suffix}")
    member_factory(project, ops, RoleCode.LEAD_OPS)
    return project, ops


def _create_lead(client, project, user, **overrides):
    payload = {"contact_name": "张三", "lead_source": "官网表单"}
    payload.update(overrides)
    return client.post(
        f"/api/v1/projects/{project.id}/leads", json=payload, headers=_auth(user)
    )


def test_visitor_ip_hashed_not_stored_raw(client, db, project_factory, user_factory, member_factory):
    project, ops = _project_and_ops(project_factory, user_factory, member_factory)
    resp = _create_lead(
        client, project, ops, visitor_ip="203.0.113.7", visitor_region="广东/广州"
    )
    assert resp.status_code == 201, resp.text
    lead_id = resp.json()["data"]["id"]

    row = db.scalar(select(Lead).where(Lead.id == uuid.UUID(lead_id)))
    assert row.ip_hash is not None and len(row.ip_hash) == 32
    assert "203.0.113.7" not in row.ip_hash
    assert row.visitor_region == "广东/广州"

    listed = client.get(
        f"/api/v1/projects/{project.id}/leads?page_size=100", headers=_auth(ops)
    )
    assert listed.status_code == 200, listed.text
    item = next(r for r in listed.json()["data"] if r["id"] == lead_id)
    assert item["visitor_hash"] == row.ip_hash[:8]
    assert item["visitor_region"] == "广东/广州"
    # 响应里不得出现原始地址
    assert "203.0.113.7" not in listed.text


def test_same_ip_counts_one_visitor(client, db, project_factory, user_factory, member_factory):
    project, ops = _project_and_ops(project_factory, user_factory, member_factory)
    for _ in range(2):
        assert _create_lead(client, project, ops, visitor_ip="203.0.113.9").status_code == 201
    # 一条没有访客地址的手工线索，不参与去重
    assert _create_lead(client, project, ops).status_code == 201

    report = client.get(
        f"/api/v1/projects/{project.id}/leads/visitor-report", headers=_auth(ops)
    )
    assert report.status_code == 200, report.text
    data = report.json()["data"]
    assert data["total_leads"] == 3
    assert data["leads_with_visitor"] == 2
    assert data["distinct_visitors"] == 1
    assert data["repeat_rate"] == 0.5
    assert data["by_region"][0] == {"label": "未填写", "count": 3}
    assert data["by_source"][0]["label"] == "官网表单"


def test_report_without_any_visitor_hash_is_null(client, db, project_factory, user_factory, member_factory):
    project, ops = _project_and_ops(project_factory, user_factory, member_factory)
    assert _create_lead(client, project, ops).status_code == 201
    data = client.get(
        f"/api/v1/projects/{project.id}/leads/visitor-report", headers=_auth(ops)
    ).json()["data"]
    assert data["distinct_visitors"] == 0
    # 无带哈希线索时不给 0，避免把「无法计算」读成「没有重复」
    assert data["repeat_rate"] is None


def test_messages_unread_flow(client, db, project_factory, user_factory, member_factory):
    project, ops = _project_and_ops(project_factory, user_factory, member_factory)
    lead_id = _create_lead(client, project, ops).json()["data"]["id"]

    visitor = client.post(
        f"/api/v1/projects/{project.id}/leads/{lead_id}/messages",
        json={"body": "  想问一下课程安排  ", "author_role": "visitor"},
        headers=_auth(ops),
    )
    assert visitor.status_code == 201, visitor.text
    visitor_body = visitor.json()["data"]
    assert visitor_body["body"] == "想问一下课程安排"  # 首尾空白被去掉
    assert visitor_body["is_read"] is False

    staff = client.post(
        f"/api/v1/projects/{project.id}/leads/{lead_id}/messages",
        json={"body": "已安排老师联系您", "author_role": "staff"},
        headers=_auth(ops),
    )
    assert staff.status_code == 201, staff.text
    assert staff.json()["data"]["is_read"] is True

    report = client.get(
        f"/api/v1/projects/{project.id}/leads/visitor-report", headers=_auth(ops)
    ).json()["data"]
    assert report["unread_messages"] == 1

    marked = client.patch(
        f"/api/v1/projects/{project.id}/leads/{lead_id}/messages/{visitor_body['id']}",
        headers=_auth(ops),
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["data"]["is_read"] is True

    after = client.get(
        f"/api/v1/projects/{project.id}/leads/visitor-report", headers=_auth(ops)
    ).json()["data"]
    assert after["unread_messages"] == 0

    listed = client.get(
        f"/api/v1/projects/{project.id}/leads/{lead_id}/messages", headers=_auth(ops)
    )
    assert listed.status_code == 200
    assert [m["author_role"] for m in listed.json()["data"]] == ["visitor", "staff"]


def test_messages_are_project_scoped(client, db, project_factory, user_factory, member_factory):
    project_a, ops_a = _project_and_ops(project_factory, user_factory, member_factory)
    project_b, ops_b = _project_and_ops(project_factory, user_factory, member_factory)
    lead_id = _create_lead(client, project_a, ops_a).json()["data"]["id"]

    resp = client.get(
        f"/api/v1/projects/{project_b.id}/leads/{lead_id}/messages", headers=_auth(ops_b)
    )
    assert resp.status_code == 403, resp.text
    assert db.scalar(select(LeadMessage).where(LeadMessage.lead_id == uuid.UUID(lead_id))) is None
