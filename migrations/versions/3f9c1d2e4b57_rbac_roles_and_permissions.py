"""RBAC 重构：角色拆分为 6 个、新增能力矩阵表、迁移历史 admin 角色。

revision: 3f9c1d2e4b57
down_revision: 482fc59c5212

变更点：
1. 建 permissions（能力码目录）与 role_permissions（角色—能力映射）。
2. roles.code 的 CHECK 从 5 个值扩为 6 个值，`admin` 就地改名为 `project_admin`（历史授权不断裂）。
3. 补 `sys_admin` 角色行（系统管理员能力只由 sys_admin 角色持有，与 users.is_system_admin 标记配合）。
"""

from alembic import op
import sqlalchemy as sa

revision = "3f9c1d2e4b57"
down_revision = "482fc59c5212"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="project"),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
        sa.CheckConstraint("scope in ('system', 'project')", name="ck_permissions_permission_scope"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("role_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("permission_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_role_permissions_role", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["permission_id"], ["permissions.id"], name="fk_role_permissions_permission", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_role_permission"),
    )
    op.create_index("ix_role_permissions_role", "role_permissions", ["role_id"])
    op.create_index("ix_role_permissions_permission", "role_permissions", ["permission_id"])

    # 角色 CHECK 扩为 6 个值；历史 admin 就地改名，已有 project_members 授权继续有效
    op.execute("ALTER TABLE roles DROP CONSTRAINT IF EXISTS ck_roles_role_code")
    op.execute(
        "UPDATE roles SET code = 'project_admin', name = '项目管理员', "
        "description = '管理本项目成员，只能授予 editor/reviewer/viewer/lead_ops' "
        "WHERE code = 'admin'"
    )
    op.execute(
        "INSERT INTO roles (id, code, name, description, created_at, updated_at) "
        "SELECT gen_random_uuid(), 'sys_admin', '系统管理员', "
        "'创建项目、维护引擎目录、管理系统级配置；不默认读写项目业务数据', now(), now() "
        "WHERE NOT EXISTS (SELECT 1 FROM roles WHERE code = 'sys_admin')"
    )
    op.execute(
        "ALTER TABLE roles ADD CONSTRAINT ck_roles_role_code "
        "CHECK (code IN ('sys_admin','project_admin','editor','reviewer','viewer','lead_ops'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE roles DROP CONSTRAINT IF EXISTS ck_roles_role_code")
    op.execute("DELETE FROM roles WHERE code = 'sys_admin'")
    op.execute(
        "UPDATE roles SET code = 'admin', name = '管理员', "
        "description = '项目配置、用户与权限、全部业务操作' WHERE code = 'project_admin'"
    )
    op.execute(
        "ALTER TABLE roles ADD CONSTRAINT ck_roles_role_code "
        "CHECK (code IN ('admin','editor','reviewer','viewer','lead_ops'))"
    )

    op.drop_index("ix_role_permissions_permission", table_name="role_permissions")
    op.drop_index("ix_role_permissions_role", table_name="role_permissions")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
