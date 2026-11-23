"""企业档案请求模型。

字数约束对齐平台侧真实规则（公司介绍 / 创始人介绍 ≥100 且 ≤1000，其余文案 ≤500）；
但只要没填，就允许为空——「必填」属于发布前的完整度检查，不该由保存接口硬拦，
否则新建项目第一步就存不进去。
"""

from datetime import date

from pydantic import BaseModel, Field, field_validator


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    return clean or None


def _clean_list(values: list[str] | None, max_items: int = 50) -> list[str] | None:
    if values is None:
        return None
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        term = (raw or "").strip()
        if not term or term.casefold() in seen:
            continue
        seen.add(term.casefold())
        result.append(term)
        if len(result) >= max_items:
            break
    return result


class CompanyProductInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    summary: str | None = Field(default=None, max_length=500)
    highlights: str | None = Field(default=None, max_length=500)

    @field_validator("name", "summary", "highlights")
    @classmethod
    def strip_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        return clean or None


class CompanyProfileUpsert(BaseModel):
    """整体替换：传什么就是什么，避免局部更新留下旧文案。"""

    legal_name: str = Field(min_length=1, max_length=255)
    brand_name: str | None = Field(default=None, max_length=255)
    slogan: str | None = Field(default=None, max_length=255)
    province: str | None = Field(default=None, max_length=64)
    headcount: int | None = Field(default=None, ge=0, le=1_000_000)
    founded_on: date | None = None

    business_phone: str | None = Field(default=None, max_length=64)
    service_hotline: str | None = Field(default=None, max_length=64)
    contact_email: str | None = Field(default=None, max_length=255)

    stores: list[str] | None = None
    official_urls: list[str] | None = None
    industries: list[str] | None = None
    regions: list[str] | None = None
    products: list[CompanyProductInput] | None = None

    description: str | None = None
    highlights: str | None = Field(default=None, max_length=500)
    pain_points: str | None = Field(default=None, max_length=500)
    story: str | None = Field(default=None, max_length=500)
    founder_intro: str | None = None
    extra: str | None = Field(default=None, max_length=5000)

    is_active: bool = True

    # 与 facts 冲突时的显式确认键（形如 "business_phone:<fact_id>"）。
    # 没列进来的冲突一律拒绝写入——这是「事实唯一源」的兜底闸门。
    acknowledged_conflicts: list[str] = Field(default_factory=list)

    @field_validator("brand_name", "slogan", "province")
    @classmethod
    def strip_short_fields(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("business_phone", "service_hotline", "contact_email", "extra")
    @classmethod
    def strip_contact_fields(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("stores", "official_urls", "industries", "regions")
    @classmethod
    def strip_string_lists(cls, value: list[str] | None) -> list[str] | None:
        return _clean_list(value)

    @field_validator("description", "founder_intro")
    @classmethod
    def validate_long_copy(cls, value: str | None) -> str | None:
        clean = _clean_text(value)
        if clean is None:
            return None
        if len(clean) < 100:
            raise ValueError("公司介绍/创始人介绍少于 100 字，AI 无法据此判断业务与主体")
        if len(clean) > 1000:
            raise ValueError("公司介绍/创始人介绍超过 1000 字，超出展示与投喂上限")
        return clean

    @field_validator("highlights", "pain_points", "story")
    @classmethod
    def strip_copy_fields(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("legal_name")
    @classmethod
    def require_legal_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("公司名称不能为空")
        return clean
