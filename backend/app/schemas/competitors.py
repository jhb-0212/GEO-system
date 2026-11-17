"""竞品台账请求模型：竞品名在项目内唯一，用于答案提及归因与 Share of Voice。"""

from pydantic import BaseModel, Field, field_validator


class CompetitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    domain: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=5000)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        return clean

    @field_validator("domain")
    @classmethod
    def strip_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class CompetitorUpdate(BaseModel):
    """局部更新；显式 null 清空可空字段，不传保持原值。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    domain: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        return clean

    @field_validator("domain")
    @classmethod
    def strip_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None
