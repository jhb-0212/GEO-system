"""问题候选池请求模型：挖掘、导入与人工确认。"""

from pydantic import BaseModel, Field, field_validator

from app.models.enums import QuestionCandidateBucket


class QuestionCandidateMine(BaseModel):
    limit: int = Field(default=20, ge=1, le=50)
    # 空列表表示三桶全要；顺序由服务端固定，不依赖前端勾选顺序。
    buckets: list[QuestionCandidateBucket] = Field(default_factory=list)


class QuestionCandidateImport(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=100)
    bucket: QuestionCandidateBucket = QuestionCandidateBucket.PURCHASE
    source_ref: str | None = Field(default=None, max_length=255)

    @field_validator("texts")
    @classmethod
    def clean_texts(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            if len(text) > 500:
                raise ValueError("单条问句不能超过 500 字")
            cleaned.append(text)
        if not cleaned:
            raise ValueError("至少导入一条问句")
        return cleaned
