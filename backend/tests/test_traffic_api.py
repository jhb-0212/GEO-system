"""B3 流量：PV / 会话 / 去重访客三个数并列，不做互推。

钉住五条：
1. 空项目返回 0，不返回 null 或 NaN；
2. 同一个 IP 的两次访问：PV=2、会话=2、去重访客=1（三个口径各自算，不做减法）；
3. 机器人事件不进 PV 与访客，单列 bot_events；
4. 导入接口只收 IP 原文、库里存的是哈希，响应里没有 IP；
5. 地区/渠道分组按事件数排序，空值映射成「未填写 / 直接访问」。
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.security import create_access_token
from app.models import TrafficEvent
from app.models.enums import RoleCode
from app.services.lead_visitors import hash_visitor


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _setup(project_factory, user_factory, member_factory, role=RoleCode.EDITOR):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"tr-{suffix}")
    user = user_factory(f"tr-u-{suffix}")
    member_factory(project, user, role)
    return project, user


def _event(db, project, *, ip=None, region=None, channel=None, session=None, bot=False, days_ago=1):
    db.add(
        TrafficEvent(
            project_id=project.id,
            visitor_session_id=session,
            visitor_ip_hash=hash_visitor(ip) if ip else None,
            visitor_region=region,
            landing_url="https://gdccai.com/",
            utm_source=channel,
            is_bot=bot,
            occurred_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
    )


def _summary(client, project, user, days=30) -> dict:
    resp = client.get(
        f"/api/v1/projects/{project.id}/traffic/summary?days={days}", headers=_auth(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_empty_project_counts_zero(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    data = _summary(client, project, user)
    assert data["totals"] == {"pv": 0, "sessions": 0, "visitors": 0, "bot_events": 0}
    assert data["by_region"] == [] and data["by_channel"] == []


def test_same_ip_dedupes_visitors_but_not_sessions(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    _event(db, project, ip="203.0.113.9", session="s1", region="广东", channel="douyin")
    _event(db, project, ip="203.0.113.9", session="s2", region="广东", channel="douyin")
    _event(db, project, ip="198.51.100.4", session="s3", region="北京", channel="search")
    db.commit()

    data = _summary(client, project, user)
    assert data["totals"]["pv"] == 3
    assert data["totals"]["sessions"] == 3
    assert data["totals"]["visitors"] == 2
    # 指标不做减法：没有「新访客 = UV - 回访」这种派生字段
    assert "new_visitors" not in data["totals"]
    assert data["by_region"][0] == {"region": "广东", "events": 2, "visitors": 1}


def test_bots_and_missing_ip_are_not_in_visitors(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    _event(db, project, ip="203.0.113.9", session="s1")
    _event(db, project, bot=True, session="bot-1", ip="203.0.113.9")
    _event(db, project, session="s2")  # 没有 IP 的历史事件
    db.commit()

    data = _summary(client, project, user)
    assert data["totals"]["pv"] == 2
    assert data["totals"]["bot_events"] == 1
    assert data["totals"]["visitors"] == 1
    assert data["by_region"][0]["region"] == "未填写"


def test_import_stores_hash_only(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory, RoleCode.EDITOR)
    payload = {
        "source": "cdn",
        "events": [{
            "visitor_session_id": "s-1",
            "visitor_ip": "203.0.113.77",
            "visitor_region": "广东",
            "landing_url": "https://gdccai.com/",
            "utm_source": "douyin",
            "occurred_at": datetime.now(UTC).isoformat(),
        }],
    }
    resp = client.post(
        f"/api/v1/projects/{project.id}/traffic-events/import", json=payload, headers=_auth(user)
    )
    assert resp.status_code == 200, resp.text
    row = db.query(TrafficEvent).filter(TrafficEvent.project_id == project.id).one()
    assert row.visitor_ip_hash == hash_visitor("203.0.113.77")
    assert row.visitor_ip_hash != "203.0.113.77"
    assert "203.0.113.77" not in resp.text
    assert _summary(client, project, user)["totals"]["visitors"] == 1


def test_window_excludes_old_events(client, db, project_factory, user_factory, member_factory):
    project, user = _setup(project_factory, user_factory, member_factory)
    _event(db, project, ip="203.0.113.9", session="s1", days_ago=40)
    _event(db, project, ip="203.0.113.9", session="s2", days_ago=1)
    db.commit()

    assert _summary(client, project, user, days=30)["totals"]["pv"] == 1
    assert _summary(client, project, user, days=90)["totals"]["pv"] == 2
