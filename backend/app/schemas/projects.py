"""项目与引擎目录的请求模型。"""

import uuid

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    # 项目创建必须同时确定 owner：缺省授予创建者，避免建出没有成员、无法访问的空项目。
    owner_id: uuid.UUID | None = None
    # 显式指定客户；缺省挂默认客户，保持既有调用兼容。
    organization_id: uuid.UUID | None = None


class ProjectConfirm(BaseModel):
    """业务负责人确认资料并设置项目优先级；note 只进审计，不落业务表。"""

    priority: int = Field(ge=1, le=5, description="项目优先级，1 最高、5 最低")
    note: str | None = Field(default=None, max_length=500)


class EngineCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    vendor: str = Field(min_length=1, max_length=64)
    supports_search: bool = True
    supports_citation: bool = True
