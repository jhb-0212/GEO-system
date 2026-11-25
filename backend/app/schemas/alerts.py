"""预警接口入参。"""

from pydantic import BaseModel, Field


class AlertRuleUpdate(BaseModel):
    is_enabled: bool | None = None
    severity: str | None = None
    thresholds: dict[str, float | int] | None = Field(default=None)


class AlertEventAck(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class AlertEvaluateRequest(BaseModel):
    """立即重算；不传窗口时按规则自身 window_days。"""

    dry_run: bool = False
