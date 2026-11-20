"""微信公众号官方发布适配器。

边界：
- 只做公众号图文：access_token → draft/add → freepublish/submit → freepublish/get；
- AppID 走配置，Secret 只从服务端 `credential_ref` 读取，不落库、不回显；
- 明确拒绝（errcode/4xx）落 failed；网络超时、5xx、响应不可解析落 unknown，
  因为请求可能已经到达微信，禁止自动重试。

微信接口文档口径：
- token: GET /cgi-bin/token?grant_type=client_credential&appid=&secret=
- 草稿: POST /cgi-bin/draft/add?access_token=
- 发布: POST /cgi-bin/freepublish/submit?access_token=
- 查询: POST /cgi-bin/freepublish/get?access_token=
"""

from __future__ import annotations

import html
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.weixin.qq.com"
TOKEN_INVALID_ERRCODES = frozenset({40001, 40014, 42001})
RATE_LIMIT_ERRCODES = frozenset({45009, 45011})
PUBLISH_FAILED_STATUS = frozenset({2, 3, 4})
PUBLISH_DELETED_STATUS = frozenset({5, 6})

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_LOCK = threading.Lock()


class WeChatPublisherError(RuntimeError):
    """微信发布失败：`ambiguous=True` 表示外部请求可能已发出，必须落 unknown。"""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        errcode: int | None = None,
        retryable: bool = False,
        ambiguous: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.errcode = errcode
        self.retryable = retryable
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class WeChatPublishResult:
    media_id: str
    publish_id: str | None
    article_url: str | None
    raw: dict[str, Any] = field(default_factory=dict)
    status_note: str | None = None


def clear_token_cache(app_id: str | None = None) -> None:
    """清空模块级 token 缓存；测试与密钥轮换时使用。"""
    with _TOKEN_LOCK:
        if app_id is None:
            _TOKEN_CACHE.clear()
        else:
            _TOKEN_CACHE.pop(app_id.strip(), None)


def _cache_token(app_id: str, token: str, expires_in: int) -> None:
    # 提前 60 秒失效，避免边界时刻拿到刚过期的 token。
    expires_at = time.monotonic() + max(60, int(expires_in) - 60)
    with _TOKEN_LOCK:
        _TOKEN_CACHE[app_id] = (token, expires_at)


def _read_cached_token(app_id: str) -> str | None:
    with _TOKEN_LOCK:
        item = _TOKEN_CACHE.get(app_id)
        if item is None:
            return None
        token, expires_at = item
        if expires_at <= time.monotonic():
            _TOKEN_CACHE.pop(app_id, None)
            return None
        return token


def _error_message(errcode: int, errmsg: str | None) -> str:
    suffix = f": {errmsg.strip()}" if errmsg and errmsg.strip() else ""
    return f"微信接口返回错误 {errcode}{suffix}"


def _error_from_errcode(errcode: int, errmsg: str | None) -> WeChatPublisherError:
    message = _error_message(errcode, errmsg)
    if errcode in TOKEN_INVALID_ERRCODES:
        return WeChatPublisherError(message, code="wechat_token_invalid", errcode=errcode, retryable=True)
    if errcode in RATE_LIMIT_ERRCODES:
        return WeChatPublisherError(message, code="wechat_rate_limited", errcode=errcode, retryable=True)
    if errcode == 40164:
        return WeChatPublisherError(message, code="wechat_ip_not_whitelisted", errcode=errcode)
    if errcode in {40013, 40125}:
        return WeChatPublisherError(message, code="wechat_invalid_credentials", errcode=errcode)
    if errcode == 48001:
        return WeChatPublisherError(message, code="wechat_api_unauthorized", errcode=errcode)
    if errcode == 40007:
        return WeChatPublisherError(message, code="wechat_invalid_media_id", errcode=errcode)
    return WeChatPublisherError(message, code=f"wechat_api_{errcode}", errcode=errcode)


