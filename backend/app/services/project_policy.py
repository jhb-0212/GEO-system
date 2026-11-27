"""通用口径配置：默认值面向任意项目，`project_policies` 做项目级覆盖。

键位约定（`模块.参数`）：
- `freshness.window_months`：内容新鲜度窗口月数（默认 18）
- `contract.target_streak`：验收契约连续采集目标天数（默认 30）
- `sentiment.min_report`：情感共识出率的最低条数（默认 50）
- `quality.number_level`：结果性数字无来源时的级别（warn / block，默认 warn）
- `quality.quote_level`：引语无出处时的级别（warn / block，默认 warn）
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project_policy import ProjectPolicy

DEFAULTS: dict[str, Any] = {
    "freshness.window_months": 18,
    "contract.target_streak": 30,
    "sentiment.min_report": 50,
    "quality.number_level": "warn",
    "quality.quote_level": "warn",
    "adaptation.four_questions": {},
}

LEVELS = {"warn", "block"}


def _validate(key: str, value: Any) -> Any:
    if key not in DEFAULTS:
        raise ValueError(f"未知口径键：{key}")
    default = DEFAULTS[key]
    if isinstance(default, int) and not isinstance(default, bool):
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"{key} 必须是正整数")
        return value
    if key in {"quality.number_level", "quality.quote_level"}:
        if value not in LEVELS:
            raise ValueError(f"{key} 只能是 warn / block")
        return value
    if isinstance(default, list):
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise ValueError(f"{key} 必须是非空字符串数组")
        return value
    return value


def effective_policies(db: Session, project_id: uuid.UUID) -> dict[str, Any]:
    merged = {key: value for key, value in DEFAULTS.items()}
    for row in db.scalars(select(ProjectPolicy).where(ProjectPolicy.project_id == project_id)):
        if row.key in DEFAULTS:
            merged[row.key] = row.value.get("v", DEFAULTS[row.key]) if isinstance(row.value, dict) else row.value
    return merged


def policy_value(db: Session, project_id: uuid.UUID, key: str) -> Any:
    row = db.scalar(
        select(ProjectPolicy).where(ProjectPolicy.project_id == project_id, ProjectPolicy.key == key)
    )
    if row is None:
        return DEFAULTS[key]
    if isinstance(row.value, dict):
        return row.value.get("v", DEFAULTS[key])
    return row.value


def set_policies(
    db: Session,
    project_id: uuid.UUID,
    updates: dict[str, Any],
    *,
    notes: dict[str, str] | None = None,
    actor_id: uuid.UUID | None = None,
    apply: bool = True,
) -> dict:
    """按项目写口径覆盖；`value` 为空表示删除该覆盖、回默认。"""
    notes = notes or {}
    applied: list[dict] = []
    for key, raw in updates.items():
        if key not in DEFAULTS:
            applied.append({"key": key, "status": "invalid", "detail": "未知口径键"})
            continue
        existing = db.scalar(
            select(ProjectPolicy).where(ProjectPolicy.project_id == project_id, ProjectPolicy.key == key)
        )
        if raw is None:
            if apply and existing is not None:
                db.delete(existing)
            applied.append({"key": key, "status": "reset", "value": DEFAULTS[key]})
            continue
        try:
            value = _validate(key, raw)
        except ValueError as exc:
            applied.append({"key": key, "status": "invalid", "detail": str(exc)})
            continue
        if apply:
            if existing is None:
                existing = ProjectPolicy(project_id=project_id, key=key, value={"v": value},
                                         note=notes.get(key), updated_by=actor_id)
                db.add(existing)
            else:
                existing.value = {"v": value}
                existing.note = notes.get(key)
                existing.updated_by = actor_id
        applied.append({"key": key, "status": "applied", "value": value})
    if apply:
        db.commit()
    return {
        "apply": apply,
        "changed": sum(1 for item in applied if item["status"] in {"applied", "reset"}),
        "decisions": applied,
        "effective": effective_policies(db, project_id),
        "defaults": DEFAULTS,
    }
