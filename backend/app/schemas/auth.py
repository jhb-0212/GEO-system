"""Authentication request bodies."""

from pydantic import BaseModel, Field, field_validator


def _validate_password_strength(value: str) -> str:
    """口令最低要求：长度由 Field 约束，这里只补「不像口令」的两种情况。

    刻意不引入字典匹配与复杂度矩阵——那属于部署策略，且会让改密接口新增一类
    契约。纯数字与单一重复字符是最常见的弱口令，判定确定、成本最低。
    """
    if value.isdigit():
        raise ValueError("密码不能是纯数字")
    if len(set(value)) < 2:
        raise ValueError("密码不能由同一个字符重复组成")
    return value


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)

    _check_new_password = field_validator("new_password")(_validate_password_strength)


class PasswordResetRequest(BaseModel):
    """管理员重置他人密码：只需新密码，不需要原密码。"""

    new_password: str = Field(min_length=8, max_length=128)

    _check_new_password = field_validator("new_password")(_validate_password_strength)


class LoginThrottleResetRequest(BaseModel):
    """解除登录失败限流：账号名必填；来源 IP 可选，留空时清该账号已记录的全部来源。"""

    username: str = Field(min_length=1, max_length=64)
    client_ip: str | None = Field(default=None, max_length=64)
