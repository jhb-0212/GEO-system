"""公开 http(s) 地址校验：发布回执、公开站页面共用。

这里只校验“是不是一个可对外展示的绝对 http(s) 地址”，不发起任何请求：
- 拒绝非 http/https、userinfo、空 host、fragment；
- 拒绝 localhost / 云元数据主机 / 内网、回环、链路本地、保留、组播 IP。
公网 IP 字面量允许（真实外链可能直接用 IP），端口不限制。
"""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse

BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def validate_public_http_url(value: str | None, *, field_name: str = "url") -> str | None:
    if value is None:
        return None
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field_name} 不能为空")

    parsed = urlparse(clean)
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ValueError(f"{field_name} 必须是 http:// 或 https:// 绝对地址")
    if parsed.username or parsed.password:
        raise ValueError(f"{field_name} 不允许包含用户名或密码")
    if parsed.fragment:
        raise ValueError(f"{field_name} 不允许包含 fragment")
    if not parsed.hostname:
        raise ValueError(f"{field_name} 缺少合法 host")

    host = parsed.hostname.casefold().strip(".")
    if host in BLOCKED_HOSTS:
        raise ValueError(f"{field_name} 不允许使用本机/元数据服务地址")

    try:
        ip = ip_address(host)
    except ValueError:
        return clean
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        raise ValueError(f"{field_name} 不允许使用内网、回环或保留地址")
    return clean
