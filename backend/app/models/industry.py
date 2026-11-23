"""客户主体、行业预设与项目策略。

- `organizations`：客户一等公民（品牌、退租导出、配额、客户级策略的挂载点）；
- `industry_presets`：行业口径模板，随迁移从 `seed_data/industry_presets/*.json` 落库；
- `project_strategies`：项目在预设之上的差异，版本化、只追加不改写。

`projects.code` 仍保留全局唯一：项目编码带客户前缀（`edu-gz-01`）即可读，
不引入 per-organization 唯一约束，避免所有按 code 查项目的地方都要改。
"""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, event, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin
from sqlalchemy.orm import Session


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active")
    branding: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class IndustryPreset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "industry_presets"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))


class ProjectStrategy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_strategies"
    __table_args__ = (
        UniqueConstraint("project_id", "strategy_key", "version", name="uq_project_strategies_key_version"),
        Index("ix_project_strategies_project_key", "project_id", "strategy_key"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    strategy_key: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active")
    note: Mapped[str | None] = mapped_column(Text)



@event.listens_for(Session, "before_flush")
def _attach_default_organization(session, flush_context, instances) -> None:
    """任何入口新建项目而没指定客户时，挂到默认客户。

    这样测试、脚本、导入工具都不必各自处理；数据库仍保持 organization_id NOT NULL，
    不会出现「项目没有客户」的脏数据。
    """
    from app.models.system import Project

    pending = [obj for obj in session.new if isinstance(obj, Project) and obj.organization_id is None]
    if not pending:
        return
    org = session.scalar(select(Organization).where(Organization.code == "default-client"))
    if org is None:
        org = Organization(code="default-client", name="默认客户", status="active", branding={})
        session.add(org)
        session.flush()
    for project in pending:
        project.organization_id = org.id
