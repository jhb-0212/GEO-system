"""补录用户 2026-11-27 发来的站点截图清单（第三批）到 `gz-base` 渠道台账。

14 张图里 4 张是台账已有站点（网经社 100ec.cn、列举网 lieju.com、列表网 liebiao.com、
沥青在线），10 张是新站：

| 图 | 站点 | 域名 | 判定依据 |
|---|---|---|---|
| 1 | 黔东南信息港 | qdn.cn | 图上直印 WWW.QDN.CN |
| 2 | 二泉网 | wst.cn | 图上直印 www.wst.cn |
| 3 | 中网化工 | okmart.com | 图上直印 OKMART.COM |
| 4 | 商业品牌网 | chinapp.net.cn | 检索确认同名站点 |
| 5 | 旅游网（看看旅游网） | seelvyou.com | 图搜命中同款 logo 的 seelvyou.com |
| 6 | 旅新网 | tourfresh.com | 抓取站点标题含「旅新网」，logo 一致 |
| 7 | 北京家电维修网 | bjjdwx.com | 图上直印 BJJDWX.COM |
| 8 | 品牌排行网 | cnpinpai.cn | 图上直印 CNPINPAI.CN |
| 9 | 在苏生活圈·江苏龙网 | 待核验 | 品牌未检索到公开域名，留空 |
| 10 | 涂料在线 | coatingol.com | 图上直印 coatingol.com |

顺带修正：沥青在线截图直印 www.sinoasphalt.com，补上 liqing-online 的主域名，
结束上一轮「域名待核验」。

口径：这批只有站点标识、没有账号和报价，全部按 `candidate + pending_review` 登记，
不预设可发布、不预设已合作；备注里写清来源与待补项，避免被当成已有发布证据。
另有「旅新网」同名站 ctna.cn（中国旅游记者协会主办），与本条 tourfresh.com 不是同一站，
备注里标注防混。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_channel_media_list_2026_11_27.py --dry-run
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_channel_media_list_2026_11_27.py
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Channel, ChannelApproval, Project, User
from app.models.enums import ChannelApprovalStatus, ChannelCategory, ChannelStatus
from app.services.channel_registry import ensure_primary_domain

PROJECT_CODE = "gz-base"
OWNER = "渠道运营组"
SOURCE_TAG = "截图清单 2026-11-27"

NEW_CHANNELS: list[dict] = [
    {
        "code": "qdn",
        "name": "黔东南信息港",
        "category": ChannelCategory.LOCAL_MEDIA,
        "primary_domain": "qdn.cn",
        "notes": (
            "【地方门户·贵州黔东南】截图直印 www.qdn.cn。｜截图只有站点标识，账号、报价、"
            "发布能力均待补；地域与广州基地不匹配，暂列备选，不排期。"
        ),
    },
    {
        "code": "wst",
        "name": "二泉网",
        "category": ChannelCategory.LOCAL_MEDIA,
        "primary_domain": "wst.cn",
        "notes": (
            "【地方社区·江苏无锡】截图直印 www.wst.cn，无锡本地门户/论坛。"
            "｜账号与报价待补；地域不匹配，只做低价铺量备选。"
        ),
    },
    {
        "code": "okmart",
        "name": "中网化工",
        "category": ChannelCategory.INDUSTRY_MEDIA,
        "primary_domain": "okmart.com",
        "notes": (
            "【行业门户·化工】截图直印 OKMART.COM，主打化工行业供求与资讯。"
            "｜与招生业务不匹配，只做信源占位，不投预算。"
        ),
    },
    {
        "code": "chinapp",
        "name": "商业品牌网",
        "category": ChannelCategory.INDUSTRY_MEDIA,
        "primary_domain": "chinapp.net.cn",
        "notes": (
            "【品牌资讯门户】CBN 中国商业品牌资讯门户，域名 chinapp.net.cn；主体为贵州新商传媒，"
            "旗下另有黔浪网、新消费品牌网，主打「AI 信源布局」。"
            "｜适合发品牌稿，不适合招生硬广；账号与报价待补。"
        ),
    },
    {
        "code": "seelvyou",
        "name": "看看旅游网（旅游网）",
        "category": ChannelCategory.INDUSTRY_MEDIA,
        "primary_domain": "seelvyou.com",
        "notes": (
            "【旅游门户】品牌标识为「旅游网」，slogan「我想去旅游」，图搜命中同款 logo 的 seelvyou.com。"
            "｜旅游类媒体，与招生业务弱相关；账号与报价待补。"
        ),
    },
    {
        "code": "tourfresh",
        "name": "旅新网",
        "category": ChannelCategory.INDUSTRY_MEDIA,
        "primary_domain": "tourfresh.com",
        "notes": (
            "【旅游媒体】TOUR 旅新网，站点标题「旅游新鲜事 | 旅新网」，域名 tourfresh.com。"
            "｜注意：另有同名「旅新网」ctna.cn（中国旅游记者协会主办），不是同一家，归因时别混。"
            "｜账号与报价待补。"
        ),
    },
    {
        "code": "bjjdwx",
        "name": "北京家电维修网",
        "category": ChannelCategory.INDUSTRY_MEDIA,
        "primary_domain": "bjjdwx.com",
        "notes": (
            "【垂直服务资讯·家电维修】截图直印 BJJDWX.COM。"
            "｜与 AIGC/招生业务基本无关，列为备选，不排期；账号与报价待补。"
        ),
    },
    {
        "code": "cnpinpai",
        "name": "品牌排行网",
        "category": ChannelCategory.INDUSTRY_MEDIA,
        "primary_domain": "cnpinpai.cn",
        "notes": (
            "【品牌榜单站】截图直印 CNPINPAI.CN，发品牌排行与品牌资讯。"
            "｜榜单类站点适合背书，不能承诺排名；账号与报价待补。"
        ),
    },
    {
        "code": "zaisu",
        "name": "在苏生活圈·江苏龙网",
        "category": ChannelCategory.LOCAL_MEDIA,
        "primary_domain": None,
        "notes": (
            "【地方生活门户·江苏】截图标识「在苏生活圈·江苏龙网」，未检索到公开域名，"
            "主体疑似江苏龙网传媒（备案域名 loongwang.com），未核实前不录主域名、不参与域名观测。"
            "｜账号与报价待补。"
        ),
    },
    {
        "code": "coatingol",
        "name": "涂料在线",
        "category": ChannelCategory.INDUSTRY_MEDIA,
        "primary_domain": "coatingol.com",
        "notes": (
            "【行业门户·涂料】截图直印 www.coatingol.com，标注「涂料产业化综合服务平台」。"
            "｜与招生业务不匹配，只做信源占位；账号与报价待补。"
        ),
    },
]

# 已有渠道：截图补域名
DOMAIN_FIXES: list[dict] = [
    {
        "code": "liqing-online",
        "domain": "sinoasphalt.com",
        "append": (
            "｜截图清单直印 www.sinoasphalt.com，标注「广东省沥青混凝土供应链协会支持媒体」，"
            "上一轮「域名待核验」状态解除。"
        ),
    },
]


def _append_note(current: str | None, extra: str) -> str:
    base = (current or "").strip()
    if extra.strip() in base:
        return base
    if not base:
        return extra.strip().lstrip("｜")
    return f"{base}{extra}"


def main() -> int:
    parser = argparse.ArgumentParser(description="按截图清单补录渠道")
    parser.add_argument("--project-code", default=PROJECT_CODE)
    parser.add_argument("--actor", default="geo_admin")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    created = skipped = fixed = conflicts = 0

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            raise SystemExit(f"未找到项目：{args.project_code}")
        actor = db.scalar(select(User).where(User.username == args.actor))
        if actor is None:
            raise SystemExit(f"未找到操作人：{args.actor}")

        for spec in NEW_CHANNELS:
            existing = db.scalar(
                select(Channel).where(
                    Channel.project_id == project.id, Channel.code == spec["code"]
                )
            )
            if existing is not None:
                print(f"跳过 {spec['code']}（{existing.name}）已在台账")
                skipped += 1
                continue

            try:
                ensure_primary_domain(
                    db, project_id=project.id, channel=None, domain=spec["primary_domain"]
                )
            except Exception as exc:
                print(f"域名冲突，中止：{spec['code']} → {spec['primary_domain']}（{exc}）")
                conflicts += 1
                break

            channel = Channel(
                project_id=project.id,
                code=spec["code"],
                name=spec["name"],
                category=spec["category"],
                status=ChannelStatus.CANDIDATE,
                primary_domain=spec["primary_domain"],
                publish_url=None,
                login_url=None,
                owner_name=OWNER,
                owner_contact=None,
                notes=spec["notes"],
                is_active=True,
                approval_status=ChannelApprovalStatus.PENDING_REVIEW,
                submitted_by=actor.id,
                submitted_at=now,
            )
            db.add(channel)
            db.flush()

            db.add(
                ChannelApproval(
                    project_id=project.id,
                    channel_id=channel.id,
                    submitted_by=actor.id,
                    submitted_at=now,
                    comment=f"{SOURCE_TAG}：仅站点标识，账号与报价待补",
                )
            )
            print(
                f"新增 {channel.code:<12} {channel.name}｜{channel.category}｜"
                f"{channel.primary_domain or '(域名待核验)'}"
            )
            created += 1

        if conflicts == 0:
            for fix in DOMAIN_FIXES:
                channel = db.scalar(
                    select(Channel).where(
                        Channel.project_id == project.id, Channel.code == fix["code"]
                    )
                )
                if channel is None:
                    print(f"域名修正跳过 {fix['code']}（台账无此渠道）")
                    continue
                if channel.primary_domain != fix["domain"]:
                    ensure_primary_domain(
                        db, project_id=project.id, channel=channel, domain=fix["domain"]
                    )
                    channel.primary_domain = fix["domain"]
                    fixed += 1
                channel.notes = _append_note(channel.notes, fix["append"])
                print(f"域名修正 {channel.code} → {fix['domain']}")

        if args.dry_run:
            db.rollback()
            mode = "预演（已回滚，未写库）"
        else:
            db.commit()
            mode = "已写库"

    print(f"合计：新增 {created}、跳过 {skipped}、域名修正 {fixed}、冲突 {conflicts}；{mode}")
    return 1 if conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
