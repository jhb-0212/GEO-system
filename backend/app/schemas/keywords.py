"""关键词请求模型：复用 question.read / question.write，不新增权限码。"""

from pydantic import BaseModel, Field, field_validator


class KeywordCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    category: str | None = Field(default=None, max_length=64)
    priority: int = Field(default=100, ge=0)
    is_active: bool = True
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        return clean


class KeywordUpdate(BaseModel):
    """局部更新；DELETE 只做软删，不物理删除关键词。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    category: str | None = Field(default=None, max_length=64)
    priority: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("不能为空")
        return clean
