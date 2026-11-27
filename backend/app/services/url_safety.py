"""引用 URL 安全访问策略：只允许访问公网 HTTP/HTTPS，逐跳校验重定向。

外部引擎返回的引用 URL 是不可信输入，不能直接交给 httpx 抓取：
- 拒绝非 HTTP/HTTPS、带 userinfo、非 80/443 端口；
- 拒绝 localhost、内网、链路本地、云元数据、保留地址等非公网目标；
- 每次重定向都重新解析和校验，禁止公网跳内网；
- 探测请求不走环境代理（trust_env=False），避免代理把请求带进内网。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

MAX_REDIRECTS = 5
ALLOWED_PORTS = {80, 443}
ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}
BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost")


class UnsafeUrlError(ValueError):
    """URL 未通过公网访问策略。"""


def _resolve_host_ips(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({info[4][0].split("%", 1)[0] for info in infos})


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if getattr(address, "ipv4_mapped", None) is not None:
        address = address.ipv4_mapped
    return bool(address.is_global) and not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def validate_public_http_url(url: str) -> str:
    """校验并返回去掉 fragment 的 URL；不通过则抛 `UnsafeUrlError`。"""
    if not isinstance(url, str) or not url.strip():
        raise UnsafeUrlError("URL 为空")
    if len(url) > 4096:
        raise UnsafeUrlError("URL 过长")

    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"不支持的协议：{parsed.scheme or '(空)'}")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URL 不允许携带用户名/密码")
    if not parsed.hostname:
        raise UnsafeUrlError("URL 缺少主机名")

    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError("URL 端口无效") from exc
    effective_port = port or (443 if parsed.scheme.lower() == "https" else 80)
    if effective_port not in ALLOWED_PORTS:
        raise UnsafeUrlError(f"不允许的端口：{effective_port}")

    host = parsed.hostname.strip().rstrip(".").lower()
    if host in BLOCKED_HOSTNAMES or any(host.endswith(suffix) for suffix in BLOCKED_HOST_SUFFIXES):
        raise UnsafeUrlError(f"不允许访问本机/内网主机：{host}")

    # 字面 IP 直接校验；域名先解析，任一解析结果落在非公网就整条拒绝。
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public_ip(host):
            raise UnsafeUrlError(f"不允许访问非公网 IP：{host}")
    else:
        try:
            addresses = _resolve_host_ips(host, effective_port)
        except OSError as exc:
            raise UnsafeUrlError(f"域名解析失败：{host}") from exc
        if not addresses:
            raise UnsafeUrlError(f"域名没有解析结果：{host}")
        unsafe = [address for address in addresses if not _is_public_ip(address)]
        if unsafe:
            raise UnsafeUrlError(f"域名解析到非公网地址：{host} -> {unsafe[0]}")

    return urlunsplit(parsed._replace(fragment=""))


def safe_get(
    url: str,
    *,
    timeout: float = 15.0,
    max_redirects: int = MAX_REDIRECTS,
    headers: dict[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Response:
    """带公网策略的 GET；手动逐跳跟随重定向，每一跳都重新校验。"""
    request_headers = headers or {}
    with httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        headers=request_headers,
        transport=transport,
    ) as client:
        current = validate_public_http_url(url)
        for _ in range(max_redirects + 1):
            response = client.get(current)
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("location")
            if not location:
                raise UnsafeUrlError("重定向缺少 Location")
            current = validate_public_http_url(urljoin(str(response.url), location))
        raise UnsafeUrlError(f"重定向超过 {max_redirects} 次")
