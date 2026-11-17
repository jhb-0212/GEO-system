"""发布可见性检测回归：命中只认 URL 精确相等，查询失败不能读成"未收录"。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx

from app.core.security import create_access_token
from app.models import (
    Channel,
    ContentItem,
    ContentVersion,
    Project,
    PublishAccount,
    PublishReceipt,
    PublishTask,
    PublishVisibilityCheck,
)
from app.models.enums import (
    ChannelCategory,
    ChannelStatus,
    ContentKind,
    ContentStatus,
    ProjectStatus,
    RoleCode,
)
from app.services import publish_visibility as pv


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _project(db, code: str) -> Project:
    project = Project(code=code, name="可见性测试", status=ProjectStatus.ACTIVE, timezone="Asia/Shanghai")
    db.add(project)
    db.flush()
    return project


def _receipt(db, project: Project, *, title: str, published_url: str) -> PublishReceipt:
    channel = Channel(
        project_id=project.id,
        code=f"ch-{uuid.uuid4().hex[:6]}",
        name="渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
    )
    db.add(channel)
    db.flush()
    item = ContentItem(project_id=project.id, title=title, kind=ContentKind.MASTER)
    db.add(item)
    db.flush()
    version = ContentVersion(
        project_id=project.id,
        item_id=item.id,
        version_no=1,
        body="正文",
        content_hash=uuid.uuid4().hex,
        status=ContentStatus.DRAFT,
    )
    db.add(version)
    db.flush()
    account = PublishAccount(
        project_id=project.id, channel_id=channel.id, account_name=f"账号-{uuid.uuid4().hex[:6]}"
    )
    db.add(account)
    db.flush()
    task = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"t-{uuid.uuid4().hex[:8]}",
        idempotency_key=f"i-{uuid.uuid4().hex[:8]}",
    )
    db.add(task)
    db.flush()
    receipt = PublishReceipt(
        project_id=project.id,
        task_id=task.id,
        published_url=published_url,
        received_at=datetime.now(timezone.utc),
    )
    db.add(receipt)
    db.flush()
    return receipt


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)


def test_truncate_to_weight_counts_chinese_as_two():
    text = "广州" * 20  # 40 个字，权重 80，必须截断
    assert len(pv.truncate_to_weight(text)) == 36  # 36 字 × 2 = 72
    assert pv.truncate_to_weight("abc") == "abc"


def test_build_query_prefers_title_and_falls_back_to_url():
    assert pv.build_query(" 发布闭环联调稿 ", "https://36kr.com/p/x") == "发布闭环联调稿"
    assert pv.build_query(None, "https://36kr.com/p/geo-live-smoke") == "geo live smoke"


def test_site_of_strips_scheme_and_www():
    assert pv.site_of("https://www.36kr.com/p/a") == "36kr.com"
    assert pv.site_of("http://k.sina.com.cn/article_1.html") == "k.sina.com.cn"


def test_evaluate_matches_only_exact_url():
    url = "https://36kr.com/p/geo-live-smoke"
    refs = [
        {"url": "https://36kr.com/p/another"},
        {"url": "https://36kr.com/p/geo-live-smoke?utm_source=x"},
    ]
    result = pv.evaluate(refs, url)
    assert result.matched is True
    assert result.position == 2
    assert pv.evaluate([{"url": "https://36kr.com/"}], url).matched is False


def test_evaluate_never_reports_match_on_error():
    result = pv.evaluate([{"url": "https://36kr.com/p/geo-live-smoke"}], "https://36kr.com/p/geo-live-smoke", error_code="http_429")
    assert result.matched is False
    assert result.error_code == "http_429"


def test_check_receipt_records_hit(db):
    project = _project(db, f"vis-hit-{uuid.uuid4().hex[:6]}")
    receipt = _receipt(db, project, title="发布闭环联调稿", published_url="https://36kr.com/p/geo-live-smoke")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read().decode())
        return httpx.Response(
            200,
            json={
                "request_id": "req-1",
                "references": [
                    {"id": 1, "url": "https://36kr.com/p/geo-live-smoke", "title": "发布闭环联调稿"},
                ],
            },
        )

    with _mock_client(handler) as client:
        result = pv.check_receipt(db, receipt, client=client, api_key="k")

    assert result.matched is True and result.position == 1
    assert seen["body"]["search_filter"] == {"match": {"site": ["36kr.com"]}}
    assert seen["body"]["messages"][0]["content"] == "发布闭环联调稿"
    row = db.query(PublishVisibilityCheck).filter_by(receipt_id=receipt.id).one()
    assert row.matched is True and row.position == 1 and row.error_code is None
    assert row.site == "36kr.com" and row.request_id == "req-1"


def test_check_receipt_records_quota_error_not_unmatched(db):
    project = _project(db, f"vis-429-{uuid.uuid4().hex[:6]}")
    receipt = _receipt(db, project, title="配额测试", published_url="https://36kr.com/p/quota")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"code": "QUOTA_USER_DAILY_FREE", "message": "quota exceeded"})

    with _mock_client(handler) as client:
        result = pv.check_receipt(db, receipt, client=client, api_key="k")

    assert result.matched is False
    assert result.error_code == "QUOTA_USER_DAILY_FREE"
    row = db.query(PublishVisibilityCheck).filter_by(receipt_id=receipt.id).one()
    assert row.error_code == "QUOTA_USER_DAILY_FREE"


def test_check_receipt_reads_body_code_on_http_200(db):
    project = _project(db, f"vis-200err-{uuid.uuid4().hex[:6]}")
    receipt = _receipt(db, project, title="参数错误", published_url="https://36kr.com/p/bad")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "InvalidArgument", "message": "bad param"})

    with _mock_client(handler) as client:
        result = pv.check_receipt(db, receipt, client=client, api_key="k")

    assert result.error_code == "InvalidArgument"
    assert result.matched is False


def test_latest_checks_keeps_newest_per_receipt(db):
    project = _project(db, f"vis-latest-{uuid.uuid4().hex[:6]}")
    receipt = _receipt(db, project, title="最新一条", published_url="https://36kr.com/p/latest")
    db.add(
        PublishVisibilityCheck(
            project_id=project.id,
            receipt_id=receipt.id,
            checked_at=datetime(2026, 11, 16, tzinfo=timezone.utc),
            matched=False,
            query="旧",
            result_count=0,
        )
    )
    db.add(
        PublishVisibilityCheck(
            project_id=project.id,
            receipt_id=receipt.id,
            checked_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
            matched=True,
            position=3,
            matched_url="https://36kr.com/p/latest",
            query="新",
            result_count=4,
        )
    )
    db.flush()

    rows = pv.latest_checks(db, project.id)
    assert len(rows) == 1
    assert rows[0]["matched"] is True and rows[0]["query"] == "新"


class _FakeSearchClient:
    """替身客户端：返回一条命中当前回执的 references。"""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def post(self, url, **kwargs):
        return httpx.Response(
            200,
            json={"request_id": "req-api", "references": [{"id": 1, "url": "https://36kr.com/p/api"}]},
        )


def test_check_endpoint_requires_execute_permission(client, project_factory, user_factory, member_factory):
    project = project_factory(f"vis-api-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"vis-viewer-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)

    response = client.post(
        f"/api/v1/projects/{project.id}/stats/publish-visibility/check",
        json={"limit": 5},
        headers=_auth(viewer),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_permission"


def test_check_endpoint_runs_and_records(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    project = project_factory(f"vis-api-ok-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"vis-editor-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    receipt = _receipt(db, project, title="接口触发", published_url="https://36kr.com/p/api")

    monkeypatch.setattr("app.api.stats.httpx.Client", _FakeSearchClient)
    monkeypatch.setattr("app.api.stats.read_credential_env", lambda _ref: "test-key")

    response = client.post(
        f"/api/v1/projects/{project.id}/stats/publish-visibility/check",
        json={"limit": 5},
        headers=_auth(editor),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"checked": 1, "matched": 1, "unmatched": 0, "failed": 0}

    row = db.query(PublishVisibilityCheck).filter_by(receipt_id=receipt.id).one()
    assert row.matched is True and row.position == 1


def test_check_endpoint_throttles_repeat_calls(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    project = project_factory(f"vis-api-429-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"vis-editor2-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    _receipt(db, project, title="节流", published_url="https://36kr.com/p/api")

    monkeypatch.setattr("app.api.stats.httpx.Client", _FakeSearchClient)
    monkeypatch.setattr("app.api.stats.read_credential_env", lambda _ref: "test-key")

    first = client.post(
        f"/api/v1/projects/{project.id}/stats/publish-visibility/check",
        json={"limit": 1},
        headers=_auth(editor),
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/projects/{project.id}/stats/publish-visibility/check",
        json={"limit": 1},
        headers=_auth(editor),
    )
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "too_many_requests"


def test_check_endpoint_reports_missing_credential(
    client, project_factory, user_factory, member_factory, monkeypatch
):
    project = project_factory(f"vis-api-nokey-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"vis-editor3-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)

    monkeypatch.setattr("app.api.stats.read_credential_env", lambda _ref: "")

    response = client.post(
        f"/api/v1/projects/{project.id}/stats/publish-visibility/check",
        json={"limit": 5},
        headers=_auth(editor),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "credential_missing"
