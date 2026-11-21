"""可复现地落库 6 个扩展 / 探测 API 入口。

范围：Kimi、千问、秘塔、智谱清言、讯飞星火、360 智脑。
原则：
- Kimi、千问、秘塔、360 已接入联网适配器；种子里标记 `supports_search=true`，
  但仍默认停用，等真实 Key 与 `test-connection` 通过后再由运营启用；
- 千问已切 Responses `web_search`，360 走 `/v1/search/aisearch` 的
  `references` 与正文角标；秘塔走 OpenAI 兼容 ChatCompletions 问答；
- 讯飞星火走星辰 MaaS Chat Completions，`supports_search=true` 时用
  `tools:[{"type":"web_search","web_search":{"enable":true}}]`，参数使用 `max_completion_tokens`；
- 智谱走两段式：先独立 `POST /api/paas/v4/web_search` 取来源，再用入口
  `model_name` 调 Chat Completions；入口不锁定模型，默认给免费模型，也可改成 FlashX；
- 不覆盖已有密钥密文；如入口已有 `encrypted_secret`，只更新地址、模型和备注；
- 可重复执行；已有目录占位入口时原地升级，不再新建重复入口。

用法（在 backend 目录）：
    .\\.venv\\Scripts\\python.exe scripts\\seed_platform_api_entries.py
    .\\.venv\\Scripts\\python.exe scripts\\seed_platform_api_entries.py --apply
    .\\.venv\\Scripts\\python.exe scripts\\seed_platform_api_entries.py --apply --json
    .\\.venv\\Scripts\\python.exe scripts\\seed_platform_api_entries.py --only-code nami_ai --apply
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
    supports_search: bool = False
    supports_citation: bool = False


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
            "已接 Kimi Responses `web_search`，支持联网与来源引用；"
            "默认停用，需配置 MOONSHOT_API_KEY 并完成真实联网探针后再启用。"
        ),
        supports_search=True,
        supports_citation=True,
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
            "已切 Responses `web_search`（`tools:[{\"type\":\"web_search\"}]`，"
            "从 `action.sources` 取网页来源）；默认停用，"
            "需配置 DASHSCOPE_API_KEY 并完成真实联网探针后再启用。"
        ),
        supports_search=True,
        supports_citation=True,
    ),
    ApiEntrySeed(
        code="metaso",
        engine_name="秘塔AI搜索",
        vendor="秘塔科技",
        entry_name="秘塔 API（ChatCompletions 问答）",
        entry_url="https://metaso.cn/api/v1",
        model_name="fast",
        credential_ref="METASO_API_KEY",
        note=(
            "官方 ChatCompletions 问答入口；模型本身联网，"
            "`choices[0].message.citations` 归一为带标题/链接/摘要/日期的引用；"
            "2026-11-20 真实调用返回 200 与引用，默认停用，完成系统 test-connection 后再启用。"
        ),
        supports_search=True,
        supports_citation=True,
    ),
    ApiEntrySeed(
        code="nami_ai",
        engine_name="360纳米AI",
        vendor="三六零",
        entry_name="360 智脑 API（AI搜索）",
        entry_url="https://api.360.cn/v1/search/aisearch",
        model_name="360gpt-pro",
        credential_ref="QIHU360_API_KEY",
        note=(
            "2026-11-20 按官方文档接入 `/v1/search/aisearch`："
            "`search_mode=required`、`enable_corner_markers=true`，"
            "从顶层 `references` 取标题/链接/摘要，正文角标作兜底；"
            "默认停用，需配置 QIHU360_API_KEY 并完成真实探针后再启用。"
        ),
        supports_search=True,
        supports_citation=True,
    ),
    ApiEntrySeed(
        code="zhipu",
        engine_name="智谱清言",
        vendor="智谱AI",
        entry_name="智谱 GLM API",
        entry_url="https://open.bigmodel.cn/api/paas/v4",
        model_name="glm-4-flash-250414",
        credential_ref="ZHIPU_API_KEY",
        note=(
            "2026-11-20 接入智谱两段式：先独立 `/web_search`（`search_engine=search_pro`）"
            "取结构化来源，再用入口 `model_name` 调 Chat Completions 作答；"
            "模型名不写死在代码里，可在入口改成 glm-5.3-flashx 或其他模型；"
            "默认停用，需配置 ZHIPU_API_KEY、搜索资源包/余额可用并完成真实联网探针后再启用。"
        ),
        supports_search=True,
        supports_citation=True,
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
            "2026-11-20 接入星辰 MaaS Chat Completions；"
            "supports_search=true 时请求体带 tools:[{type:web_search,web_search:{enable:true}}]，"
            "使用 max_completion_tokens，默认关闭 thinking；"
            "当前库无 Key，默认停用，需完成真实联网探针后再启用。"
        ),
        supports_search=True,
        supports_citation=False,
    ),
)


def _ensure_engine(session, seed: ApiEntrySeed) -> tuple[AiEngine, bool]:
    engine = session.scalar(select(AiEngine).where(AiEngine.code == seed.code))
    if engine is not None:
        # 能力按平台种子更新；是否参与采集仍由 is_active 单独控制。
        engine.supports_search = seed.supports_search
        engine.supports_citation = seed.supports_citation
        engine.is_active = False
        return engine, False

    engine = AiEngine(
        code=seed.code,
        name=seed.engine_name,
        vendor=seed.vendor,
        supports_search=seed.supports_search,
        supports_citation=seed.supports_citation,
        access_note="扩展 / 探测候选平台，默认停用；联网能力按平台配置。",
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


def seed_entries(
    session,
    *,
    apply: bool = False,
    codes: set[str] | None = None,
) -> dict:
    created_engines: list[str] = []
    upgraded_entries: list[str] = []
    created_entries: list[str] = []
    warnings: list[str] = []

    selected = [seed for seed in SEEDS if codes is None or seed.code in codes]
    for seed in selected:
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
        entry.supports_search = seed.supports_search
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
        "seed_total": len(selected),
        "created_engines": created_engines,
        "created_entries": created_entries,
        "upgraded_entries": upgraded_entries,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="落库 6 个扩展 / 探测 API 入口（默认 dry-run）")
    parser.add_argument("--apply", action="store_true", help="提交到数据库；不传则只预览并回滚")
    parser.add_argument(
        "--only-code",
        action="append",
        help="只处理指定 engine code，可重复；用于避免误改已启用平台",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()
    codes = set(args.only_code) if args.only_code else None

    with SessionLocal() as session:
        summary = seed_entries(session, apply=args.apply, codes=codes)
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
