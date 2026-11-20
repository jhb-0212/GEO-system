"""监测轮次请求模型：路由层只做编排，入参校验集中在这里。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.enums import AnswerKind, ReviewResult, SamplingMode


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


class SampleReviewRecordRequest(BaseModel):
    """终态样本事后复核记录：只补复核留痕，不改判、不改状态机。

    与 `SampleReviewRequest` 的区别：后者只用于 `manual_review` 样本的归入
    hit/miss；这里允许对已终态的 hit/miss/failed/no_answer_surface 样本补记
    复核人、时间、结论和备注，统计分母与样本状态保持不变。
    """

    review_note: str = Field(min_length=1, max_length=2000)
    review_result: ReviewResult | None = None


class ManualSampleCreate(BaseModel):
    """手测样本录入：把网页端人工看到的回答补进监测证据链。

    - 任务必须已有；样本按 `(task_id, attempt_no)` 追加，不改写原自动采样；
    - `answer_kind` 必填，避免把“生成回答”和“检索结果”混进同一个分母；
    - `brand_mentioned` / `brand_identified` 留空时按品牌词表自动判定；
    - 引用 URL 只做原始证据登记，渠道归属仍走发布回执匹配，不按域名猜。
    """

    raw_answer: str = Field(min_length=1, max_length=200_000)
    answer_kind: AnswerKind
    sampling_mode: SamplingMode | None = None
    sampled_at: datetime | None = None
    brand_mentioned: bool | None = None
    brand_identified: bool | None = None
    citation_urls: list[str] = Field(default_factory=list, max_length=20)
    raw_response: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=500)

    @field_validator("citation_urls")
    @classmethod
    def _clean_citation_urls(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            url = value.strip()
            if not url or url in seen:
                continue
            seen.add(url)
            cleaned.append(url)
        return cleaned