class WeChatOfficialPublisher:
    """微信公众号官方 API 客户端；注入 `http_client` 便于测试，不碰真实网络。"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._app_id = (app_id or "").strip()
        self._app_secret = (app_secret or "").strip()
        if not self._app_id or not self._app_secret:
            raise WeChatPublisherError(
                "微信公众号 AppID/Secret 未配置",
                code="wechat_mp_not_configured",
            )
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "WeChatOfficialPublisher":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = self._client.request(method, url, params=params, json=json_body)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise WeChatPublisherError(
                "微信接口网络超时/不可达，结果未知",
                code="wechat_network_unknown",
                retryable=True,
                ambiguous=True,
            ) from exc
        if response.status_code >= 500:
            raise WeChatPublisherError(
                f"微信接口 HTTP {response.status_code}，结果未知",
                code="wechat_http_unknown",
                retryable=True,
                ambiguous=True,
            )
        if response.status_code >= 400:
            # 微信正常错误是 200 + errcode；4xx 多是网关/白名单层拒绝，按明确失败处理。
            try:
                data = response.json()
            except ValueError:
                data = {}
            errcode = int(data.get("errcode") or 0) if isinstance(data, dict) else 0
            if errcode:
                raise _error_from_errcode(errcode, data.get("errmsg"))
            raise WeChatPublisherError(
                f"微信接口 HTTP {response.status_code}",
                code=f"wechat_http_{response.status_code}",
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise WeChatPublisherError(
                f"微信接口返回非 JSON（HTTP {response.status_code}）",
                code="wechat_bad_response",
                ambiguous=True,
            ) from exc
        if not isinstance(data, dict):
            raise WeChatPublisherError(
                "微信接口返回结构不是对象",
                code="wechat_bad_response",
                ambiguous=True,
            )
        errcode = int(data.get("errcode") or 0)
        if errcode:
            raise _error_from_errcode(errcode, data.get("errmsg"))
        return data

    def get_access_token(self, *, force: bool = False) -> str:
        if not force:
            cached = _read_cached_token(self._app_id)
            if cached:
                return cached
        data = self._request_json(
            "GET",
            "/cgi-bin/token",
            params={
                "grant_type": "client_credential",
                "appid": self._app_id,
                "secret": self._app_secret,
            },
        )
        token = str(data.get("access_token") or "").strip()
        if not token:
            raise WeChatPublisherError(
                "微信 token 响应缺少 access_token",
                code="wechat_token_missing",
                ambiguous=True,
            )
        _cache_token(self._app_id, token, int(data.get("expires_in") or 7200))
        return token

    def _call_with_token(
        self,
        path: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        for index in range(2):
            token = self.get_access_token(force=index > 0)
            try:
                return self._request_json(
                    "POST",
                    path,
                    params={"access_token": token},
                    json_body=body,
                )
            except WeChatPublisherError as exc:
                if index == 0 and exc.errcode in TOKEN_INVALID_ERRCODES:
                    clear_token_cache(self._app_id)
                    continue
                raise
        raise WeChatPublisherError("微信 token 重试失败", code="wechat_token_retry_failed")

    def add_draft(
        self,
        *,
        title: str,
        content_html: str,
        author: str = "",
        digest: str = "",
        content_source_url: str = "",
        thumb_media_id: str = "",
    ) -> str:
        article: dict[str, Any] = {
            "title": (title or "").strip()[:64],
            "author": (author or "").strip()[:16],
            "digest": (digest or "").strip()[:120],
            "content": content_html,
            "content_source_url": (content_source_url or "").strip(),
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        }
        if thumb_media_id.strip():
            article["thumb_media_id"] = thumb_media_id.strip()
        data = self._call_with_token("/cgi-bin/draft/add", {"articles": [article]})
        media_id = str(data.get("media_id") or "").strip()
        if not media_id:
            raise WeChatPublisherError(
                "微信草稿响应缺少 media_id",
                code="wechat_draft_missing_media_id",
                ambiguous=True,
            )
        return media_id

    def submit_publish(self, media_id: str) -> str:
        data = self._call_with_token(
            "/cgi-bin/freepublish/submit",
            {"media_id": media_id},
        )
        publish_id = str(data.get("publish_id") or "").strip()
        if not publish_id:
            raise WeChatPublisherError(
                "微信发布响应缺少 publish_id",
                code="wechat_publish_missing_id",
                ambiguous=True,
            )
        return publish_id

    def get_publish_status(self, publish_id: str) -> dict[str, Any]:
        return self._call_with_token(
            "/cgi-bin/freepublish/get",
            {"publish_id": publish_id},
        )

    def publish_article(
        self,
        *,
        title: str,
        content_html: str,
        author: str = "",
        digest: str = "",
        content_source_url: str = "",
        thumb_media_id: str = "",
    ) -> WeChatPublishResult:
        """草稿 + 发布 + 一次状态查询；不轮询，查不到 URL 时由运营后续补回执。"""
        media_id = self.add_draft(
            title=title,
            content_html=content_html,
            author=author,
            digest=digest,
            content_source_url=content_source_url,
            thumb_media_id=thumb_media_id,
        )
        publish_id = self.submit_publish(media_id)

        article_url: str | None = None
        status_note: str | None = None
        try:
            detail = self.get_publish_status(publish_id)
        except WeChatPublisherError as exc:
            # 发布已提交，状态查询失败不改变“已提交”的事实；只记备注。
            status_note = exc.code
        else:
            publish_status = int(detail.get("publish_status") or 1)
            article_detail = detail.get("article_detail") or {}
            if isinstance(article_detail, dict):
                url = str(article_detail.get("article_url") or "").strip()
                if url:
                    article_url = url
            if publish_status in PUBLISH_FAILED_STATUS:
                raise WeChatPublisherError(
                    f"微信发布状态={publish_status}，平台未通过",
                    code=f"wechat_publish_status_{publish_status}",
                )
            if publish_status in PUBLISH_DELETED_STATUS:
                raise WeChatPublisherError(
                    f"微信发布状态={publish_status}，文章已删除",
                    code=f"wechat_publish_status_{publish_status}",
                )
        return WeChatPublishResult(
            media_id=media_id,
            publish_id=publish_id,
            article_url=article_url,
            raw={"publish_id": publish_id, "media_id": media_id},
            status_note=status_note,
        )


def render_wechat_html(body: str) -> str:
    """把纯文本/Markdown 轻量转成公众号可用的 HTML，所有正文先转义。"""
    source = (body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not source:
        raise WeChatPublisherError("正文为空，不能生成公众号草稿", code="wechat_empty_body")

    blocks: list[str] = []
    list_open = False

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            blocks.append("</ul>")
            list_open = False

    for raw_line in source.split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            close_list()
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if heading:
            close_list()
            level = min(len(heading.group(1)) + 1, 4)
            blocks.append(f"<h{level}>{html.escape(heading.group(2).strip())}</h{level}>")
            continue
        bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        if bullet:
            if not list_open:
                blocks.append("<ul>")
                list_open = True
            blocks.append(f"<li>{html.escape(bullet.group(1).strip())}</li>")
            continue
        quote = re.match(r"^\s*>\s?(.*)$", line)
        if quote:
            close_list()
            blocks.append(f"<blockquote>{html.escape(quote.group(1).strip())}</blockquote>")
            continue
        close_list()
        blocks.append(f"<p>{html.escape(line.strip())}</p>")
    close_list()
    return "\n".join(blocks)


def build_wechat_digest(body: str, limit: int = 120) -> str:
    """摘要：去掉 Markdown 控制符，压缩空白，截断到公众号 digest 上限。"""
    text = re.sub(r"[#>*_`~-]+", " ", body or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]
