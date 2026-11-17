"""请求来源 IP 与可信代理口径。

所有「按 IP 分桶」的规则（登录限流、公开接口限流、后续任何 IP 维度限制）都必须
共用这里的取值：一旦一处信 X-Forwarded-For、另一处不信，攻击者只需要挑最宽松的
那个入口伪造头就能绕过。
"""

from __future__ import annotations

from fastapi import Request

from app.core.config import settings


def client_ip(request: Request) -> str:
    """取真实来源 IP：只有配置了可信代理层数才解析转发头。

    `trusted_proxy_count=0` 时完全忽略 X-Forwarded-For / X-Real-IP，避免客户端
    直接伪造头绕过按 IP 的限流。Nginx 前置时设为 1，取 XFF 右侧第 1 个地址
    （即 Nginx 实际看到的客户端地址），不是最左侧可伪造段。
    """
    trusted = max(0, int(settings.trusted_proxy_count))
    if trusted > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [part.strip() for part in forwarded.split(",") if part.strip()]
            if len(parts) >= trusted:
                return parts[-trusted]
    return request.client.host if request.client else "unknown"
