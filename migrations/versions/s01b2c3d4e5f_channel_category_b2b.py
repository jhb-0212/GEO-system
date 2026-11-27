"""渠道分类新增 b2b（B2B 商贸/黄页平台）

Revision ID: s01b2c3d4e5f
Revises: r01a2b3c4d5e
Create Date: 2026-11-27

背景：渠道台账把「能自助发布供求/商讯的 B2B 黄页」并入内容平台或行业媒体都不准确——
前者按自媒体口径限制 2000 字，后者是编辑制媒体。分类独立后，渠道改编的篇幅上限
（content_derivation.CHANNEL_RULES）才能按 3000 字执行，且台账口径可区分。

本迁移只扩 category 的 CHECK 约束，不改列、不迁移数据；已含 b2b 的库直接跳过。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "s01b2c3d4e5f"
down_revision = "r01a2b3c4d5e"
branch_labels = None
depends_on = None

_OLD_VALUES = (
    "own_site",
    "content_platform",
    "video",
    "community",
    "encyclopedia",
    "local_media",
    "industry_media",
    "institution",
)
_NEW_VALUES = (
    "own_site",
    "content_platform",
    "video",
    "community",
    "encyclopedia",
    "local_media",
    "industry_media",
    "b2b",
    "institution",
)


def _condition(values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{value}'::character varying" for value in values)
    return f"(category)::text = ANY ((ARRAY[{joined}])::text[])"


def _category_constraints(bind) -> list[tuple[str, str]]:
    rows = bind.execute(
        sa.text(
            "SELECT conname, pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint "
            "WHERE conrelid = 'channels'::regclass AND contype = 'c' "
            "AND pg_get_constraintdef(oid) ILIKE '%category%'"
        )
    ).mappings()
    return [(row["conname"], row["definition"]) for row in rows]


def upgrade() -> None:
    bind = op.get_bind()
    found = _category_constraints(bind)
    if not found:
        raise RuntimeError("[channel_category] channels 上找不到 category 的 CHECK 约束，拒绝继续迁移")
    for conname, definition in found:
        if "'b2b'" in definition:
            print(f"[channel_category] {conname} 已包含 b2b，跳过")
            continue
        # 用原生 DDL 而不是 op.drop_constraint/create_check_constraint：
        # alembic 会按命名约定再给约束名加一层 "ck_" 前缀，把
        # ck_channels_channel_category 渲染成 ck_channels_ck_channels_channel_category。
        op.execute(f'ALTER TABLE channels DROP CONSTRAINT "{conname}"')
        op.execute(
            f'ALTER TABLE channels ADD CONSTRAINT "{conname}" CHECK ({_condition(_NEW_VALUES)})'
        )
        print(f"[channel_category] {conname} 已扩展到 b2b")


def downgrade() -> None:
    bind = op.get_bind()
    used = bind.execute(
        sa.text("SELECT count(*) FROM channels WHERE category = 'b2b'")
    ).scalar_one()
    if used:
        raise RuntimeError(
            f"[channel_category] 仍有 {used} 条渠道使用 b2b，先迁移数据再回滚分类"
        )
    for conname, definition in _category_constraints(bind):
        if "'b2b'" not in definition:
            continue
        op.execute(f'ALTER TABLE channels DROP CONSTRAINT "{conname}"')
        op.execute(
            f'ALTER TABLE channels ADD CONSTRAINT "{conname}" CHECK ({_condition(_OLD_VALUES)})'
        )
