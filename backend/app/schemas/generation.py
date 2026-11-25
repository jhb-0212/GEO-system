"""G1/G2 生成批次接口：建批、跑批、审稿、导出。"""

from typing import Literal

from pydantic import BaseModel, Field


class GenerationBatchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source: Literal["opportunity", "question"]
    limit: int = Field(default=10, ge=1, le=50)
    # 留空 = 模板合成（默认）。填了引擎会明确报「模型出稿未开启」
    engine_code: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=500)


class GenerationItemReview(BaseModel):
    reviewed: bool

class GenerationSampleReviewRequest(BaseModel):
    sample_size: int = Field(default=3, ge=1, le=10)
    threshold: int = Field(default=60, ge=0, le=100)


class GenerationGateApprovalRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)
