"""Monitoring sample and citation review inputs."""

import uuid

from pydantic import BaseModel, Field

from app.models.enums import CitationReviewStatus, ReviewResult


class SampleManualReview(BaseModel):
    result: ReviewResult
    note: str | None = Field(default=None, max_length=2000)


class CitationReview(BaseModel):
    review_status: CitationReviewStatus
    is_brand_related: bool
    channel_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)
