"""媒体资源矩阵配置的写入模型。

只接受结构化目录，不接受任意 JSON：后台保存的每个字段都会直接渲染到公开页，
不能让未校验的内容穿透到展示层。
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Tone = Literal["red", "blue", "dark", "yellow", "green", "orange", "pink", "purple"]
LogoStyle = Literal["text", "square", "china", "circle", "play", "bili"]


class MediaBrandInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    domain: str = Field(default="", max_length=255)
    tone: Tone = "dark"
    logo: str | None = Field(default=None, max_length=512)
    logoStyle: LogoStyle | None = None
    mark: str | None = Field(default=None, max_length=60)
    sub: str | None = Field(default=None, max_length=40)
    more: bool = False

    @field_validator("name", "domain")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("logo")
    @classmethod
    def normalize_logo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if not (clean.startswith("/") or clean.startswith("http://") or clean.startswith("https://")):
            raise ValueError("logo 必须是站内路径（以 / 开头）或 http/https 地址")
        if len(clean) > 512:
            raise ValueError("logo 地址长度不能超过 512")
        return clean

    @field_validator("mark", "sub")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


class MediaSectionInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=200)
    items: list[MediaBrandInput] = Field(default_factory=list, max_length=200)

    @field_validator("title", "note")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class MediaCategoryInput(BaseModel):
    id: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9][a-z0-9-]*$")
    label: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    sections: list[MediaSectionInput] = Field(min_length=1, max_length=30)

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("label", "title", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def unique_sections(self) -> "MediaCategoryInput":
        titles = [section.title for section in self.sections]
        if len(titles) != len(set(titles)):
            raise ValueError("同一分类下的分组标题不能重复")
        return self


class MediaMatrixConfigUpdate(BaseModel):
    payload: list[MediaCategoryInput] = Field(min_length=1, max_length=12)
    note: str | None = Field(default=None, max_length=255)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @model_validator(mode="after")
    def unique_categories(self) -> "MediaMatrixConfigUpdate":
        ids = [category.id for category in self.payload]
        if len(ids) != len(set(ids)):
            raise ValueError("分类 id 不能重复")
        labels = [category.label for category in self.payload]
        if len(labels) != len(set(labels)):
            raise ValueError("分类名称不能重复")
        return self
