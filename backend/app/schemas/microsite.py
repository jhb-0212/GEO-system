"""K8 微站请求模型：站点信息与模块内容。"""

from pydantic import BaseModel, Field


class SiteUpdate(BaseModel):
    """只改站点信息；slug 会再被规范化一次，空串视为非法。"""

    slug: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=120)
    intro: str | None = Field(default=None, max_length=2000)
    is_published: bool | None = None


class SiteModuleUpdate(BaseModel):
    """模块内容整体替换：后台是整段 JSON 编辑，不做字段级补丁。"""

    title: str | None = Field(default=None, max_length=120)
    content: dict | None = None
    sort_order: int | None = Field(default=None, ge=0, le=99)
    is_active: bool | None = None
