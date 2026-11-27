"""为 15 个引擎补齐网页端/手机端人工入口（幂等）。

入口类型固定为 `web_user` / `app_user`，协议固定 `custom`：
- 只登记人工入口与 URL/路径，不自动采集、不写凭据；
- 已有同类型入口时更新 URL / 说明 / 启停状态，不新建重复行；
- 手机端保留 `entry_url` 为空，路径写在 `access_note`，避免伪造 deep link；
- 入口启停跟随引擎：引擎停用则入口停用；微信搜一搜无独立网页端，网页入口强制停用。

用法（backend 目录）：
    .\\backend\\.venv\\Scripts\\python.exe backend\\scripts\\seed_user_side_entries.py ^
        --database-url "postgresql+psycopg://geo:geo_dev@localhost:5433/geo_pilot" --apply --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

WEB = "web_user"
APP = "app_user"

PLAN = {
    "baidu_ai_search": {
        "web": (
            "百度AI搜 网页版（人工）",
            "https://chat.baidu.com/",
            "官方入口当前跳转文心 chat_site；与百度文心网页端重叠，单独记录时必须标注入口来源，不能与文心合并算提及。人工网页端，需登录；逐题新开对话。",
        ),
        "app": (
            "百度AI搜 手机端（百度 App 内，人工）",
            None,
            "百度 App → AI 搜索入口；无独立 App。人工手机端，需登录；记录设备、百度 App 版本与入口路径；引用按界面展示记录；不自动采集。",
        ),
    },
    "deepseek": {
        "web": (
            "DeepSeek 网页版（人工）",
            "https://chat.deepseek.com/",
            "人工网页端；需登录后可用；智能搜索开启；引用区显示网页数量，可展开取 URL。",
        ),
        "app": (
            "DeepSeek 手机客户端（人工）",
            None,
            "DeepSeek App；人工手机端，需登录；记录设备与 App 版本；逐题新开对话；不自动采集。",
        ),
    },
    "doubao": {
        "web": (
            "豆包网页版（人工）",
            "https://www.doubao.com/chat/",
            "人工网页端；需登录；逐题新开对话；引用区可展开取 URL。",
        ),
        "app": (
            "豆包手机客户端（人工）",
            None,
            "豆包 App；人工手机端，需登录；记录设备与 App 版本；逐题新开对话；不自动采集。",
        ),
    },
    "kimi": {
        "web": (
            "Kimi 网页版（人工）",
            "https://www.kimi.com/",
            "人工网页端；需登录；逐题新开对话；回答引用按页面展示记录。",
        ),
        "app": (
            "Kimi 手机客户端（人工）",
            None,
            "Kimi App；人工手机端，需登录；记录设备与 App 版本；逐题新开对话；不自动采集。",
        ),
    },
    "metaso": {
        "web": (
            "秘塔AI搜索 网页版（人工）",
            "https://metaso.cn/",
            "人工网页端；基础检索可直接打开，保存历史与深度研究需登录；回答带来源编号与链接。",
        ),
        "app": (
            "秘塔AI搜索 手机客户端（人工）",
            None,
            "秘塔 AI 搜索 App；人工手机端，需登录；记录设备与 App 版本；来源按回答引用记录；不自动采集。",
        ),
    },
    "nami_ai": {
        "web": (
            "360纳米AI 网页版（人工）",
            "https://www.n.cn/",
            "官方入口当前跳转 work.n.cn / 纳米work；人工网页端，需登录 360 账号；来源以引用/网页列表为准。",
        ),
        "app": (
            "360纳米AI 手机客户端（人工）",
            None,
            "360 纳米 AI App；人工手机端，需登录 360 账号；记录设备与 App 版本；不自动采集。",
        ),
    },
    "qianwen": {
        "web": (
            "千问 网页版（人工）",
            "https://www.qianwen.com/",
            "tongyi.com 当前跳转 qianwen.com；人工网页端，需登录；逐题新开对话；引用按页面展示记录。",
        ),
        "app": (
            "千问 手机客户端（人工）",
            None,
            "千问 App；人工手机端，需登录；记录设备与 App 版本；逐题新开对话；不自动采集。",
        ),
    },
    "quark": {
        "web": (
            "夸克 网页版（人工）",
            "https://www.quark.cn/s",
            "人工网页端；可直接提问；回答为 AI 总结，来源以结果页引用与网页列表为准。",
        ),
        "app": (
            "夸克 手机客户端（人工）",
            None,
            "夸克 App → 首页「问 AI」/搜索框；人工手机端，需登录；记录设备与 App 版本；不自动采集。",
        ),
    },
    "spark": {
        "web": (
            "讯飞星火 网页版（人工）",
            "https://xinghuo.xfyun.cn/",
            "人工网页端；需登录；逐题新开对话；引用按页面展示记录。",
        ),
        "app": (
            "讯飞星火 手机客户端（人工）",
            None,
            "讯飞星火 App；人工手机端，需登录；记录设备与 App 版本；逐题新开对话；不自动采集。",
        ),
    },
    "wechat_search_ai": {
        "web": (
            "微信搜一搜 AI 网页端（人工，无独立页）",
            "https://search.weixin.qq.com/",
            "微信搜一搜无独立网页版；该 URL 仅为官方开放平台/产品说明页，不能作为网页端采集，入口强制停用。",
        ),
        "app": (
            "微信搜一搜 AI 手机端（微信内，人工）",
            None,
            "微信 App → 发现 → 搜一搜 → 输入问题 → AI 搜索；AI 入口按账号/版本灰度开放。人工手机端，需登录微信；记录设备、微信版本与灰度状态；不自动采集。",
        ),
    },
    "wenxin": {
        "web": (
            "文心一言网页版（人工）",
            "https://wenxin.baidu.com/",
            "人工网页端；可匿名提问；来源列表 20-80 条，可按页面展示记录链接。",
        ),
        "app": (
            "文心一言手机客户端（人工）",
            None,
            "文心 App；人工手机端，需登录；记录设备与 App 版本；逐题新开对话；不自动采集。",
        ),
    },
    "xiaohongshu_diandian": {
        "web": (
            "小红书点点 网页版（人工）",
            "https://www.xiaohongshu.com/ai_chat",
            "PC 端点点；需登录小红书，部分账号需内测资格；回答右侧展示相关笔记原文与互动数据。",
        ),
        "app": (
            "小红书点点 手机端（小红书 App 内，人工）",
            None,
            "小红书 App → 首页左上角/消息页进入点点；人工手机端，需登录；记录设备、App 版本与内测资格；不自动采集。",
        ),
    },
    "yuanbao": {
        "web": (
            "腾讯元宝网页版（人工）",
            "https://yuanbao.tencent.com/",
            "人工网页端；需微信/手机/QQ 登录；回答显示引用资料数量，来源 URL 可能未暴露可复制链接。",
        ),
        "app": (
            "腾讯元宝手机客户端（人工）",
            None,
            "腾讯元宝 App；人工手机端，需登录；记录设备与 App 版本；微信内入口不与独立 App 混算；不自动采集。",
        ),
    },
    "zhihu_direct": {
        "web": (
            "知乎直答 网页版（人工）",
            "https://zhida.zhihu.com/",
            "人工网页端；需登录知乎账号；支持简略/深入/专业搜索；回答带知乎内容与外部来源。",
        ),
        "app": (
            "知乎直答 手机端（知乎 App 内，人工）",
            None,
            "知乎 App → 直答入口；人工手机端，需登录；记录设备与 App 版本；来源按回答展示记录；不自动采集。",
        ),
    },
    "zhipu": {
        "web": (
            "智谱清言 网页版（人工）",
            "https://chatglm.cn/",
            "人工网页端；需登录；逐题新开对话；引用按页面展示记录。",
        ),
        "app": (
            "智谱清言 手机客户端（人工）",
            None,
            "智谱清言 App；人工手机端，需登录；记录设备与 App 版本；逐题新开对话；不自动采集。",
        ),
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="补齐 15 引擎的网页端/手机端人工入口")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--apply", action="store_true", help="实际写库；缺省只做 dry-run")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    db_name = args.database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    os.environ["DATABASE_URL"] = args.database_url
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    from sqlalchemy import select  # noqa: E402

    from app.db.session import SessionLocal  # noqa: E402
    from app.models import AiEngine, AiEngineEntry  # noqa: E402
    from app.models.enums import EngineEntryType, EngineProtocol  # noqa: E402

    verified_at = datetime.now(UTC).replace(microsecond=0)

    with SessionLocal() as db:
        engines = db.scalars(select(AiEngine).order_by(AiEngine.code)).all()
        by_code = {engine.code: engine for engine in engines}
        missing = sorted(set(PLAN) - set(by_code))
        extra = sorted(set(by_code) - set(PLAN))
        if missing:
            raise SystemExit(f"库 {db_name} 缺少引擎：{missing}")
        if extra:
            raise SystemExit(f"库 {db_name} 存在未覆盖引擎：{extra}；请先补 PLAN")

        changes = []
        for code, spec in PLAN.items():
            engine = by_code[code]
            for entry_type, (name, url, note) in ((WEB, spec["web"]), (APP, spec["app"])):
                row = db.scalar(
                    select(AiEngineEntry).where(
                        AiEngineEntry.engine_id == engine.id,
                        AiEngineEntry.entry_type == EngineEntryType(entry_type),
                    )
                )
                active = bool(engine.is_active)
                if entry_type == WEB and code == "wechat_search_ai":
                    active = False
                if row is None:
                    action = "create"
                    row = AiEngineEntry(
                        engine_id=engine.id,
                        entry_type=EngineEntryType(entry_type),
                        name=name,
                        entry_url=url,
                        protocol=EngineProtocol.CUSTOM,
                        supports_search=True,
                        access_note=note,
                        last_verified_at=verified_at if entry_type == WEB else None,
                        is_active=active,
                    )
                    db.add(row)
                else:
                    action = "update"
                    row.name = name
                    if url:
                        row.entry_url = url
                    row.protocol = EngineProtocol.CUSTOM
                    row.supports_search = True
                    row.access_note = note
                    row.last_verified_at = verified_at if entry_type == WEB else row.last_verified_at
                    row.is_active = active
                changes.append(
                    {
                        "engine": code,
                        "entry_type": entry_type,
                        "name": name,
                        "entry_url": url or "",
                        "is_active": active,
                        "action": action,
                    }
                )

        if args.apply:
            db.commit()
        else:
            db.rollback()

    payload = {
        "database": db_name,
        "applied": bool(args.apply),
        "engines": len(PLAN),
        "entries": len(changes),
        "web_active": sum(1 for c in changes if c["entry_type"] == WEB and c["is_active"]),
        "app_active": sum(1 for c in changes if c["entry_type"] == APP and c["is_active"]),
        "changes": changes,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for row in changes:
            print(f"{row['action']:6} {row['engine']:22} {row['entry_type']:8} active={row['is_active']} {row['name']}")
        print(f"库={db_name} applied={args.apply} entries={len(changes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
