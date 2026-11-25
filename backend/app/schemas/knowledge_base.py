"""知识库候选事实的人工确认请求。"""

from pydantic import BaseModel, Field, field_validator

from app.models.enums import FactType


class KnowledgeCandidateAccept(BaseModel):
    fact_type: FactType | None = None
    fact_key: str | None = Field(default=None, max_length=128)
    fact_value: str | None = Field(default=None, max_length=2000)
    change_note: str | None = Field(default=None, max_length=500)

    @field_validator("fact_key", "fact_value")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        clean = value.strip() if value else None
        return clean or None


class KnowledgeCandidateReject(BaseModel):
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: str | None) -> str | None:
        clean = value.strip() if value else None
        return clean or None
