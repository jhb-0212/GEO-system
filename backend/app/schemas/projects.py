"""项目与引擎目录的请求模型。"""

import uuid

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    # 项目创建必须同时确定 owner：缺省授予创建者，避免建出没有成员、无法访问的空项目。
    owner_id: uuid.UUID | None = None


class EngineCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    vendor: str = Field(min_length=1, max_length=64)
    supports_search: bool = True
    supports_citation: bool = True
