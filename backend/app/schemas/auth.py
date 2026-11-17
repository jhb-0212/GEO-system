"""Authentication request bodies."""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class PasswordResetRequest(BaseModel):
    """管理员重置他人密码：只需新密码，不需要原密码。"""

    new_password: str = Field(min_length=8, max_length=128)


class LoginThrottleResetRequest(BaseModel):
    """解除登录失败限流：账号名必填；来源 IP 可选，留空时清该账号已记录的全部来源。"""

    username: str = Field(min_length=1, max_length=64)
    client_ip: str | None = Field(default=None, max_length=64)
