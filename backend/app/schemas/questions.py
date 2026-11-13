"""题库、不可变问法版本与目标词请求模型。"""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import QuestionStatus, QuestionType


class QuestionCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    title: str = Field(min_length=1, max_length=255)
    question_type: QuestionType
    initial_text: str = Field(min_length=1)
    audience: str | None = Field(default=None, max_length=128)
    intent: str | None = Field(default=None, max_length=128)
    priority: int = Field(default=100, ge=0)
    status: QuestionStatus = QuestionStatus.DRAFT


class QuestionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: QuestionStatus | None = None
    audience: str | None = Field(default=None, max_length=128)
    intent: str | None = Field(default=None, max_length=128)
    priority: int | None = Field(default=None, ge=0)


class QuestionVersionCreate(BaseModel):
    text: str = Field(min_length=1)
    change_note: str | None = Field(default=None, max_length=2000)


class KeywordCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    category: str | None = Field(default=None, max_length=64)
    priority: int = Field(default=100, ge=0)
    is_active: bool = True
    notes: str | None = Field(default=None, max_length=5000)
    question_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    content_version_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
