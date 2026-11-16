"""登记 / 启用 DeepSeek 网页版联网搜索入口（系统级配置，不走运营页面）。

背景：批量任务每个引擎只取「一个有效入口」（`_active_engine_entries` 按 created_at 取首个），
所以同一个 DeepSeek 引擎下 API 入口与网页版入口不能同时 active，否则采集仍会走到 API 入口。
本脚本默认只建入口、不切换；要真正用网页版采集，需显式 `--activate-websearch`。

用法：
    # 演练（不写库）
    ./.venv/Scripts/python.exe scripts/register_deepseek_websearch.py
    # 写库：建/更新入口，但保持现有 active 状态
    ./.venv/Scripts/python.exe scripts/register_deepseek_websearch.py --apply
    # 写库并切换：启用网页版入口、停用同引擎其它入口
    ./.venv/Scripts/python.exe scripts/register_deepseek_websearch.py --apply --activate-websearch

切回官方 API 采集：`--apply --activate-api`（停用网页版入口、恢复 API 入口）。
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import AiEngine, AiEngineEntry
from app.models.enums import EngineEntryType, EngineProtocol

ENGINE_CODE = "deepseek"
ENTRY_NAME = "DeepSeek 网页版智能搜索"
BRIDGE_URL = "http://127.0.0.1:8099"
MODEL_NAME = "deepseek-websearch"
ACCESS_NOTE = (
    "网页版智能搜索采集（含引用来源）；官方 API 无联网搜索。"
    "口径：DeepSeek 检索行为 + 生成回答，不与 API 入口的『回答提及』混算。"
)


def _upsert_entry(session) -> tuple[AiEngineEntry, str]:
    engine = session.scalar(select(AiEngine).where(AiEngine.code == ENGINE_CODE))
    if engine is None:
        raise SystemExit(f"库里没有引擎 {ENGINE_CODE}，先跑 seed.py")
    entry = session.scalar(
        select(AiEngineEntry).where(
            AiEngineEntry.engine_id == engine.id,
            AiEngineEntry.entry_type == EngineEntryType.WEB_USER,
            AiEngineEntry.name == ENTRY_NAME,
        )
    )
    action = "created"
    if entry is None:
        entry = AiEngineEntry(
            engine_id=engine.id,
            entry_type=EngineEntryType.WEB_USER,
            name=ENTRY_NAME,
            protocol=EngineProtocol.DEEPSEEK_WEBSEARCH,
            entry_url=BRIDGE_URL,
            model_name=MODEL_NAME,
            credential_ref=None,
            supports_search=True,
            supports_citation=True,
            access_note=ACCESS_NOTE,
            is_active=False,
        )
        session.add(entry)
        session.flush()
    else:
        action = "updated"
        entry.protocol = EngineProtocol.DEEPSEEK_WEBSEARCH
        entry.entry_url = entry.entry_url or BRIDGE_URL
        entry.model_name = entry.model_name or MODEL_NAME
        entry.supports_search = True
        entry.supports_citation = True
        entry.access_note = entry.access_note or ACCESS_NOTE
    return entry, action


def _entry_summary(entry: AiEngineEntry) -> dict:
    return {
        "id": str(entry.id),
        "name": entry.name,
        "entry_type": getattr(entry.entry_type, "value", str(entry.entry_type)),
        "protocol": getattr(entry.protocol, "value", str(entry.protocol)),
        "entry_url": entry.entry_url,
        "is_active": entry.is_active,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写库；默认只演练并回滚")
    parser.add_argument(
        "--activate-websearch",
        action="store_true",
        help="启用网页版入口并停用同引擎其它入口（采集切到网页版口径）",
    )
    parser.add_argument(
        "--activate-api",
        action="store_true",
        help="停用网页版入口并恢复同引擎 API 入口（采集切回回答提及口径）",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.activate_websearch and args.activate_api:
        raise SystemExit("--activate-websearch 与 --activate-api 不能同时使用")

    with SessionLocal() as session:
        entry, action = _upsert_entry(session)
        engine = session.scalar(select(AiEngine).where(AiEngine.code == ENGINE_CODE))
        siblings = session.scalars(
            select(AiEngineEntry).where(AiEngineEntry.engine_id == engine.id)
        ).all()

        if args.activate_websearch:
            for row in siblings:
                row.is_active = row.id == entry.id
            entry.last_verified_at = None
        elif args.activate_api:
            for row in siblings:
                if row.id == entry.id:
                    row.is_active = False
                elif getattr(row.protocol, "value", str(row.protocol)) == "openai_compatible":
                    row.is_active = True

        result = {
            "apply": args.apply,
            "entry_action": action,
            "entry": _entry_summary(entry),
            "siblings": [_entry_summary(row) for row in siblings],
            "note": (
                "同一引擎只取一个有效入口；两个都 active 时按 created_at 取最早的那个"
            ),
        }
        if args.apply:
            session.commit()
        else:
            session.rollback()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
