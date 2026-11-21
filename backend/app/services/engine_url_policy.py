"""引擎入口地址策略：入口 URL 不能把受控凭据带到任意地址。

这里是入口地址的唯一事实源：
- 已知协议只允许官方 host + 固定 path；
- openai_compatible 只允许官方 provider host 或部署方显式配置的 allowlist；
- 所有入口拒绝 userinfo、IP 字面量、回环/内网/链路本地/云元数据地址和非常用端口。

DNS rebinding 不能在纯字符串校验里完全消除；部署侧仍需 egress 网络策略收口。
"""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse

from app.core.config import settings
from app.models.enums import EngineProtocol

# 官方端点：host + path 必须同时匹配，避免把官方 key 发到同 host 的任意路径。
OFFICIAL_ENDPOINTS: dict[EngineProtocol, tuple[str, str]] = {
    EngineProtocol.WENXIN_SEARCH: (
        "qianfan.baidubce.com",
        "/v2/ai_search/web_search",
    ),
    EngineProtocol.DOUBAO_SEARCH: (
        "ark.cn-beijing.volces.com",
        "/api/v3/responses",
    ),
    EngineProtocol.DEEPSEEK_WEB_SEARCH: (
        "api.deepseek.com",
        "/responses",
    ),
    EngineProtocol.YUANBAO_SEARCH: (
        "wsa.tencentcloudapi.com",
        "/",
    ),
}

# openai_compatible 允许的官方 provider host；自定义私有模型必须通过
# ENGINE_ALLOWED_HOSTS 显式登记，不能任意填一个公网域名。
OFFICIAL_PROVIDER_HOSTS = {
    "api.deepseek.com",
    "ark.cn-beijing.volces.com",
    "qianfan.baidubce.com",
    "wsa.tencentcloudapi.com",
    "api.openai.com",
    "api.moonshot.cn",
    "api.moonshot.ai",
    "metaso.cn",
    "open.bigmodel.cn",
    "api.z.ai",
    "dashscope.aliyuncs.com",
    "dashscope-intl.aliyuncs.com",
    "api.360.cn",
}

BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def _allowed_hosts_from_settings() -> set[str]:
    raw = settings.engine_allowed_hosts
    return {
        item.strip().casefold()
        for item in raw.split(",")
        if item.strip()
    }


def _clean_host(host: str) -> str:
    return host.strip().casefold().strip(".")


def _reject_ip_literal(host: str) -> None:
    try:
        ip = ip_address(host)
    except ValueError:
        return
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        raise ValueError("entry_url 不允许使用内网、回环或保留地址")
    raise ValueError("entry_url 不允许直接使用 IP 字面量，请使用官方域名")


def validate_engine_url(
    value: str | None,
    protocol: EngineProtocol,
    *,
    allowed_hosts: set[str] | None = None,
) -> str | None:
    """校验并返回清理后的 URL；None 表示“未配置”，由调用方决定是否使用默认端点。"""
    if value is None:
        return None
    clean = value.strip()
    if not clean:
        return None

    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("entry_url 必须以 http:// 或 https:// 开头")
    if parsed.username or parsed.password:
        raise ValueError("entry_url 不允许包含用户名或密码")
    if parsed.fragment:
        raise ValueError("entry_url 不允许包含 fragment")
    if not parsed.hostname:
        raise ValueError("entry_url 缺少合法 host")
    if parsed.port is not None and parsed.port not in {80, 443}:
        raise ValueError("entry_url 不允许使用非常用端口")

    host = _clean_host(parsed.hostname)
    if host in BLOCKED_HOSTS:
        raise ValueError("entry_url 不允许使用本机/元数据服务地址")
    _reject_ip_literal(host)

    official = OFFICIAL_ENDPOINTS.get(protocol)
    if official is not None:
        expected_host, expected_path = official
        if host != expected_host:
            raise ValueError(f"{protocol.value} 入口只允许官方 host：{expected_host}")
        if parsed.scheme != "https":
            raise ValueError(f"{protocol.value} 入口只允许 https")
        path = parsed.path.rstrip("/") or "/"
        if path != expected_path:
            raise ValueError(f"{protocol.value} 入口只允许官方 path：{expected_path}")
        if parsed.query:
            raise ValueError(f"{protocol.value} 入口不允许携带 query")
        return clean

    if protocol == EngineProtocol.OPENAI_COMPATIBLE:
        allowed = OFFICIAL_PROVIDER_HOSTS | (allowed_hosts or _allowed_hosts_from_settings())
        if host not in allowed:
            raise ValueError(
                "openai_compatible 入口只允许官方 provider host 或 ENGINE_ALLOWED_HOSTS 登记 host"
            )
        if parsed.scheme != "https":
            raise ValueError("openai_compatible 入口只允许 https")
        return clean

    # custom 是「登记待接入平台」的入口，不做域名白名单：否则用户连登记都做不到，
    # 连接测试也会把「协议未实现」误报成「地址非法」。
    # 这里仍拒绝内网 / IP / userinfo / 非常用端口（见上方通用校验）；真正发请求前
    # build_entry_adapter 会再调用一次本函数。将来给 custom 接真实适配器时，
    # 必须同时把它的 host 收进 OFFICIAL_PROVIDER_HOSTS 或 ENGINE_ALLOWED_HOSTS，
    # 否则等于继承了任意公网地址。
    if parsed.scheme != "https":
        raise ValueError("entry_url 只允许 https")
    return clean
