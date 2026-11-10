"""发布请求模型。"""

from pydantic import BaseModel

from app.models.enums import AttemptResult, PublishMode


class PublishAttemptCreate(BaseModel):
    result: AttemptResult = AttemptResult.SUCCESS
    mode: PublishMode = PublishMode.MANUAL
    error_code: str | None = None
    error_note: str | None = None
