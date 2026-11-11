
from contextvars import ContextVar

# 保存当前请求的唯一 ID，供日志和其他模块读取
request_id_var: ContextVar[str] = ContextVar(
    "request_id",
    default="-",
)
