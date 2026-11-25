"""机会中心请求模型：六因子固定键、1–5 分，权重可调但必须为正。"""

import uuid
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.enums import OpportunityGapType, OpportunityStatus


class OpportunityScoreFactors(BaseModel):
    business_value: int = Field(ge=1, le=5, description="业务目标重要度")
    competitor_gap: int = Field(ge=1, le=5, description="竞品引用差距")
    material_readiness: int = Field(ge=1, le=5, description="官方素材就绪度")
    implementation_cost: int = Field(ge=1, le=5, description="实施成本，越高越难落地")
    channel_authorization: int = Field(ge=1, le=5, description="授权发布渠道")
    verifiability: int = Field(ge=1, le=5, description="下一轮可验证性")


class OpportunityScoreWeights(BaseModel):
    business_value: float = Field(default=1.0, ge=0, le=5)
    competitor_gap: float = Field(default=1.0, ge=0, le=5)
    material_readiness: float = Field(default=1.0, ge=0, le=5)
    implementation_cost: float = Field(default=1.0, ge=0, le=5)
    channel_authorization: float = Field(default=1.0, ge=0, le=5)
    verifiability: float = Field(default=1.0, ge=0, le=5)

    @model_validator(mode="after")
    def _at_least_one_weight(self) -> "OpportunityScoreWeights":
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("六因子权重之和必须大于 0")
        return self


class OpportunityCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    gap_type: OpportunityGapType
    question_id: uuid.UUID | None = None
    sample_id: uuid.UUID | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    score_factors: OpportunityScoreFactors
    score_weights: OpportunityScoreWeights = Field(default_factory=OpportunityScoreWeights)
    owner_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)


class OpportunityUpdate(BaseModel):
    status: OpportunityStatus | None = None
    owner_id: uuid.UUID | None = None
    score_factors: OpportunityScoreFactors | None = None
    score_weights: OpportunityScoreWeights | None = None
    linked_content_plan_id: uuid.UUID | None = None
    linked_content_item_id: uuid.UUID | None = None
    linked_publish_task_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)


class OpportunitySuggestionAccept(BaseModel):
    owner_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class OpportunitySuggestionDismiss(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class OpportunitySuggestionGenerate(BaseModel):
    round_id: uuid.UUID | None = None
    limit: int = Field(default=80, ge=1, le=200)
