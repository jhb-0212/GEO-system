"""资质证书：增加证据图片字段（evidence_image_key / evidence_image_name）

Revision ID: v04e5f6a7b8c
Revises: u03d4e5f6a7b
Create Date: 2026-11-27

资质原来只有一个「证据链接」，现场拍照或扫描件没地方放。这一版把图片原件落到
evidence_root/certifications/{project_id}/，库里只存 storage_key 与原始文件名，
外链 evidence_url 仍然保留，两者可同时存在。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v04e5f6a7b8c"
down_revision: Union[str, None] = "u03d4e5f6a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("certifications", sa.Column("evidence_image_key", sa.String(length=255), nullable=True))
    op.add_column("certifications", sa.Column("evidence_image_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("certifications", "evidence_image_name")
    op.drop_column("certifications", "evidence_image_key")
