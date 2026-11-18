"""引擎凭据的对称加密：系统内填写的 API Key 加密落库，不存明文。

密钥派生：`SHA-256(SECRET_KEY)` → Fernet 密钥。只依赖部署时已有的 SECRET_KEY，
不额外引入配置项；密文带 `v1:` 前缀便于将来轮换算法。

注意：
- 换 SECRET_KEY 会导致旧密文无法解密（表现为凭据失效），需重填 Key；
- 解密失败一律返回空串（回落环境变量路径），不抛异常、不泄露细节；
- 本模块只负责加解密，不碰数据库；读取优先级（库内密文 > 环境变量）在
  `app.services.engine_credentials` 里统一处理。
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

CIPHER_PREFIX = "v1:"

# SECRET_KEY 长度/强度由 config 的校验保证（生产环境拒绝默认值与短密钥）。

def _cipher() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: str) -> str:
    """明文 → `v1:` 前缀的 Fernet 密文；空值返回空串。"""
    value = (plain or "").strip()
    if not value:
        return ""
    token = _cipher().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{CIPHER_PREFIX}{token}"


def decrypt_secret(token: str | None) -> str:
    """密文 → 明文；空值、无前缀或解密失败返回空串（交由调用方回落环境变量）。"""
    if not token:
        return ""
    value = token.strip()
    if not value.startswith(CIPHER_PREFIX):
        return ""
    try:
        plain = _cipher().decrypt(value[len(CIPHER_PREFIX):].encode("ascii"))
    except (InvalidToken, ValueError):
        return ""
    return plain.decode("utf-8", errors="ignore")


def has_encrypted_secret(token: str | None) -> bool:
    """只判断是否存了密文，不尝试解密（用于响应里的配置来源标识）。"""
    return bool(token and token.strip().startswith(CIPHER_PREFIX))
