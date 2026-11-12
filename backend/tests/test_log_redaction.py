"""日志脱敏：密码、Token、Authorization、API Key 都不能以明文进日志。"""

import logging

from app.core.logging import JsonFormatter, redact


def test_redact_password():
    assert "s3cret" not in redact("password=s3cret")


def test_redact_bearer():
    assert "abc123" not in redact("Authorization: Bearer abc123")


def test_redact_api_key():
    assert "sk-live-0123456789" not in redact("key sk-live-0123456789")


def test_formatter_masks_fields_and_keeps_request_id():
    record = logging.LogRecord(
        "test",
        logging.INFO,
        "f.py",
        1,
        "login ok",
        None,
        None,
        extra={"fields": {"token": "secret123"}},
    )
    rendered = JsonFormatter().format(record)
    assert "secret123" not in rendered
    assert '"request_id"' in rendered
