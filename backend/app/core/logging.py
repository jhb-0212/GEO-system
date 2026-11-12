"""统一 JSON 日志：所有服务输出一行一个 JSON，便于按 request_id / level 检索。

字段：ts、level、logger、message、request_id，以及调用方通过 extra={"fields": {...}} 附加的字段。
不引入外部采集组件；生产侧靠容器 json-file 轮转与 stdout 收集。
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import datetime

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# ---------- 敏感信息脱敏 ----------
SENSITIVE_PATTERN = re.compile(
    r"""(?ix)
    (["']?[\w.-]*(?:password|passwd|pwd|token|secret|api[_-]?key|authorization|credential)[\w.-]*["']?\s*[:=]\s*)
    (?:"[^"]*"|'[^']*'|Bearer\s+[^\s,;&}]+|Basic\s+[^\s,;&}]+|[^\s,;&}]+)
    """
)
AUTH_PATTERN = re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
API_KEY_PATTERN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{20,})\b")


def redact(text: str) -> str:
    """把密码、Token、Authorization、AI API Key 打码为 [REDACTED]。"""
    text = SENSITIVE_PATTERN.sub(lambda m: m.group(1) + '"[REDACTED]"', text)
    text = AUTH_PATTERN.sub("[REDACTED]", text)
    return API_KEY_PATTERN.sub("[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": request_id_var.get(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for key, value in fields.items():
                payload[key] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str | None = None) -> None:
    """把 root 与 uvicorn 的 logger 统一到同一个 JSON handler，避免两套格式。"""
    from app.core.config import settings

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel((level or settings.log_level).upper())

    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel((level or settings.log_level).upper())
