"""系统级数据：用户、角色、项目注册、项目授权、审计、口径、Outbox。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import (
    ImportBatchStatus,
    MetricStatus,
    OutboxStatus,
    PermissionScope,
    ProjectStatus,
    RoleCode,
)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # 系统管理员：可建项目、维护引擎目录、管理任意项目成员。与项目内 admin 角色是两个层级。
    is_system_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    code: Mapped[RoleCode] = mapped_column(str_enum(RoleCode, "role_code"), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """能力码目录：接口只认能力码，不认角色名，角色调整不动代码。"""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[PermissionScope] = mapped_column(
        str_enum(PermissionScope, "permission_scope"),
        nullable=False,
        default=PermissionScope.PROJECT,
        server_default=PermissionScope.PROJECT.value,
    )
    description: Mapped[str | None] = mapped_column(Text)


class RolePermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """角色—能力映射：系统管理员与项目管理员的能力集合在此显式区分。"""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_role_permission"),
        Index("ix_role_permissions_role", "role_id"),
        Index("ix_role_permissions_permission", "permission_id"),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """项目注册：所有业务数据通过 project_id 归属到这里的记录。"""

    __tablename__ = "projects"

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        str_enum(ProjectStatus, "project_status"),
        nullable=False,
        default=ProjectStatus.ACTIVE,
        server_default=ProjectStatus.ACTIVE.value,
    )
    description: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")


class ProjectMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """项目级授权：权限判断以这里为准，不信任前端传来的 project_id。"""

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
        Index("ix_project_members_user", "user_id", "is_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    project: Mapped[Project] = relationship(lazy="joined")
    role: Mapped[Role] = relationship(lazy="joined")


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """关键操作审计：导出、删除、权限变更、审批、发布必须留痕。"""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_project_created", "project_id", "created_at"),
        Index("ix_audit_logs_target", "target_type", "target_id"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[uuid.UUID | None] = mapped_column()
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OutboxEvent(UUIDPrimaryKeyMixin, Base):
    """事务性 Outbox：业务记录与入队动作同一事务写，Worker 只消费已提交事件。

    project_id 允许为空，只有系统级 topic（`system.` 前缀）可以为空；
    项目级事件必须带项目标识，由库层 CHECK 强制，避免系统事件被 NOT NULL 卡住。
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_events_status_created", "status", "created_at"),
        CheckConstraint(
            "project_id IS NOT NULL OR topic LIKE 'system.%'",
            name="ck_outbox_events_project_or_system",
        ),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        str_enum(OutboxStatus, "outbox_status"),
        nullable=False,
        default=OutboxStatus.PENDING,
        server_default=OutboxStatus.PENDING.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_note: Mapped[str | None] = mapped_column(Text)


class MetricDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """指标口径版本：历史统计必须能追溯到当时使用的规则版本。"""

    __tablename__ = "metric_definitions"
    __table_args__ = (
        UniqueConstraint("project_id", "code", "rule_version", name="uq_metric_definitions_project_code_version"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[MetricStatus] = mapped_column(
        str_enum(MetricStatus, "metric_status"),
        nullable=False,
        default=MetricStatus.ACTIVE,
        server_default=MetricStatus.ACTIVE.value,
    )


class ImportBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """历史数据导入批次：旧数据标识、前后数量核对、回滚追溯都挂在这里。

    导入脚本必须先建批次，再往目标表写数据并回填 import_batch_id，
    回滚按批次删除或停用，审计日志记录批次 id。
    """

    __tablename__ = "import_batches"
    __table_args__ = (Index("ix_import_batches_project_started", "project_id", "started_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[ImportBatchStatus] = mapped_column(
        str_enum(ImportBatchStatus, "import_batch_status"),
        nullable=False,
        default=ImportBatchStatus.PENDING,
        server_default=ImportBatchStatus.PENDING.value,
    )
    # 逐表数量核对：导入前后行数、成功/跳过/失败行数
    counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rollback_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
