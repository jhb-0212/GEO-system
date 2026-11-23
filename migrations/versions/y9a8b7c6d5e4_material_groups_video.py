"""素材分组与视频：materials 加 group_name / sort_order / source，枚举加 video

Revision ID: y9a8b7c6d5e4
Revises: x9f0a1b2c3d4
Create Date: 2026-11-23

对标加快科技「知识库 → 图片上传 / 视频上传」的分组归档：
- 图片按分组展示（校区环境、资质证书、上课实拍…），组内可排序；
- 视频只存成片与标签，不做在线剪辑、不做数字员工；
- source 记录素材来源，仅用于筛选追溯。

material_category 落库是 VARCHAR + CHECK（str_enum 用 native_enum=False），
所以加 'video' 取值 = 重建 CHECK 约束，不需要 ALTER TYPE。
downgrade 会把约束退回三值，但已有 video 记录会随之违反约束，故 downgrade 先清空该列值。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "y9a8b7c6d5e4"
down_revision: Union[str, None] = "x9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = "ck_materials_material_category"
# 约束名由 metadata 命名约定生成（ck_<table>_<name>），用 op.* 会被再加一次前缀，
# 因此这里直接用原始 SQL，名字与库里现有约束严格一致。
DROP_CHECK = f"ALTER TABLE materials DROP CONSTRAINT IF EXISTS {CONSTRAINT}"
ADD_CHECK_4 = (
    f"ALTER TABLE materials ADD CONSTRAINT {CONSTRAINT} "
    "CHECK (category IN ('image', 'video', 'document', 'case'))"
)
ADD_CHECK_3 = (
    f"ALTER TABLE materials ADD CONSTRAINT {CONSTRAINT} "
    "CHECK (category IN ('image', 'document', 'case'))"
)


def upgrade() -> None:
    op.execute(DROP_CHECK)
    op.execute(ADD_CHECK_4)
    op.add_column(
        "materials", sa.Column("group_name", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "materials",
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "materials", sa.Column("source", sa.String(length=64), nullable=True)
    )
    op.create_index(
        "ix_materials_project_group",
        "materials",
        ["project_id", "group_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_materials_project_group", table_name="materials")
    op.drop_column("materials", "source")
    op.drop_column("materials", "sort_order")
    op.drop_column("materials", "group_name")
    op.execute("UPDATE materials SET category = 'document' WHERE category = 'video'")
    op.execute(DROP_CHECK)
    op.execute(ADD_CHECK_3)
