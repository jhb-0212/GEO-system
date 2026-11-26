"""C2-2：待办接口（HTTP 层）的多时区契约。

C2-1 验证到 service（`todo_snapshot`）；本文件走真实 HTTP：
鉴权依赖、响应 Envelope、`window` 字段、废弃参数被忽略、`range=all` 的空窗口。

默认跳过；`GEO_C2_DST_MATRIX=1` 打开（与 C2-1 同一个开关，CI 同一步骤执行）。
期望窗口仍取硬编码 UTC 值，不用被测实现自己算。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models import Fact
from app.models.enums import FactStatus, FactType, RoleCode
from app.services import time_windows

RUN_MATRIX = __import__("os").environ.get("GEO_C2_DST_MATRIX") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_MATRIX,
    reason="C2 真实数据库矩阵；设置 GEO_C2_DST_MATRIX=1 后运行",
)

# (时区, 本地日) -> (window.start, window.end, 用于冻结的瞬时 UTC)
API_CASES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("UTC", "2026-11-26"): ("2026-11-26T00:00:00+00:00", "2026-11-27T00:00:00+00:00", "2026-11-26T12:00:00+00:00"),
    ("Asia/Shanghai", "2026-11-26"): ("2026-11-25T16:00:00+00:00", "2026-11-26T16:00:00+00:00", "2026-11-26T04:00:00+00:00"),
    ("Asia/Tokyo", "2026-11-26"): ("2026-11-25T15:00:00+00:00", "2026-11-26T15:00:00+00:00", "2026-11-26T03:00:00+00:00"),
    ("Europe/Berlin", "2026-11-26"): ("2026-11-25T23:00:00+00:00", "2026-11-26T23:00:00+00:00", "2026-11-26T11:00:00+00:00"),
    ("America/New_York", "2026-11-26"): ("2026-11-26T05:00:00+00:00", "2026-11-27T05:00:00+00:00", "2026-11-26T17:00:00+00:00"),
    # DST 开始 / 结束
    ("America/New_York", "2026-03-08"): ("2026-03-08T05:00:00+00:00", "2026-03-09T04:00:00+00:00", "2026-03-08T16:00:00+00:00"),
    ("America/New_York", "2026-11-01"): ("2026-11-01T04:00:00+00:00", "2026-11-02T05:00:00+00:00", "2026-11-01T16:00:00+00:00"),
}


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _freeze(monkeypatch, instant: datetime) -> None:
    """冻结“当前时刻”：路由与 service 都从 `time_windows._normalize_now` 取 now。"""
    monkeypatch.setattr(time_windows, "_normalize_now", lambda now=None: instant.astimezone(UTC))


def _setup(db, project_factory, user_factory, member_factory, zone: str):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"c2api-{suffix}")
    project.timezone = zone
    db.flush()
    editor = user_factory(f"c2api-user-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    return project, _auth(editor)


def _add_fact(db, project, key: str, at: datetime) -> Fact:
    fact = Fact(
        project_id=project.id,
        fact_type=FactType.BASE_ADDRESS,
        fact_key=f"{key}-{uuid.uuid4().hex[:8]}",
        fact_value="C2 API 边界样本",
        approval_status=FactStatus.DRAFT,
        source_url="https://example.com/c2-api",
        entered_todo_at=at,
    )
    db.add(fact)
    db.flush()
    return fact


def _facts_group(payload: dict) -> dict:
    return next(group for group in payload["groups"] if group["key"] == "facts")


@pytest.mark.parametrize(("zone", "local_day"), sorted(API_CASES))
def test_api_today_window_matches_hardcoded(
    client, db, monkeypatch, project_factory, user_factory, member_factory, zone: str, local_day: str
) -> None:
    expected_start, expected_end, freeze_at = API_CASES[(zone, local_day)]
    _freeze(monkeypatch, _dt(freeze_at))
    project, headers = _setup(db, project_factory, user_factory, member_factory, zone)

    response = client.get(
        f"/api/v1/projects/{project.id}/workbench/todos?range=today", headers=headers
    )
    assert response.status_code == 200
    payload = response.json()["data"]

    assert payload["business_timezone"] == zone
    assert payload["window"] == {"start": expected_start, "end": expected_end}
    assert payload["generated_at"] == _dt(freeze_at).isoformat()
    assert payload["range"] == "today"


@pytest.mark.parametrize(("zone", "local_day"), [("America/New_York", "2026-03-08"), ("America/New_York", "2026-11-01")])
def test_api_dst_days_are_23_and_25_hours(
    client, db, monkeypatch, project_factory, user_factory, member_factory, zone: str, local_day: str
) -> None:
    expected_start, expected_end, freeze_at = API_CASES[(zone, local_day)]
    _freeze(monkeypatch, _dt(freeze_at))
    project, headers = _setup(db, project_factory, user_factory, member_factory, zone)

    payload = client.get(
        f"/api/v1/projects/{project.id}/workbench/todos?range=today", headers=headers
    ).json()["data"]

    start, end = _dt(payload["window"]["start"]), _dt(payload["window"]["end"])
    hours = (end - start).total_seconds() / 3600
    assert hours == (23 if local_day == "2026-03-08" else 25)


def test_api_ignores_deprecated_offset(
    client, db, monkeypatch, project_factory, user_factory, member_factory
) -> None:
    """旧偏移参数只能影响遥测，绝不允许改变 window。"""
    zone, local_day = "America/New_York", "2026-11-26"
    expected_start, expected_end, freeze_at = API_CASES[(zone, local_day)]
    _freeze(monkeypatch, _dt(freeze_at))
    project, headers = _setup(db, project_factory, user_factory, member_factory, zone)

    windows = []
    for offset in (480, 0, -300, 330):
        payload = client.get(
            f"/api/v1/projects/{project.id}/workbench/todos?range=today&tz_offset_minutes={offset}",
            headers=headers,
        ).json()["data"]
        windows.append(payload["window"])

    assert all(w == {"start": expected_start, "end": expected_end} for w in windows)


def test_api_range_all_has_no_window(
    client, db, monkeypatch, project_factory, user_factory, member_factory
) -> None:
    _freeze(monkeypatch, _dt("2026-11-26T12:00:00+00:00"))
    project, headers = _setup(db, project_factory, user_factory, member_factory, "UTC")

    payload = client.get(
        f"/api/v1/projects/{project.id}/workbench/todos?range=all", headers=headers
    ).json()["data"]

    assert payload["window"] is None
    assert payload["business_timezone"] == "UTC"


def test_api_half_open_counts_against_real_db(
    client, db, monkeypatch, project_factory, user_factory, member_factory
) -> None:
    zone, local_day = "Asia/Shanghai", "2026-11-26"
    expected_start, expected_end, freeze_at = API_CASES[(zone, local_day)]
    start, end = _dt(expected_start), _dt(expected_end)
    _freeze(monkeypatch, _dt(freeze_at))
    project, headers = _setup(db, project_factory, user_factory, member_factory, zone)

    _add_fact(db, project, "before", start - timedelta(seconds=1))
    _add_fact(db, project, "at-start", start)
    _add_fact(db, project, "before-end", end - timedelta(seconds=1))
    _add_fact(db, project, "at-end", end)

    payload = client.get(
        f"/api/v1/projects/{project.id}/workbench/todos?range=today", headers=headers
    ).json()["data"]

    group = _facts_group(payload)
    assert group["counts"]["today"] == 2
    assert sorted(datetime.fromisoformat(item["at"]) for item in group["items"]) == [start, end - timedelta(seconds=1)]
    assert payload["counts"]["today"] == 2


def test_api_same_instant_different_zone_windows(
    client, db, monkeypatch, project_factory, user_factory, member_factory
) -> None:
    """同一瞬时 + 同一“现在”：上海已过日界（不计入），UTC 仍在当日（计入）。"""
    instant = _dt("2026-11-26T16:30:00+00:00")   # 上海 11-27 00:30 / UTC 11-26 16:30
    now_instant = _dt("2026-11-26T15:00:00+00:00")  # 上海 11-26 23:00 / UTC 11-26 15:00
    _freeze(monkeypatch, now_instant)

    shanghai, headers_sh = _setup(db, project_factory, user_factory, member_factory, "Asia/Shanghai")
    utc_project, headers_utc = _setup(db, project_factory, user_factory, member_factory, "UTC")
    _add_fact(db, shanghai, "same", instant)
    _add_fact(db, utc_project, "same", instant)

    payload_sh = client.get(
        f"/api/v1/projects/{shanghai.id}/workbench/todos?range=today", headers=headers_sh
    ).json()["data"]
    payload_utc = client.get(
        f"/api/v1/projects/{utc_project.id}/workbench/todos?range=today", headers=headers_utc
    ).json()["data"]

    assert payload_sh["window"] == {"start": "2026-11-25T16:00:00+00:00", "end": "2026-11-26T16:00:00+00:00"}
    assert payload_utc["window"] == {"start": "2026-11-26T00:00:00+00:00", "end": "2026-11-27T00:00:00+00:00"}

    assert _facts_group(payload_sh)["counts"]["today"] == 0, "上海已跨日界，该瞬时不应计入当日"
    assert _facts_group(payload_utc)["counts"]["today"] == 1, "UTC 同一瞬时仍在当日"
