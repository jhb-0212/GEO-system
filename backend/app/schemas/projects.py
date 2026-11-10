"""项目与引擎目录的请求模型。"""

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)


class EngineCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    vendor: str = Field(min_length=1, max_length=64)
    supports_search: bool = True
    supports_citation: bool = True
