"""监测轮次请求模型：路由层只做编排，入参校验集中在这里。"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ReviewResult


class RoundCreate(BaseModel):
    """新建监测轮次请求。

    `is_baseline=true` 表示基线轮次；全项目只允许一条基线，重复提交走幂等 get-or-create。
    """

    name: str | None = Field(default=None, max_length=128)
    is_baseline: bool = False
    planned_at: datetime | None = None


class SampleReviewRequest(BaseModel):
    """样本人工复核请求（B5）：复核结论只能归入 hit/miss。

    FAILED 为终态，不允许改判；重采走新建任务 / 新 sampling_no，保留原失败样本。
    """

    review_result: ReviewResult
    review_note: str | None = Field(default=None, max_length=500)
