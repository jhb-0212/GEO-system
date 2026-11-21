"""验证 6 个扩展 API 入口种子可重复执行、默认停用、不会重复建入口。"""

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
        assert engine.supports_search is seed.supports_search
        assert engine.supports_citation is seed.supports_citation

        entries = db.scalars(
            select(AiEngineEntry).where(
                AiEngineEntry.engine_id == engine.id,
                AiEngineEntry.entry_type == EngineEntryType.API,
            )
        ).all()
        # 同一平台允许按模型拆多条入口；这里只校验种子入口本身不重复。
        seeded = [entry for entry in entries if entry.name == seed.entry_name]
        assert len(seeded) == 1
        entry = seeded[0]
        assert entry.name == seed.entry_name
        assert entry.protocol == EngineProtocol.OPENAI_COMPATIBLE
        assert entry.entry_url == seed.entry_url
        assert entry.model_name == seed.model_name
        assert entry.credential_ref == seed.credential_ref
        assert entry.supports_search is seed.supports_search
        assert entry.is_active is False
        assert entry.access_note == seed.note

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
        seeded = [entry for entry in entries if entry.name == seed.entry_name]
        assert len(seeded) == 1


def test_seed_platform_api_entries_only_code(db):
    """--only-code 只补指定平台，避免误把已启用平台重置为停用。"""
    summary = seed_entries(db, apply=True, codes={"nami_ai"})
    assert summary["seed_total"] == 1

    engine = db.scalar(select(AiEngine).where(AiEngine.code == "nami_ai"))
    assert engine is not None
    entry = db.scalar(
        select(AiEngineEntry).where(
            AiEngineEntry.engine_id == engine.id,
            AiEngineEntry.entry_type == EngineEntryType.API,
        )
    )
    assert entry is not None
    assert entry.entry_url == "https://api.360.cn/v1/search/aisearch"
    assert entry.is_active is False


def test_catalog_seed_skips_existing_extra_api_entries(db):
    seed_entries(db, apply=True)
    result = seed_catalog(db, apply=False)
    created = set(result["created_entries"])
    for code in ("kimi", "qianwen", "metaso", "nami_ai", "zhipu", "spark"):
        assert f"{code}:api" not in created
