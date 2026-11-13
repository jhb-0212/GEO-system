"""题库请求模型：题目元信息与版本正文分离。"""

from pydantic import BaseModel, Field, field_validator

from app.models.enums import QuestionStatus, QuestionType


class QuestionCreate(BaseModel):
    """新建题目：首版正文必须同时提交，服务端在同一个事务里创建 v1。"""

    code: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=255)
    question_type: QuestionType
    audience: str | None = Field(default=None, max_length=128)
    intent: str | None = Field(default=None, max_length=128)
    priority: int = Field(default=100, ge=0)
    status: QuestionStatus = QuestionStatus.DRAFT
    text: str = Field(min_length=1)

    @field_validator("code", "title", "text")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        return clean


class QuestionUpdate(BaseModel):
    """只改元信息；code/title/question_type 与正文都不在这里改。"""

    audience: str | None = Field(default=None, max_length=128)
    intent: str | None = Field(default=None, max_length=128)
    priority: int | None = Field(default=None, ge=0)
    status: QuestionStatus | None = None


class QuestionVersionCreate(BaseModel):
    text: str = Field(min_length=1)
    change_note: str | None = None

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        return clean
