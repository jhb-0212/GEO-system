"""真实试点采集的硬边界：库白名单、连接串脱敏、执行授权。

这些函数只做纯校验/格式化，不连接数据库，便于单测；脚本在任何写操作之前调用。
"""

from __future__ import annotations

from urllib.parse import urlsplit

PILOT_DATABASE_ALLOWLIST = frozenset({"geo_pilot"})


class PilotGuardError(ValueError):
    """真实采集边界校验失败。"""


def _parsed(database_url: str):
    try:
        parsed = urlsplit(database_url)
    except ValueError as exc:
        raise PilotGuardError("数据库连接串无法解析") from exc
    if not parsed.path or not parsed.path.strip("/"):
        raise PilotGuardError("数据库连接串缺少库名")
    return parsed


def database_name(database_url: str) -> str:
    return _parsed(database_url).path.strip("/").split("/", 1)[0]


def database_host(database_url: str) -> str:
    return _parsed(database_url).hostname or ""


def ensure_pilot_database(
    database_url: str, allowlist: frozenset[str] = PILOT_DATABASE_ALLOWLIST
) -> str:
    """只允许白名单内的试点库；不再用“排除 _smoke”这种反向规则。"""
    name = database_name(database_url)
    if name not in allowlist:
        raise PilotGuardError(f"当前库 {name!r} 不在试点白名单 {sorted(allowlist)}；拒绝真实采集")
    return name


def redacted_database_label(database_url: str) -> str:
    """只输出库名和主机，绝不输出用户名、密码、查询参数。"""
    return f"库={database_name(database_url)} 主机={database_host(database_url) or '(unknown)'}"


def ensure_execution_authorized(*, check_only: bool, execute: bool) -> None:
    """真实采集会写库并发外部请求，必须显式 `--execute`，不能靠“没写 --check-only”默认执行。"""
    if check_only:
        return
    if not execute:
        raise PilotGuardError("真实采集必须显式加 --execute；只校验请用 --check-only")
