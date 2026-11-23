"""K4 百科词条接口：起草、编辑、提交审核、审、登记外链。"""

import uuid

from pydantic import BaseModel, Field, field_validator


class EncyclopediaEntryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    platform: str = Field(max_length=32)
    summary: str | None = Field(default=None, max_length=1000)
    body: str = Field(min_length=1, max_length=20000)
    references: list = Field(default_factory=list)
    slug: str | None = Field(default=None, max_length=128)


class EncyclopediaEntryUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    platform: str | None = Field(default=None, max_length=32)
    summary: str | None = Field(default=None, max_length=1000)
    body: str | None = Field(default=None, max_length=20000)
    references: list | None = None


class EncyclopediaReview(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=1000)


class EncyclopediaPublish(BaseModel):
    published_url: str = Field(min_length=8, max_length=2000)

    @field_validator("published_url")
    @classmethod
    def _http_only(cls, value: str) -> str:
        value = value.strip()
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("外链必须是 http(s) 地址")
        return value
