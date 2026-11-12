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
AUTH_PATTERN = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
API_KEY_PATTERN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{20,})\b")

# 结构化字段（extra={"fields": {...}}）按「字段名」判断，而不是只看值里的文本。
# 归一化后精确匹配（小写 + 去掉 - _ .），不做子串/词根匹配，避免误伤
# keyword / token_count / tokenizer 这类普通业务字段。
SENSITIVE_KEYS = frozenset({
    "password", "passwd", "pwd", "token", "secret",
    "apikey", "accesskey", "privatekey", "clientsecret", "refreshtoken",
    "accesstoken", "idtoken", "authtoken", "sessiontoken", "apitoken",
    "secretkey", "apisecret", "bearertoken", "accesssecret", "sessionid",
    "authorization", "credential", "cookie", "setcookie", "signature",
})
# JSON 日志自身的固定字段，不允许被 fields 覆盖。
RESERVED_KEYS = frozenset({
    "ts", "level", "logger", "message", "request_id", "exception",
})


def redact(text: str) -> str:
    """把自由文本里的密码、Token、Authorization、AI API Key 打码为 [REDACTED]。"""
    text = SENSITIVE_PATTERN.sub(lambda m: m.group(1) + '"[REDACTED]"', text)
    # 保留 Bearer / Basic 字样，方便排查「是哪种认证失败」。
    text = AUTH_PATTERN.sub(lambda m: m.group(1) + " [REDACTED]", text)
    return API_KEY_PATTERN.sub("[REDACTED]", text)


def is_sensitive_key(key: str) -> bool:
    """字段名是否敏感；忽略大小写与 - _ . 分隔符。"""
    return re.sub(r"[-_.]", "", str(key)).lower() in SENSITIVE_KEYS


def redact_value(key: str, value: object) -> object:
    """先按字段名判断，再按值内容脱敏；递归处理 dict / list 嵌套。"""
    if is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(str(key), v) for v in value]
    if isinstance(value, str):
        return redact(value)
    return value


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
                if key in RESERVED_KEYS:
                    continue
                payload[key] = redact_value(str(key), value)
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
