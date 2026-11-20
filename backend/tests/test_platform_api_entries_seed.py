"""验证 4 个扩展 API 入口种子可重复执行、默认停用、不会重复建入口。"""

from sqlalchemy import select

from app.models import AiEngine, AiEngineEntry
from app.models.enums import EngineEntryType, EngineProtocol
from scripts.seed_platform_api_entries import SEEDS, seed_entries
from scripts.seed_platform_catalog import seed_catalog


def test_seed_platform_api_entries_is_idempotent(db):
    seed_entries(db, apply=True)

    for seed in SEEDS:
        engine = db.scalar(select(AiEngine).where(AiEngine.code == seed.code))
        assert engine is not None
        assert engine.is_active is False
        assert engine.supports_search is False
        assert engine.supports_citation is False

        entries = db.scalars(
            select(AiEngineEntry).where(
                AiEngineEntry.engine_id == engine.id,
                AiEngineEntry.entry_type == EngineEntryType.API,
            )
        ).all()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.name == seed.entry_name
        assert entry.protocol == EngineProtocol.OPENAI_COMPATIBLE
        assert entry.entry_url == seed.entry_url
        assert entry.model_name == seed.model_name
        assert entry.credential_ref == seed.credential_ref
        assert entry.supports_search is False
        assert entry.is_active is False

    second = seed_entries(db, apply=True)
    assert second["created_engines"] == []
    assert second["created_entries"] == []

    for seed in SEEDS:
        engine = db.scalar(select(AiEngine).where(AiEngine.code == seed.code))
        entries = db.scalars(
            select(AiEngineEntry).where(
                AiEngineEntry.engine_id == engine.id,
                AiEngineEntry.entry_type == EngineEntryType.API,
            )
        ).all()
        assert len(entries) == 1


def test_catalog_seed_skips_existing_extra_api_entries(db):
    seed_entries(db, apply=True)
    result = seed_catalog(db, apply=False)
    created = set(result["created_entries"])
    for code in ("kimi", "qianwen", "zhipu", "spark"):
        assert f"{code}:api" not in created
