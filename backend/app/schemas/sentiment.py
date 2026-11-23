from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SentimentLabelIn(BaseModel):
    polarity: Literal["positive", "neutral", "negative"]
    grade: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("grade", "note")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None
