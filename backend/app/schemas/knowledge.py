"""FAQ 与素材的写接口请求模型。"""

from pydantic import BaseModel, Field, field_validator

from app.models.enums import FaqStatus, MaterialCategory


class FaqCreate(BaseModel):
    question: str = Field(min_length=1, max_length=255)
    answer: str = Field(min_length=1, max_length=10000)
    status: FaqStatus = FaqStatus.DRAFT
    sort_order: int = Field(default=0, ge=0, le=9999)

    @field_validator("question", "answer")
    @classmethod
    def strip_text(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("内容不能为空")
        return clean


class FaqUpdate(BaseModel):
    question: str | None = Field(default=None, min_length=1, max_length=255)
    answer: str | None = Field(default=None, min_length=1, max_length=10000)
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
