from datetime import date

from pydantic import BaseModel, Field, field_validator


class CertificationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=64)
    issuer: str | None = Field(default=None, max_length=255)
    cert_no: str | None = Field(default=None, max_length=128)
    issued_on: date | None = None
    expires_on: date | None = None
    evidence_url: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("资质名称不能为空")
        return clean

    @field_validator("category", "issuer", "cert_no", "evidence_url", "notes")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class CertificationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=64)
    issuer: str | None = Field(default=None, max_length=255)
    cert_no: str | None = Field(default=None, max_length=128)
    issued_on: date | None = None
    expires_on: date | None = None
    evidence_url: str | None = Field(default=None, max_length=512)
    notes: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None

    @field_validator("category", "issuer", "cert_no", "evidence_url", "notes")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("资质名称不能为空")
        return clean