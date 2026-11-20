r"""国内监测入口目录：首轮 4 个 + 扩展 6 个 + 探测 5 个。

只写目录和入口配置，不伪造协议适配：
- 首轮 4 个沿用现有入口，保持 active；文心入口是千帆 ERNIE 对话模型
  （`openai_compatible`），不是千帆 AI 搜索检索产品；
- 扩展/探测 11 个新建为 inactive 候选，入口也 inactive；
- 候选不参与 `generate_tasks`，24 格基线仍是 4×6；
- 官方入口、联网能力、来源可见性、访问限制、最近核验日期由运营核验后补。

用法（在 backend 目录）：
    .\.venv\Scripts\python.exe scripts\seed_platform_catalog.py --apply
    .\.venv\Scripts\python.exe scripts\seed_platform_catalog.py --json
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
class CatalogEntry:
    code: str
    name: str
    vendor: str
    batch: str
    entry_type: EngineEntryType
    entry_name: str
    note: str
    protocol: EngineProtocol = EngineProtocol.CUSTOM
    entry_url: str | None = None
    model_name: str | None = None
    supports_search: bool = True


CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        "doubao",
        "豆包",
        "字节跳动",
        "首轮 4 个",
        EngineEntryType.WEB_USER,
        "豆包网页端",
        "首轮主入口；网页端与应用端需分别核验；支持联网搜索",
    ),
    CatalogEntry(
        "yuanbao",
        "腾讯元宝",
        "腾讯",
        "首轮 4 个",
        EngineEntryType.WEB_USER,
        "腾讯元宝网页端",
        "首轮主入口；微信/网页入口需分别核验；支持联网搜索",
    ),
    CatalogEntry(
        "deepseek",
        "DeepSeek",
        "深度求索",
        "首轮 4 个",
        EngineEntryType.WEB_USER,
        "DeepSeek网页端",
        "首轮主入口；网页端与官方 API 分别采样",
    ),
    CatalogEntry(
        "wenxin",
        "百度文心",
        "百度",
        "首轮 4 个",
        EngineEntryType.API,
        "文心一言 ERNIE 5.1（千帆对话模型）",
        "首轮主入口；千帆 ModelBuilder 对话模型（ERNIE 5.1），不是千帆 AI 搜索检索产品；"
        "请求体 web_search:{enable:true} 开启联网，返回生成回答",
        protocol=EngineProtocol.OPENAI_COMPATIBLE,
        entry_url="https://qianfan.baidubce.com/v2",
        model_name="ernie-5.1",
        supports_search=True,
    ),
    CatalogEntry(
        "kimi",
        "Kimi",
        "月之暗面",
        "扩展 6 个",
        EngineEntryType.API,
        "Kimi API 入口（待核验）",
        "扩展候选；官方入口、联网、来源可见性、访问限制、最近核验待补；未接协议，默认停用",
    ),
    CatalogEntry(
        "qianwen",
        "千问",
        "阿里云",
        "扩展 6 个",
        EngineEntryType.API,
        "千问 API 入口（待核验）",
        "扩展候选；官方入口、联网、来源可见性、访问限制、最近核验待补；未接协议，默认停用",
    ),
    CatalogEntry(
        "quark",
        "夸克",
        "阿里",
        "扩展 6 个",
        EngineEntryType.APP_SEARCH,
        "夸克应用内搜索入口（待核验）",
        "扩展候选；按客户端实测入口和来源展示；未接协议，默认停用",
    ),
    CatalogEntry(
        "metaso",
        "秘塔AI搜索",
        "秘塔科技",
        "扩展 6 个",
        EngineEntryType.APP_SEARCH,
        "秘塔AI搜索应用内入口（待核验）",
        "扩展候选；按客户端实测入口和来源展示；未接协议，默认停用",
    ),
    CatalogEntry(
        "baidu_ai_search",
        "百度AI搜",
        "百度",
        "扩展 6 个",
        EngineEntryType.APP_SEARCH,
        "百度AI搜应用内入口（待核验）",
        "扩展候选；与百度文心分开记录；按客户端实测入口和来源展示；未接协议，默认停用",
    ),
    CatalogEntry(
        "nami_ai",
        "360纳米AI",
        "三六零",
        "扩展 6 个",
        EngineEntryType.APP_SEARCH,
        "360纳米AI应用内入口（待核验）",
        "扩展候选；按客户端实测入口和来源展示；未接协议，默认停用",
    ),
    CatalogEntry(
        "zhipu",
        "智谱清言",
        "智谱AI",
        "探测 5 个",
        EngineEntryType.API,
        "智谱清言 API 入口（待核验）",
        "探测候选；官方入口、联网、来源可见性、访问限制、最近核验待补；未接协议，默认停用",
    ),
    CatalogEntry(
        "spark",
        "讯飞星火",
        "科大讯飞",
        "探测 5 个",
        EngineEntryType.API,
        "讯飞星火 API 入口（待核验）",
        "探测候选；官方入口、联网、来源可见性、访问限制、最近核验待补；未接协议，默认停用",
    ),
    CatalogEntry(
        "wechat_search_ai",
        "微信搜一搜AI",
        "腾讯",
        "探测 5 个",
        EngineEntryType.APP_SEARCH,
        "微信搜一搜AI应用内入口（待核验）",
        "探测候选；与腾讯元宝分开记录；按客户端实测入口和来源展示；未接协议，默认停用",
    ),
    CatalogEntry(
        "zhihu_direct",
        "知乎直答",
        "知乎",
        "探测 5 个",
        EngineEntryType.APP_SEARCH,
        "知乎直答应用内入口（待核验）",
        "探测候选；按客户端实测入口和来源展示；未接协议，默认停用",
    ),
    CatalogEntry(
        "xiaohongshu_diandian",
        "小红书点点",
        "小红书",
        "探测 5 个",
        EngineEntryType.APP_SEARCH,
        "小红书点点应用内入口（待核验）",
        "探测候选；按客户端实测入口和来源展示；未接协议，默认停用",
    ),
)


def _describe_index() -> dict[str, dict[str, int]]:
    result = {"首轮 4 个": 0, "扩展 6 个": 0, "探测 5 个": 0}
    for item in CATALOG:
        result[item.batch] += 1
    return result


def seed_catalog(session, *, apply: bool = False) -> dict:
    created_engines: list[str] = []
    created_entries: list[str] = []
    existing: list[str] = []
    warnings: list[str] = []

    for item in CATALOG:
        engine = session.scalar(select(AiEngine).where(AiEngine.code == item.code))
        if engine is None:
            engine = AiEngine(
                code=item.code,
                name=item.name,
                vendor=item.vendor,
                supports_search=True,
                supports_citation=True,
                access_note=item.note,
                is_active=False,
            )
            session.add(engine)
            session.flush()
            created_engines.append(item.code)
        else:
            existing.append(item.code)
            if engine.is_active and item.batch != "首轮 4 个":
                warnings.append(f"{item.code} 已是 active，未自动改动；请人工确认是否应纳入基线")

        entry = session.scalar(
            select(AiEngineEntry).where(
                AiEngineEntry.engine_id == engine.id,
                AiEngineEntry.entry_type == item.entry_type,
                AiEngineEntry.name == item.entry_name,
            )
        )
        if entry is None:
            # 平台可能已有同名以外的同类型入口（例如运营把“豆包网页端”
            # 命名为“豆包网页版（人工）”，或 API 候选已由
            # seed_platform_api_entries.py 升级为 openai_compatible）。
            # 目录脚本只补缺，不因名称差异再塞一条重复入口。
            existing_same_type = session.scalar(
                select(AiEngineEntry)
                .where(
                    AiEngineEntry.engine_id == engine.id,
                    AiEngineEntry.entry_type == item.entry_type,
                )
                .order_by(AiEngineEntry.created_at, AiEngineEntry.id)
            )
            if existing_same_type is not None:
                warnings.append(
                    f"{item.code} 已有 {item.entry_type.value} 入口 {existing_same_type.name}，跳过目录占位"
                )
                continue

        if entry is None:
            entry = AiEngineEntry(
                engine_id=engine.id,
                entry_type=item.entry_type,
                name=item.entry_name,
                protocol=item.protocol,
                entry_url=item.entry_url,
                model_name=item.model_name,
                supports_search=item.supports_search,
                access_note=item.note,
                is_active=False,
            )
            session.add(entry)
            created_entries.append(f"{item.code}:{item.entry_type.value}")

    if apply:
        session.commit()
    else:
        session.rollback()

    return {
        "apply": apply,
        "catalog_total": len(CATALOG),
        "by_batch": _describe_index(),
        "created_engines": created_engines,
        "created_entries": created_entries,
        "existing": existing,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写库；默认只演练并回滚")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    with SessionLocal() as session:
        result = seed_catalog(session, apply=args.apply)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"catalog={result['catalog_total']} "
            f"created_engines={len(result['created_engines'])} "
            f"created_entries={len(result['created_entries'])} "
            f"existing={len(result['existing'])} "
            f"apply={result['apply']}"
        )
        if result["warnings"]:
            print("warnings:", "; ".join(result["warnings"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
