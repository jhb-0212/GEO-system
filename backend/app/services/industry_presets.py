"""行业预设与项目策略：把行业语义从代码里搬到配置。

三层：
- 预设（`industry_presets`）：一个行业怎么读术语、怎么判风险，例如教育培训；
- 项目策略（`project_strategies`）：某项目在预设之上的差异，例如自己的基线题目；
- 代码只保留与行业无关的算法（如何匹配、如何打分、如何排序）。

预设 JSON 放在 `seed_data/industry_presets/`，随迁移落库；服务默认读当前项目策略，
缺策略时回退到该项目绑定的预设，再缺就回退到内置 `edu-training`（迁移前的存量行为）。
"""

from __future__ import annotations

import copy
import json
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.industry import IndustryPreset, ProjectStrategy

PRESET_DIR = Path(__file__).resolve().parents[3] / "seed_data" / "industry_presets"
DEFAULT_PRESET_CODE = "edu-training"


def _deep_merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=16)
def load_preset_file(code: str = DEFAULT_PRESET_CODE) -> dict:
    path = PRESET_DIR / f"{code}.json"
    if not path.exists():
        raise FileNotFoundError(f"行业预设不存在：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def preset_config(code: str = DEFAULT_PRESET_CODE) -> dict:
    return copy.deepcopy(load_preset_file(code))


def dot_get(config: dict, dotted: str, default: Any = None) -> Any:
    node: Any = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def project_industry_config(db: Session, project_id: uuid.UUID) -> dict:
    """项目生效的行业配置：预设 + 该项目策略覆盖。"""
    row = db.scalar(
        select(ProjectStrategy)
        .where(
            ProjectStrategy.project_id == project_id,
            ProjectStrategy.strategy_key == "industry",
            ProjectStrategy.status == "active",
        )
        .order_by(ProjectStrategy.version.desc())
    )
    preset_code = DEFAULT_PRESET_CODE
    if row is not None and isinstance(row.config, dict):
        preset_code = str(row.config.get("preset_code") or DEFAULT_PRESET_CODE)
    base = preset_config(preset_code)
    if row is None:
        return base
    overrides = row.config.get("overrides") if isinstance(row.config, dict) else None
    return _deep_merge(base, overrides or {})


def project_terms(db: Session, project_id: uuid.UUID, dotted: str, default: Any = None) -> Any:
    return dot_get(project_industry_config(db, project_id), dotted, default)


def default_terms(dotted: str, default: Any = None) -> Any:
    """没有 db 上下文时的预设值（存量行为）。"""
    return dot_get(preset_config(DEFAULT_PRESET_CODE), dotted, default)


def upsert_strategy(
    db: Session,
    project_id: uuid.UUID,
    *,
    strategy_key: str = "industry",
    preset_code: str = DEFAULT_PRESET_CODE,
    overrides: dict | None = None,
    note: str | None = None,
) -> ProjectStrategy:
    existing = db.scalar(
        select(ProjectStrategy)
        .where(ProjectStrategy.project_id == project_id, ProjectStrategy.strategy_key == strategy_key)
        .order_by(ProjectStrategy.version.desc())
    )
    version = (existing.version + 1) if existing else 1
    row = ProjectStrategy(
        project_id=project_id,
        strategy_key=strategy_key,
        config={"preset_code": preset_code, "overrides": overrides or {}},
        version=version,
        status="active",
        note=note,
    )
    db.add(row)
    return row


def seed_preset(db: Session, code: str = DEFAULT_PRESET_CODE) -> IndustryPreset:
    payload = load_preset_file(code)
    row = db.scalar(select(IndustryPreset).where(IndustryPreset.code == code))
    if row is None:
        row = IndustryPreset(code=code, name=payload.get("name", code), config=payload)
        db.add(row)
    return row


def default_organization(db: Session):
    """存量行为兜底：没有指定客户时挂到默认客户，避免新建项目因缺 org 失败。"""
    from app.models.industry import Organization

    row = db.scalar(select(Organization).where(Organization.code == "default-client"))
    if row is None:
        row = Organization(code="default-client", name="默认客户", status="active", branding={})
        db.add(row)
        db.flush()
    return row
