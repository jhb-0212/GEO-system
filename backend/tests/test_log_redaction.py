"""日志脱敏：密码、Token、Authorization、API Key 都不能以明文进日志。

注意：logging.LogRecord 没有 extra 形参。直接构造时写 extra={...} 会被塞进
**kwargs，record.fields 并不存在 —— 那样根本测不到 fields 脱敏（假阳性）。
这里显式给 record 挂 fields，等价于 logger.info(..., extra={"fields": ...})
经 Logger.makeRecord 处理后的真实状态；末尾另有一条走真实 logger 链路的用例。
"""

import io
import json
import logging

import pytest

from app.core.logging import JsonFormatter, redact, redact_value


def _record(**fields) -> logging.LogRecord:
    record = logging.LogRecord(
        "test", logging.INFO, "f.py", 1, "login ok", None, None
    )
    if fields:
        record.fields = fields
    return record


def _render(record: logging.LogRecord) -> str:
    return JsonFormatter().format(record)


# ---------- 自由文本 ----------


def test_redact_password():
    assert "s3cret" not in redact("password=s3cret")


def test_redact_bearer():
    assert "abc123" not in redact("Authorization: Bearer abc123")


def test_redact_api_key():
    assert "sk-live-0123456789" not in redact("key sk-live-0123456789")


def test_redact_keeps_auth_scheme():
    assert redact("Bearer abc123") == "Bearer [REDACTED]"


# ---------- 结构化 fields：核心是按「字段名」判断 ----------


def test_formatter_masks_fields_by_key():
    rendered = _render(_record(token="secret123", password="p@ss"))
    assert "secret123" not in rendered
    assert "p@ss" not in rendered
    assert "[REDACTED]" in rendered


def test_formatter_masks_nested_fields():
    rendered = _render(_record(payload={"password": "deep-secret", "count": 3}))
    assert "deep-secret" not in rendered
    assert json.loads(rendered)["payload"]["count"] == 3


def test_formatter_masks_fields_in_list():
    rendered = _render(_record(items=[{"password": "list-secret"}]))
    assert "list-secret" not in rendered


def test_formatter_keeps_non_sensitive_fields():
    data = json.loads(_render(_record(note="plain ok", count=7)))
    assert data["note"] == "plain ok"
    assert data["count"] == 7


def test_formatter_preserves_reserved_keys():
    rendered = _render(
        _record(request_id="hacked", message="hacked", level="hacked")
    )
    data = json.loads(rendered)
    assert data["request_id"] != "hacked"
    assert data["message"] == "login ok"
    assert data["level"] == "INFO"
    assert '"request_id"' in rendered


def test_formatter_masks_sensitive_key_with_non_string_value():
    rendered = _render(_record(token=123456))
    assert "123456" not in rendered
    assert json.loads(rendered)["token"] == "[REDACTED]"


# ---------- 字段名敏感清单：参数化锁住，防止复合词再漏 ----------

SENSITIVE_KEY_CASES = [
    "password", "passwd", "pwd", "token", "secret",
    "apikey", "accesskey", "privatekey", "clientsecret", "refreshtoken",
    "accesstoken", "idtoken", "authtoken", "sessiontoken", "apitoken",
    "secretkey", "apisecret", "bearertoken", "accesssecret", "sessionid",
    "authorization", "credential", "cookie", "setcookie", "signature",
    # 分隔符与大小写变体：归一化后应命中
    "access_token", "access-token", "access.token", "ACCESS_TOKEN",
]

NON_SENSITIVE_KEY_CASES = [
    "tokenizer", "secretary", "token_count", "keyword", "keyword_id",
    "items", "note", "client_id", "username",
]


@pytest.mark.parametrize("key", SENSITIVE_KEY_CASES)
def test_redact_sensitive_key_by_name(key):
    assert redact_value(key, "abc123") == "[REDACTED]"


@pytest.mark.parametrize("key", NON_SENSITIVE_KEY_CASES)
def test_keep_non_sensitive_key(key):
    assert redact_value(key, "abc123") == "abc123"


def test_nested_access_token_and_password_are_masked():
    rendered = _render(
        _record(
            access_token="abc123",
            note="ok",
            nested={"password": "p"},
        )
    )
    data = json.loads(rendered)
    assert "abc123" not in rendered
    assert data["access_token"] == "[REDACTED]"
    assert data["note"] == "ok"
    assert data["nested"]["password"] == "[REDACTED]"


# ---------- 真实 logger 链路 ----------


def test_real_logger_extra_fields_are_masked():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.redaction.real")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info("login ok", extra={"fields": {"token": "secret123"}})

    rendered = stream.getvalue()
    assert "secret123" not in rendered
    assert "[REDACTED]" in rendered
