"""引用 URL 公网策略：协议/主机/端口/重定向逐项拒绝。"""

import httpx
import pytest

from app.services import url_safety


def _public_dns(host: str, port: int) -> list[str]:
    if host == "public.example":
        return ["93.184.216.34"]
    return ["10.0.0.8"]


def test_rejects_non_public_targets(monkeypatch):
    monkeypatch.setattr(url_safety, "_resolve_host_ips", _public_dns)
    unsafe = [
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.8/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://localhost/",
        "http://metadata.google.internal/",
        "http://public.example:8080/",
        "ftp://public.example/file",
        "http://user:pass@public.example/",
        "http://intranet.example/",
    ]
    for url in unsafe:
        with pytest.raises(url_safety.UnsafeUrlError):
            url_safety.validate_public_http_url(url)


def test_accepts_public_https(monkeypatch):
    monkeypatch.setattr(url_safety, "_resolve_host_ips", _public_dns)
    assert url_safety.validate_public_http_url("HTTPS://public.example/a?b=1#frag") == (
        "https://public.example/a?b=1"
    )


def test_safe_get_follows_only_public_redirects(monkeypatch):
    monkeypatch.setattr(url_safety, "_resolve_host_ips", _public_dns)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "https://public.example/final"}, request=request)
        return httpx.Response(200, text="ok", request=request)

    response = url_safety.safe_get(
        "https://public.example/start", transport=httpx.MockTransport(handler)
    )
    assert response.status_code == 200
    assert response.text == "ok"


def test_safe_get_blocks_public_to_private_redirect(monkeypatch):
    monkeypatch.setattr(url_safety, "_resolve_host_ips", _public_dns)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            request=request,
        )

    with pytest.raises(url_safety.UnsafeUrlError, match="非公网 IP"):
        url_safety.safe_get(
            "https://public.example/start", transport=httpx.MockTransport(handler)
        )


def test_safe_get_redirect_limit(monkeypatch):
    monkeypatch.setattr(url_safety, "_resolve_host_ips", _public_dns)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"Location": "https://public.example/next"}, request=request
        )

    with pytest.raises(url_safety.UnsafeUrlError, match="重定向超过"):
        url_safety.safe_get(
            "https://public.example/start", max_redirects=2, transport=httpx.MockTransport(handler)
        )
