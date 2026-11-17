"""指标口径请求模型：同一 code 可累积多个 rule_version，历史统计按版本追溯。"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import MetricStatus


class MetricDefinitionCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    formula: str = Field(min_length=1, max_length=5000)
    description: str | None = Field(default=None, max_length=5000)
    effective_from: datetime | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        return clean

    @field_validator("name", "formula")
    @classmethod
    def strip_required(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        return clean


class MetricDefinitionUpdate(BaseModel):
    """局部更新；调整状态为 retired 时后端自动落 effective_to。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    formula: str | None = Field(default=None, min_length=1, max_length=5000)
    description: str | None = Field(default=None, max_length=5000)
    status: MetricStatus | None = None

    @field_validator("name", "formula")
    @classmethod
    def strip_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        return clean
