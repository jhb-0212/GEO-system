"""品牌实体配置请求模型。

三个列表字段的分工在接口层就要卡住，避免前端把地址电话塞进 aliases：
- `aliases` 只放品牌名称类词条（正式名/简称/旧名/英文名），命中即 brand_mentioned；
- `identifiers` 放地址、电话、公众号名等唯一标识，命中即 brand_identified，不影响提及率；
- `owned_domains` 放品牌自有域名，用于引用归属与信源占比。

服务端会做去空白与去重；不做大小写折叠（中文为主，折叠反而会误伤英文名写法）。
"""

from pydantic import BaseModel, Field, field_validator


def _strip_list(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = value.strip()
        if not term or term.casefold() in seen:
            continue
        seen.add(term.casefold())
        cleaned.append(term)
    return cleaned


class BrandProfileUpsert(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=255)
    aliases: list[str] | None = None
    identifiers: list[str] | None = None
    owned_domains: list[str] | None = None
    notes: str | None = Field(default=None, max_length=5000)
    is_active: bool = True

    @field_validator("canonical_name")
    @classmethod
    def strip_canonical(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("品牌正式名不能为空")
        return clean

    @field_validator("aliases", "identifiers", "owned_domains")
    @classmethod
    def strip_lists(cls, value: list[str] | None) -> list[str] | None:
        return _strip_list(value)

    @field_validator("owned_domains")
    @classmethod
    def normalize_domains(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [domain.casefold().removeprefix("www.").strip(".") for domain in value]
