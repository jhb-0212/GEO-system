"""可复现地落库 4 个扩展 / 探测 API 入口。

范围：Kimi、千问、智谱清言、讯飞星火。
原则：
- 只登记 API 入口，不伪造联网能力；当前统一按普通 OpenAI-compatible 对话处理，
  `supports_search=false`，不参与 24 格基线；
- 默认停用；拿到 Key 后逐个 `test-connection`，通过后再由运营决定是否启用；
- 不覆盖已有密钥密文；如入口已有 `encrypted_secret`，只更新地址、模型和备注；
- 可重复执行；已有目录占位入口时原地升级，不再新建重复入口。

用法（在 backend 目录）：
    .\\.venv\\Scripts\\python.exe scripts\\seed_platform_api_entries.py
    .\\.venv\\Scripts\\python.exe scripts\\seed_platform_api_entries.py --apply
    .\\.venv\\Scripts\\python.exe scripts\\seed_platform_api_entries.py --apply --json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models import AiEngine, AiEngineEntry  # noqa: E402
from app.models.enums import EngineEntryType, EngineProtocol  # noqa: E402


@dataclass(frozen=True)
class ApiEntrySeed:
    code: str
    engine_name: str
    vendor: str
    entry_name: str
    entry_url: str
    model_name: str
    credential_ref: str
    note: str


SEEDS: tuple[ApiEntrySeed, ...] = (
    ApiEntrySeed(
        code="kimi",
        engine_name="Kimi",
        vendor="月之暗面",
        entry_name="Kimi 官方 API",
        entry_url="https://api.moonshot.cn/v1",
        model_name="kimi-k3",
        credential_ref="MOONSHOT_API_KEY",
        note=(
            "2026-11-18 文档记录 test-connection 通过（当前库未复核）；"
            "当前适配器仅普通对话，不联网、无引用；默认停用，不参与 24 格。"
        ),
    ),
    ApiEntrySeed(
        code="qianwen",
        engine_name="千问",
        vendor="阿里云",
        entry_name="千问 百炼 API",
        entry_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3.8-max",
        credential_ref="DASHSCOPE_API_KEY",
        note=(
            "2026-11-18 文档记录 test-connection 通过（当前库未复核）；"
            "千问联网需 enable_search，当前适配器未适配；默认停用，不参与 24 格。"
        ),
    ),
    ApiEntrySeed(
        code="zhipu",
        engine_name="智谱清言",
        vendor="智谱AI",
        entry_name="智谱 GLM API",
        entry_url="https://open.bigmodel.cn/api/paas/v4",
        model_name="glm-4-flash",
        credential_ref="ZHIPU_API_KEY",
        note=(
            "2026-11-18 文档记录 test-connection 通过（当前库未复核）；"
            "智谱联网需 tools:[{type:web_search}]，当前适配器未适配；默认停用，不参与 24 格。"
        ),
    ),
    ApiEntrySeed(
        code="spark",
        engine_name="讯飞星火",
        vendor="科大讯飞",
        entry_name="讯飞星火 HTTP",
        entry_url="https://maas-api.cn-huabei-1.xf-yun.com/v2",
        model_name="spark-x2.6",
        credential_ref="SPARK_API_KEY",
        note=(
            "2026-11-18 文档记录 test-connection 通过（当前库未复核，首包偏慢）；"
            "当前适配器仅普通对话，不联网、无引用；默认停用，不参与 24 格。"
        ),
    ),
)


def _ensure_engine(session, seed: ApiEntrySeed) -> tuple[AiEngine, bool]:
    engine = session.scalar(select(AiEngine).where(AiEngine.code == seed.code))
    if engine is not None:
        # 候选平台不进入基线；即使历史记录里被启用过，也回到停用。
        engine.supports_search = False
        engine.supports_citation = False
        engine.is_active = False
        return engine, False

    engine = AiEngine(
        code=seed.code,
        name=seed.engine_name,
        vendor=seed.vendor,
        supports_search=False,
        supports_citation=False,
        access_note="扩展 / 探测候选平台，默认停用；不参与 24 格。",
        is_active=False,
    )
    session.add(engine)
    session.flush()
    return engine, True


def _find_api_entry(session, engine: AiEngine, seed: ApiEntrySeed) -> tuple[AiEngineEntry | None, str]:
    """优先复用同名入口；否则复用该平台下唯一的目录占位 API 入口。"""
    exact = session.scalar(
        select(AiEngineEntry).where(
            AiEngineEntry.engine_id == engine.id,
            AiEngineEntry.entry_type == EngineEntryType.API,
            AiEngineEntry.name == seed.entry_name,
        )
    )
    if exact is not None:
        return exact, "exact"

    entries = session.scalars(
        select(AiEngineEntry)
        .where(
            AiEngineEntry.engine_id == engine.id,
            AiEngineEntry.entry_type == EngineEntryType.API,
        )
        .order_by(AiEngineEntry.created_at, AiEngineEntry.id)
    ).all()
    if len(entries) == 1:
        return entries[0], "placeholder"

    for entry in entries:
        protocol = getattr(entry.protocol, "value", str(entry.protocol))
        if protocol == EngineProtocol.CUSTOM.value and "待核验" in entry.name:
            return entry, "placeholder"
    return None, "new"


def seed_entries(session, *, apply: bool = False) -> dict:
    created_engines: list[str] = []
    upgraded_entries: list[str] = []
    created_entries: list[str] = []
    warnings: list[str] = []

    for seed in SEEDS:
        engine, engine_created = _ensure_engine(session, seed)
        if engine_created:
            created_engines.append(seed.code)

        entry, match = _find_api_entry(session, engine, seed)
        if entry is None:
            entry = AiEngineEntry(
                engine_id=engine.id,
                entry_type=EngineEntryType.API,
                name=seed.entry_name,
            )
            session.add(entry)
            created_entries.append(f"{seed.code}:api")
        else:
            upgraded_entries.append(f"{seed.code}:api:{match}")

        # 只改目录与协议字段，绝不覆盖 encrypted_secret / encrypted_secret_secondary。
        entry.entry_type = EngineEntryType.API
        entry.name = seed.entry_name
        entry.entry_url = seed.entry_url
        entry.protocol = EngineProtocol.OPENAI_COMPATIBLE
        entry.model_name = seed.model_name
        entry.credential_ref = seed.credential_ref
        entry.supports_search = False
        entry.access_note = seed.note
        entry.is_active = False

        if entry.encrypted_secret:
            warnings.append(f"{seed.code}: 已保留系统内已填写的密钥密文")

    if apply:
        session.commit()
    else:
        session.rollback()

    return {
        "apply": apply,
        "seed_total": len(SEEDS),
        "created_engines": created_engines,
        "created_entries": created_entries,
        "upgraded_entries": upgraded_entries,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="落库 4 个扩展 / 探测 API 入口（默认 dry-run）")
    parser.add_argument("--apply", action="store_true", help="提交到数据库；不传则只预览并回滚")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    with SessionLocal() as session:
        summary = seed_entries(session, apply=args.apply)
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(
                f"apply={summary['apply']} seed={summary['seed_total']} "
                f"engines+{len(summary['created_engines'])} "
                f"entries+{len(summary['created_entries'])} "
                f"upgraded={len(summary['upgraded_entries'])} "
                f"warnings={len(summary['warnings'])}"
            )
            for item in summary["warnings"]:
                print(f"  WARN {item}")


if __name__ == "__main__":
    main()
