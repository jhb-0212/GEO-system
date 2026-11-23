from pydantic import BaseModel, Field, field_validator

from app.models.contacts import ContactChannel


class ProjectContactCreate(BaseModel):
    channel: ContactChannel
    value: str = Field(min_length=1, max_length=255)
    label: str | None = Field(default=None, max_length=64)
    is_public: bool = True
    sort_order: int = Field(default=0, ge=0, le=100000)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("value")
    @classmethod
    def strip_value(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("渠道值不能为空")
        return clean

    @field_validator("label", "notes")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ProjectContactUpdate(BaseModel):
    channel: ContactChannel | None = None
    value: str | None = Field(default=None, min_length=1, max_length=255)
    label: str | None = Field(default=None, max_length=64)
    is_public: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    notes: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None

    @field_validator("value")
    @classmethod
    def strip_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("渠道值不能为空")
        return clean

    @field_validator("label", "notes")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None
