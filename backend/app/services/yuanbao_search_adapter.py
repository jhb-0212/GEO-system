"""腾讯元宝搜索（Tencent Yuanbao Search / wsa SearchPro）适配器。

边界：
- 元宝搜索 API 返回的是检索结果（title/url/passage/content），不是对话生成答案；
  本适配器把结果归一成可审计的检索摘要文本，并逐条写 citations，不做“模型回答”冒充。
- 调用使用腾讯云 TC3-HMAC-SHA256 签名；SecretId / SecretKey 只从环境变量读取，
  库里只存 credential_ref（SecretId 的变量名），不落明文。
- 4 平台业务基线必须四个入口都真实可调用；本适配器结果不能与 DeepSeek/豆包/文心
  的生成式回答混为一谈，报表中通过 `engine_model=yuanbao-search` 标识。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.core.credentials import read_credential_env
from app.models import MonitoringTask, QuestionVersion
from app.models.enums import FailureCode
from app.services.monitoring_collection import (
    AccessBlockedFailure,
    CollectionFailure,
    RateLimitedFailure,
    TransientCollectionFailure,
)
from app.services.monitoring_extraction import AnswerPayload, CitationInput

DEFAULT_ENDPOINT = "https://wsa.tencentcloudapi.com"
DEFAULT_VERSION = "2025-05-08"
DEFAULT_ACTION = "SearchPro"
DEFAULT_MODEL = "yuanbao-search"
SECRET_KEY_ENV = "YUANBAO_SECRET_KEY"
MAX_PAGES = 10
_TAG_RE = re.compile(r"<[^>]+>")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def build_tc3_headers(
    *,
    secret_id: str,
    secret_key: str,
    action: str,
    version: str,
    endpoint: str,
    body: bytes,
    timestamp: int | None = None,
) -> dict[str, str]:
    """构造腾讯云 TC3 签名头；body 必须与实际发送字节完全一致。"""
    host = urlparse(endpoint).netloc
    if not host:
        raise ValueError(f"非法腾讯云 endpoint: {endpoint!r}")
    ts = int(timestamp if timestamp is not None else datetime.now(timezone.utc).timestamp())
    date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")

    canonical_headers = (
        "content-type:application/json\n"
        f"host:{host}\n"
        f"x-tc-action:{action.lower()}\n"
    )
    signed_headers = "content-type;host;x-tc-action"
    canonical_request = (
        "POST\n"
        "/\n"
        "\n"
        f"{canonical_headers}\n"
        f"{signed_headers}\n"
        f"{_sha256_hex(body)}"
    )
    credential_scope = f"{date}/wsa/tc3_request"
    string_to_sign = (
        "TC3-HMAC-SHA256\n"
        f"{ts}\n"
        f"{credential_scope}\n"
        f"{_sha256_hex(canonical_request.encode('utf-8'))}"
    )
    secret_date = _hmac_sha256(secret_key.encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, "wsa")
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(
        secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    authorization = (
        "TC3-HMAC-SHA256 "
        f"Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )
    return {
        "Authorization": authorization,
        "Content-Type": "application/json",
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Version": version,
        "X-TC-Timestamp": str(ts),
    }


def _clean_text(value: Any) -> str:
    text = _TAG_RE.sub("", str(value or ""))
    return " ".join(text.split())


def _parse_pages(raw_pages: Any) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    if not isinstance(raw_pages, list):
        return pages
    for item in raw_pages:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError:
                item = {"passage": item}
        if not isinstance(item, dict):
            continue
        pages.append(item)
    return pages


def _answer_text(pages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, page in enumerate(pages[:MAX_PAGES], start=1):
        title = _clean_text(page.get("title"))
        passage = _clean_text(page.get("content") or page.get("passage"))
        url = str(page.get("url") or "").strip()
        block = [f"[{index}] {title}" if title else f"[{index}]"]
        if passage:
            block.append(passage)
        if url:
            block.append(url)
        lines.append("\n".join(block))
    return "\n\n".join(lines).strip()


def _citations(pages: list[dict[str, Any]]) -> list[CitationInput]:
    result: list[CitationInput] = []
    seen: set[str] = set()
    for page in pages[:MAX_PAGES]:
        url = str(page.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(CitationInput(url=url))
    return result


class YuanbaoSearchAdapter:
    """把 SearchPro 检索结果归一成监测样本可用的 AnswerPayload。"""

    def __init__(
        self,
        db: Session,
        *,
        secret_id: str,
        secret_key: str,
        endpoint: str = DEFAULT_ENDPOINT,
        version: str = DEFAULT_VERSION,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._db = db
        self.secret_id = secret_id.strip()
        self.secret_key = secret_key.strip()
        self.endpoint = endpoint.rstrip("/") or DEFAULT_ENDPOINT
        self.version = version
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "YuanbaoSearchAdapter":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _question_text(self, task: MonitoringTask) -> str:
        version = self._db.get(QuestionVersion, task.question_version_id)
        if version is None or not version.text.strip():
            raise CollectionFailure(
                "任务关联的问题版本不存在或为空",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )
        return version.text.strip()

    def _raise_response_error(self, error: dict[str, Any]) -> None:
        code = str(error.get("Code") or "").strip()
        message = str(error.get("Message") or "").strip()
        if code == "RequestLimitExceeded":
            raise RateLimitedFailure(f"元宝搜索限流：{message or code}")
        if code in {"UnauthorizedOperation", "AuthFailure", "ResourceNotFound"}:
            raise AccessBlockedFailure(f"元宝搜索不可用：{message or code}")
        if code in {"InternalError", "ResourceUnavailable"}:
            raise TransientCollectionFailure(
                f"元宝搜索服务异常：{message or code}",
                failure_code=FailureCode.OTHER,
            )
        raise CollectionFailure(
            f"元宝搜索失败：{code} {message}".strip(),
            failure_code=FailureCode.OTHER,
            retryable=False,
        )

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        query = self._question_text(task)
        body_payload = {"Query": query, "Cnt": MAX_PAGES}
        body = json.dumps(body_payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        headers = build_tc3_headers(
            secret_id=self.secret_id,
            secret_key=self.secret_key,
            action=DEFAULT_ACTION,
            version=self.version,
            endpoint=self.endpoint,
            body=body,
        )
        try:
            response = self._client.post(
                self.endpoint,
                headers=headers,
                content=body,
            )
        except httpx.TimeoutException as exc:
            raise TransientCollectionFailure(
                f"元宝搜索请求超时: {exc}",
                failure_code=FailureCode.TIMEOUT,
            ) from exc
        except httpx.HTTPError as exc:
            raise AccessBlockedFailure(f"元宝搜索服务不可达: {exc}") from exc

        if response.status_code == 429:
            raise RateLimitedFailure("元宝搜索触发限流（HTTP 429）")
        if response.status_code in (401, 403):
            raise AccessBlockedFailure(f"元宝搜索鉴权失败（HTTP {response.status_code}）")
        if response.status_code >= 500:
            raise TransientCollectionFailure(
                f"元宝搜索服务异常（HTTP {response.status_code}）",
                failure_code=FailureCode.OTHER,
            )
        if response.status_code >= 400:
            raise CollectionFailure(
                f"元宝搜索请求被拒绝（HTTP {response.status_code}）",
                failure_code=FailureCode.OTHER,
                retryable=False,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise TransientCollectionFailure(
                "元宝搜索返回不是合法 JSON",
                failure_code=FailureCode.OTHER,
            ) from exc
        if not isinstance(data, dict):
            raise TransientCollectionFailure(
                "元宝搜索返回结构不是 JSON 对象",
                failure_code=FailureCode.OTHER,
            )

        payload = data.get("Response")
        if not isinstance(payload, dict):
            raise TransientCollectionFailure(
                "元宝搜索返回缺少 Response",
                failure_code=FailureCode.OTHER,
            )
        error = payload.get("Error")
        if isinstance(error, dict):
            self._raise_response_error(error)

        pages = _parse_pages(payload.get("Pages"))
        text = _answer_text(pages)
        return AnswerPayload(
            text=text,
            raw_response={
                "query": payload.get("Query") or query,
                "version": payload.get("Version"),
                "request_id": payload.get("RequestId"),
                "pages": pages,
                "result_count": len(pages),
            },
            engine_model=DEFAULT_MODEL,
            model_version=payload.get("Version"),
            citations=_citations(pages),
        )


def build_yuanbao_adapter(
    db: Session,
    *,
    credential_ref: str | None,
    entry_url: str | None = None,
    timeout_seconds: float = 60.0,
    client: httpx.Client | None = None,
) -> YuanbaoSearchAdapter:
    """从 credential_ref 读 SecretId，并从固定 YUANBAO_SECRET_KEY 读 SecretKey。"""
    if not credential_ref:
        raise AccessBlockedFailure("元宝搜索入口未配置 credential_ref（SecretId 环境变量名）")
    secret_id = read_credential_env(credential_ref)
    secret_key = os.getenv(SECRET_KEY_ENV, "").strip()
    if not secret_id:
        raise AccessBlockedFailure(f"环境变量 {credential_ref} 未配置")
    if not secret_key:
        raise AccessBlockedFailure(f"环境变量 {SECRET_KEY_ENV} 未配置")
    return YuanbaoSearchAdapter(
        db,
        secret_id=secret_id,
        secret_key=secret_key,
        endpoint=entry_url or DEFAULT_ENDPOINT,
        timeout_seconds=timeout_seconds,
        client=client,
    )
