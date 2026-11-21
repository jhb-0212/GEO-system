r"""国内监测入口目录：首轮 4 个 + 扩展 6 个 + 探测 5 个。

只写目录和入口配置，不伪造协议适配：
- 首轮 4 个沿用现有入口，保持 active；文心入口是千帆 ERNIE 对话模型
  （`openai_compatible`），不是千帆 AI 搜索检索产品；
- 扩展/探测 11 个新建为 inactive 候选，入口也 inactive；
- 候选不参与 `generate_tasks`，24 格基线仍是 4×6；
- 官方入口、访问备注已写入；最近核验日期需现场人工确认，不能由种子伪造。

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
        "夸克应用内搜索入口",
        "官方入口：https://www.quark.cn/s（网页 AI 搜索）；App 内首页「问 AI」/搜索框。"
        "网页端可直接提问，App 需登录夸克账号。回答为 AI 总结，来源以结果页引用与网页列表为准。"
        "纯应用内检索，人工采样，不自动采集；启用前需人工核验。",
        entry_url="https://www.quark.cn/s",
    ),
    CatalogEntry(
        "metaso",
        "秘塔AI搜索",
        "秘塔科技",
        "扩展 6 个",
        EngineEntryType.APP_SEARCH,
        "秘塔AI搜索应用内入口",
        "官方入口：https://metaso.cn/（网页/客户端）；基础检索可直接打开，保存历史与深度研究需登录。"
        "回答带来源编号与链接。纯应用内检索，人工采样，不自动采集；启用前需人工核验。",
        entry_url="https://metaso.cn/",
    ),
    CatalogEntry(
        "baidu_ai_search",
        "百度AI搜",
        "百度",
        "扩展 6 个",
        EngineEntryType.APP_SEARCH,
        "百度AI搜应用内入口",
        "官方入口：https://chat.baidu.com/（现跳转文心 chat_site）；也可从百度 App 的 AI 搜索入口进入。"
        "支持百度账号登录，部分基础问答可匿名。回答下方展示参考来源；与文心一言 API 分开记录。"
        "纯应用内检索，人工采样，不自动采集；启用前需人工核验。",
        entry_url="https://chat.baidu.com/",
    ),
    CatalogEntry(
        "nami_ai",
        "360纳米AI",
        "三六零",
        "扩展 6 个",
        EngineEntryType.APP_SEARCH,
        "360纳米AI应用内入口",
        "官方入口：https://www.n.cn/（现跳转 work.n.cn / 纳米work）；客户端下载见 https://bot.n.cn/downloads。"
        "App/桌面端需登录 360 账号；支持联网搜索和多模型，来源以回答引用/网页列表为准。"
        "纯应用内检索，人工采样，不自动采集；启用前需人工核验。",
        entry_url="https://www.n.cn/",
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
        "微信搜一搜AI应用内入口",
        "应用内路径：微信 App → 发现 → 搜一搜 → 输入问题 → AI 搜索；官方产品说明 https://search.weixin.qq.com/。"
        "需登录微信，AI 搜索入口按账号/版本灰度开放。回答融合公众号、视频号与全网信息，参考资料可展开。"
        "纯应用内检索，人工采样，不自动采集；启用前需人工核验。",
        entry_url="https://search.weixin.qq.com/",
    ),
    CatalogEntry(
        "zhihu_direct",
        "知乎直答",
        "知乎",
        "探测 5 个",
        EngineEntryType.APP_SEARCH,
        "知乎直答应用内入口",
        "官方入口：https://zhida.zhihu.com/（网页/知乎 App 直答）。需登录知乎账号；"
        "支持简略、深入、专业搜索，回答带知乎内容与外部来源。纯应用内检索，人工采样，不自动采集；"
        "启用前需人工核验。",
        entry_url="https://zhida.zhihu.com/",
    ),
    CatalogEntry(
        "xiaohongshu_diandian",
        "小红书点点",
        "小红书",
        "探测 5 个",
        EngineEntryType.APP_SEARCH,
        "小红书点点应用内入口",
        "官方入口：https://www.xiaohongshu.com/ai_chat（PC 端点点）；App 内从首页左上角/消息页进入点点。"
        "需登录小红书，部分账号需领取内测资格。回答右侧展示相关笔记原文与互动数据，来源可溯源。"
        "纯应用内检索，人工采样，不自动采集；启用前需人工核验。",
        entry_url="https://www.xiaohongshu.com/ai_chat",
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
