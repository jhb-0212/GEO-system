
import json
import logging
import re
from datetime import datetime, timezone

from app.core.request_context import request_id_var


# 识别常见敏感字段

# 识别常见敏感字段，包括带前缀的字段名
SENSITIVE_PATTERN = re.compile(
    r"""(?ix)
    (["']?[\w.-]*(?:password|passwd|pwd|token|secret|api[_-]?key|authorization|credential)[\w.-]*["']?\s*[:=]\s*)
    (?:"[^"]*"|'[^']*'|Bearer\s+[^\s,;&}]+|Basic\s+[^\s,;&}]+|[^\s,;&}]+)
    """
)

# 识别独立出现的 Bearer / Basic 凭据
AUTH_PATTERN = re.compile(
    r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+",
    re.IGNORECASE,
)

# 识别常见 AI API Key 格式
API_KEY_PATTERN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|"
    r"AIza[A-Za-z0-9_-]{20,})\b"
)



def redact_sensitive_data(value: str) -> str:
    """对日志文本中的密码、Token 和 API Key 进行脱敏。"""

    value = SENSITIVE_PATTERN.sub(
        lambda match: match.group(1) + '"[REDACTED]"',
        value,
    )

    value = AUTH_PATTERN.sub("[REDACTED]", value)
    value = API_KEY_PATTERN.sub("[REDACTED]", value)

    return value



class JSONFormatter(logging.Formatter):
    """将日志记录转换为 JSON 格式，并屏蔽敏感信息。"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_data(record.getMessage()),
            "request_id": request_id_var.get(),
        }

        # 附加请求信息
        for key in ("method", "path", "status_code"):
            if hasattr(record, key):
                value = getattr(record, key)

                if isinstance(value, str):
                    value = redact_sensitive_data(value)

                log_data[key] = value

        # 异常堆栈也进行脱敏
        if record.exc_info:
            exception_text = self.formatException(record.exc_info)
            log_data["exception"] = redact_sensitive_data(
                exception_text
            )
        if record.stack_info:
            log_data["stack_info"] = redact_sensitive_data(
                self.formatStack(record.stack_info)
                )

        return json.dumps(log_data, ensure_ascii=False)


def configure_logging() -> None:
    """统一配置应用程序 JSON 日志。"""

    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 避免重复添加处理器
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # 让 Uvicorn 日志也传递给根日志处理器
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True
