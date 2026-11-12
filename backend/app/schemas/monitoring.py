"""监测轮次请求模型：路由层只做编排，入参校验集中在这里。"""

from datetime import datetime

from pydantic import BaseModel, Field


class RoundCreate(BaseModel):
    """新建监测轮次请求。

    `is_baseline=true` 表示基线轮次；全项目只允许一条基线，重复提交走幂等 get-or-create。
    """

    name: str | None = Field(default=None, max_length=128)
    is_baseline: bool = False
    planned_at: datetime | None = None
