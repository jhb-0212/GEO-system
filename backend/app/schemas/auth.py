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


class ProfileUpdateRequest(BaseModel):
    """个人基础信息：只改对外展示字段，不改账号与权限。"""

    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    job_title: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=64)
    wechat: str | None = Field(default=None, max_length=64)

    @field_validator("display_name", "job_title", "phone", "wechat")
    @classmethod
    def strip_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        return clean or None


class PasswordResetRequest(BaseModel):
    """管理员重置他人密码：只需新密码，不需要原密码。"""

    new_password: str = Field(min_length=8, max_length=128)

    _check_new_password = field_validator("new_password")(_validate_password_strength)


class LoginThrottleResetRequest(BaseModel):
    """解除登录失败限流：账号名必填；来源 IP 可选，留空时清该账号已记录的全部来源。"""

    username: str = Field(min_length=1, max_length=64)
    client_ip: str | None = Field(default=None, max_length=64)


class UserCreateRequest(BaseModel):
    """系统管理员建号：账号创建后默认启用，权限仍需通过项目成员授予。"""

    username: str = Field(min_length=1, max_length=64, pattern=r"[A-Za-z0-9_.-]+")
    display_name: str = Field(min_length=1, max_length=64)
    email: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=128)

    _check_password = field_validator("password")(_validate_password_strength)

    @field_validator("username", "display_name", "email")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        return clean or None


class UserUpdateRequest(BaseModel):
    """账号资料与启停：只允许系统管理员操作；停用会立即让旧会话失效。"""

    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    email: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

    @field_validator("display_name", "email")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        return clean or None
