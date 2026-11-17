"""FAQ 与素材的写接口请求模型。"""

from pydantic import BaseModel, Field, field_validator

from app.models.enums import FaqStatus, MaterialCategory


def _normalize_category(value: str | None) -> str | None:
    """分类归一：去首尾空白、合并中间连续空白，空串归 None。

    目的是防止「课程」和「课程 」被当成两个分类，下拉里出现重复项。
    """
    if value is None:
        return None
    return " ".join(value.split()) or None


class FaqCreate(BaseModel):
    question: str = Field(min_length=1, max_length=255)
    answer: str = Field(min_length=1, max_length=10000)
    category: str | None = Field(default=None, max_length=64)
    status: FaqStatus = FaqStatus.DRAFT
    sort_order: int = Field(default=0, ge=0, le=9999)

    @field_validator("question", "answer")
    @classmethod
    def strip_text(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("内容不能为空")
        return clean

    @field_validator("category")
    @classmethod
    def strip_category(cls, value: str | None) -> str | None:
        return _normalize_category(value)


class FaqUpdate(BaseModel):
    question: str | None = Field(default=None, min_length=1, max_length=255)
    answer: str | None = Field(default=None, min_length=1, max_length=10000)
    category: str | None = Field(default=None, max_length=64)
    status: FaqStatus | None = None
    sort_order: int | None = Field(default=None, ge=0, le=9999)

    @field_validator("question", "answer")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("内容不能为空")
        return clean

    @field_validator("category")
    @classmethod
    def strip_category(cls, value: str | None) -> str | None:
        return _normalize_category(value)


class MaterialUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    category: MaterialCategory | None = None
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("标题不能为空")
        return clean
