"""认证与口令：JWT 签发/校验、口令哈希。权限和令牌版本每次落库判断。"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(plain_password, password_hash)
    except ValueError:
        # 历史哈希格式不兼容时按校验失败处理，不向上抛异常
        return False


def create_access_token(
    user_id: uuid.UUID, *, token_version: int, expires_minutes: int | None = None
) -> str:
    minutes = expires_minutes or settings.access_token_expire_minutes
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "access",
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """校验签名与过期时间；失败抛 jwt 异常，由调用方翻译成 401。"""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
