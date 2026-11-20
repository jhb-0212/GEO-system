"""微信公众号官方适配器单测：全部走 MockTransport，不触真实微信接口。"""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.wechat_publisher import (
    WeChatOfficialPublisher,
    WeChatPublisherError,
    build_wechat_digest,
    clear_token_cache,
    render_wechat_html,
)


@pytest.fixture(autouse=True)
def _clear_token_cache():
    clear_token_cache()
    yield
    clear_token_cache()


def _publisher(handler) -> WeChatOfficialPublisher:
    return WeChatOfficialPublisher(
        "wx-app-id",
        "wx-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _ok_token() -> httpx.Response:
    return httpx.Response(200, json={"access_token": "token-1", "expires_in": 7200})


def test_publish_article_success_and_payload_shape():
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content or b"{}")))
        if request.url.path == "/cgi-bin/token":
            assert request.url.params["appid"] == "wx-app-id"
            assert request.url.params["secret"] == "wx-secret"
            return _ok_token()
        if request.url.path == "/cgi-bin/draft/add":
            article = json.loads(request.content)["articles"][0]
            assert article["title"] == "测试标题"
            assert article["content"] == "<p>正文第一段</p>"
            assert article["thumb_media_id"] == "thumb-1"
            return httpx.Response(200, json={"media_id": "media-1", "errcode": 0})
        if request.url.path == "/cgi-bin/freepublish/submit":
            assert json.loads(request.content) == {"media_id": "media-1"}
            return httpx.Response(
                200,
                json={"publish_id": "publish-1", "msg_data_id": "msg-1", "errcode": 0},
            )
        if request.url.path == "/cgi-bin/freepublish/get":
            assert json.loads(request.content) == {"publish_id": "publish-1"}
            return httpx.Response(
                200,
                json={
                    "publish_status": 0,
                    "article_detail": {"article_url": "https://mp.weixin.qq.com/s/abc"},
                    "errcode": 0,
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    result = _publisher(handler).publish_article(
        title="测试标题",
        content_html="<p>正文第一段</p>",
        thumb_media_id="thumb-1",
    )
    assert result.media_id == "media-1"
    assert result.publish_id == "publish-1"
    assert result.article_url == "https://mp.weixin.qq.com/s/abc"
    assert [path for path, _ in calls] == [
        "/cgi-bin/token",
        "/cgi-bin/draft/add",
        "/cgi-bin/freepublish/submit",
        "/cgi-bin/freepublish/get",
    ]


def test_platform_rejection_is_definitive_not_ambiguous():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return _ok_token()
        return httpx.Response(200, json={"errcode": 48001, "errmsg": "api unauthorized"})

    with pytest.raises(WeChatPublisherError) as exc_info:
        _publisher(handler).publish_article(title="标题", content_html="<p>正文</p>")
    assert exc_info.value.code == "wechat_api_unauthorized"
    assert exc_info.value.ambiguous is False
    assert exc_info.value.retryable is False


def test_network_timeout_is_ambiguous_and_not_retried():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return _ok_token()
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(WeChatPublisherError) as exc_info:
        _publisher(handler).publish_article(title="标题", content_html="<p>正文</p>")
    assert exc_info.value.code == "wechat_network_unknown"
    assert exc_info.value.ambiguous is True
    assert exc_info.value.retryable is True


def test_expired_token_refreshes_once_then_continues():
    token_calls = {"count": 0}
    draft_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            token_calls["count"] += 1
            return httpx.Response(
                200,
                json={"access_token": f"token-{token_calls['count']}", "expires_in": 7200},
            )
        if request.url.path == "/cgi-bin/draft/add":
            draft_calls["count"] += 1
            if draft_calls["count"] == 1:
                return httpx.Response(200, json={"errcode": 40001, "errmsg": "invalid credential"})
            return httpx.Response(200, json={"media_id": "media-2", "errcode": 0})
        if request.url.path == "/cgi-bin/freepublish/submit":
            return httpx.Response(200, json={"publish_id": "publish-2", "errcode": 0})
        if request.url.path == "/cgi-bin/freepublish/get":
            return httpx.Response(200, json={"publish_status": 1, "errcode": 0})
        raise AssertionError(f"unexpected path: {request.url.path}")

    result = _publisher(handler).publish_article(title="标题", content_html="<p>正文</p>")
    assert result.publish_id == "publish-2"
    assert token_calls["count"] == 2
    assert draft_calls["count"] == 2


def test_render_html_escapes_and_preserves_blocks():
    rendered = render_wechat_html("# 标题\n\n正文 <script>alert(1)</script>\n\n- 一\n- 二")
    assert "<h2>标题</h2>" in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "<ul>" in rendered and "<li>一</li>" in rendered


def test_digest_strips_markdown_and_limits_length():
    digest = build_wechat_digest("# 标题\n\n**正文** 内容", limit=8)
    assert digest == "标题 正文 内容"[:8]
    assert len(digest) == 8
