"""企业档案请求模型。

字数约束对齐平台侧真实规则（公司介绍 / 创始人介绍 ≥100 且 ≤1000，其余文案 ≤500）；
但只要没填，就允许为空——「必填」属于发布前的完整度检查，不该由保存接口硬拦，
否则新建项目第一步就存不进去。
"""

from datetime import date

from pydantic import BaseModel, Field, field_validator

from typing import Literal


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


ViewKind = Literal["company", "recruit", "meeting", "activity"]


class CompanyProfileViewInput(BaseModel):
    """一套对外画像。文案是表达，不参与事实核验：可核验值仍然只认 facts。"""

    kind: ViewKind
    title: str | None = Field(default=None, max_length=128)
    audience: str | None = Field(default=None, max_length=255)
    scenario_words: list[str] | None = None
    description: str | None = Field(default=None, max_length=1000)
    cautions: str | None = Field(default=None, max_length=500)
    is_active: bool = True

    @field_validator("title", "audience")
    @classmethod
    def strip_view_short(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("description", "cautions")
    @classmethod
    def strip_view_copy(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("scenario_words")
    @classmethod
    def strip_scenario_words(cls, value: list[str] | None) -> list[str] | None:
        return _clean_list(value, max_items=30)


class CompanyProfileViewsUpsert(BaseModel):
    """按 kind 覆盖：只改传进来的那几套，没传的保持原样。"""

    views: list[CompanyProfileViewInput] = Field(min_length=1, max_length=4)

    @field_validator("views")
    @classmethod
    def unique_kinds(cls, value: list[CompanyProfileViewInput]) -> list[CompanyProfileViewInput]:
        kinds = [item.kind for item in value]
        if len(set(kinds)) != len(kinds):
            raise ValueError("同一套画像只能提交一次")
        return value


class CompanyProfileDraftFields(BaseModel):
    """一键填表的产物：全是可选项，证据里没有就留空，不替人猜。

    与 `CompanyProfileUpsert` 的区别是「宽松」：这里不做 100 字硬校验——
    模型给了一段 80 字的介绍，丢掉这一段比整单报错更合理（保存接口仍会拦）。
    """

    legal_name: str | None = Field(default=None, max_length=255)
    brand_name: str | None = Field(default=None, max_length=255)
    slogan: str | None = Field(default=None, max_length=255)
    province: str | None = Field(default=None, max_length=64)

    business_phone: str | None = Field(default=None, max_length=64)
    service_hotline: str | None = Field(default=None, max_length=64)
    contact_email: str | None = Field(default=None, max_length=255)

    stores: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    products: list[CompanyProductInput] = Field(default_factory=list, max_length=8)

    description: str | None = None
    founder_intro: str | None = None
    highlights: str | None = None
    pain_points: str | None = None
    story: str | None = None

    @field_validator("legal_name", "brand_name", "slogan", "province", "business_phone", "service_hotline", "contact_email")
    @classmethod
    def strip_short(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("stores", "industries", "regions")
    @classmethod
    def strip_lists(cls, value: list[str] | None) -> list[str]:
        return _clean_list(value) or []

    @field_validator("highlights", "pain_points", "story")
    @classmethod
    def clip_short_copy(cls, value: str | None) -> str | None:
        clean = _clean_text(value)
        return clean[:500] if clean else None

    @field_validator("description", "founder_intro")
    @classmethod
    def clip_long_copy(cls, value: str | None) -> str | None:
        clean = _clean_text(value)
        if clean is None:
            return None
        if len(clean) < 100:
            return None
        return clean[:1000]
