"""引擎入口凭据解析：系统内填写的密文优先，环境变量兜底。

为什么有这个模块：
- 运营要求「在系统里填 Key」，不再每次都改 `.env`；
- 但 Key 不能明文落库：写入时按 `SECRET_KEY` 派生密钥加密（`app/core/secrets_box`），
  接口与日志均不回显；
- 旧的运维路径（`credential_ref` 指向环境变量）继续有效，且优先级低于库内密文：
  系统内填过就以系统的为准，清空后自动回落到环境变量。

所有会真正发外部请求的地方（采集执行、测试连接、各适配器）都必须走这里，
不要直接 `read_credential_env`，否则系统内填的 Key 不生效。
"""

from __future__ import annotations

from app.core.credentials import read_credential_env
from app.core.secrets_box import decrypt_secret, has_encrypted_secret


def resolve_entry_secret(entry, *, default_ref: str | None = None) -> str:
    """入口主密钥：库内密文 > `credential_ref` 环境变量 > 协议默认变量名。

    `default_ref` 用于历史漏填 `credential_ref` 的搜索类入口（按协议取默认变量名）。
    """
    stored = decrypt_secret(getattr(entry, "encrypted_secret", None))
    if stored:
        return stored
    ref = (getattr(entry, "credential_ref", None) or default_ref or "").strip()
    return read_credential_env(ref) if ref else ""


def resolve_entry_secret_secondary(entry, *, default_ref: str) -> str:
    """双密钥协议的第二值（元宝 SecretKey）：库内密文 > 固定环境变量。"""
    stored = decrypt_secret(getattr(entry, "encrypted_secret_secondary", None))
    if stored:
        return stored
    return read_credential_env(default_ref)


def credential_source(entry, *, default_ref: str | None = None) -> str:
    """凭据来源：`database` / `environment` / `none`，只用于展示，不返回任何值。"""
    if resolve_entry_secret(entry, default_ref=default_ref):
        return "database" if has_encrypted_secret(getattr(entry, "encrypted_secret", None)) else "environment"
    return "none"


def secondary_credential_configured(entry, *, default_ref: str) -> bool:
    return bool(resolve_entry_secret_secondary(entry, default_ref=default_ref))
