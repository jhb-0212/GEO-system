"""认证接口请求模型：登录。"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
