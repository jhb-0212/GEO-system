"""Revision ID: g3d4e5f6a7b8
Revises: f2b3c4d5e6a7
Create Date: 2026-11-24

补种 neutral 通用预设：默认回退改为「中性且明确未选行业」，不再静默套用教育培训。
"""

import json
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "g3d4e5f6a7b8"
down_revision = "f2b3c4d5e6a7"
branch_labels = None
depends_on = None

SEED_DIR = Path(__file__).resolve().parents[2] / "seed_data" / "industry_presets"


def _upsert(code: str) -> None:
    payload = json.loads((SEED_DIR / f"{code}.json").read_text(encoding="utf-8"))
    op.get_bind().execute(
        sa.text(
            "INSERT INTO industry_presets (id, code, name, config) VALUES (:id, :code, :name, :config) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {
            "id": uuid.uuid4(),
            "code": payload["code"],
            "name": payload.get("name", payload["code"]),
            "config": json.dumps(payload, ensure_ascii=False),
        },
    )


def upgrade() -> None:
    _upsert("neutral")
    _upsert("edu-training")


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM industry_presets WHERE code = 'neutral'"))
