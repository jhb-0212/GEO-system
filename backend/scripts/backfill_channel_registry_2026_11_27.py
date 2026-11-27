"""把《网站与APP注册信息登记表》里的平台补进 `gz-base` 渠道台账（2026-11-27 第二批）。

登记表共 2 个 sheet、40 行账号记录，去重后 29 个平台：
- 15 个台账里已有（搜狐/头条/网易号/百家号/知乎/小红书/抖音/B站/微博/公众号/视频号/企鹅号/
  中科/八方/免费黄页网），只补账号与发布能力备注；
- 13 个是新增（腾讯网、新浪网、凤凰网、供应商门户网、列表网、博客园、商业新知、列举网、
  淄博新闻网、国脉数字智库、中国民用航空网、长三角城市网、什么值得买）；
- QQ 只是即时通讯账号，没有公开发布能力，不入渠道台账。

两条纪律：
1. **密码和手机号一律不写库**。登记表里的明文密码、绑定手机号属于凭据/PII，台账只记平台、
   账号昵称、发布能力与准入状态；需要账号密码时回到登记表人工取。
2. 准入按"能不能发"分档：可发布的记 approved，明确不可发布的（腾讯网、凤凰网）记
   pending_review，等业务确认用途后再审。

另外修正一条历史数据：登记表显示「免费黄页网」就是「黄页88」，域名 huangye88.com，
补进 free-huangye 的主域名，结束上一轮"域名待核验"的悬空状态。

幂等：按 code 判存在，已存在则跳过；备注按标记去重，重复执行不会叠加。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_channel_registry_2026_11_27.py --dry-run
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_channel_registry_2026_11_27.py
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Channel, ChannelAlias, ChannelApproval, Project, User
from app.models.enums import (
    ChannelApprovalStatus,
    ChannelCategory,
    ChannelStatus,
    ReviewDecision,
)
from app.services.audit import record_audit
from app.services.channel_registry import ensure_alias, ensure_primary_domain

PROJECT_CODE = "gz-base"
OWNER = "渠道运营组"
SOURCE = "《网站与APP注册信息登记表》2026-11-27"

NEW_CHANNELS: list[dict] = [
    {
        "code": "tencent-portal",
        "name": "腾讯网",
        "category": ChannelCategory.CONTENT_PLATFORM,
        "primary_domain": None,
        "publishable": False,
        "aliases": [],
        "notes": (
            "【门户】登记表账号「用户6216913」，手机号+验证码注册，备注明确「不可以发布文章」。"
            "｜主域名留空：qq.com 是腾讯全站入口（QQ/腾讯新闻/腾讯视频都在其下），设为渠道主域名会把"
            "整站引用误算成本渠道。｜用途待定，暂按不可发布登记。"
        ),
    },
    {
        "code": "sina",
        "name": "新浪网",
        "category": ChannelCategory.CONTENT_PLATFORM,
        "primary_domain": "sina.com.cn",
        "publishable": True,
        "aliases": [],
        "notes": (
            "【门户】登记表账号「广东省AI数字人才就业实训基地」，手机号+验证码注册，备注「可以发布文章」。"
            "｜发布走新浪看点/新浪新闻自媒体入口，账号密码不入库。"
        ),
    },
    {
        "code": "ifeng",
        "name": "凤凰网",
        "category": ChannelCategory.CONTENT_PLATFORM,
        "primary_domain": "ifeng.com",
        "publishable": False,
        "aliases": [],
        "notes": (
            "【门户】登记表账号「广东省AI数字人才就业实训基地」，备注「不可以发布文章」，"
            "绑定手机收不到验证码、只能用微信扫码登录。｜先解决登录再谈发布，暂按不可发布登记。"
        ),
    },
    {
        "code": "chinagysw",
        "name": "供应商门户网",
        "category": ChannelCategory.B2B,
        "primary_domain": "chinagysw.cn",
        "publishable": True,
        "aliases": [],
        "notes": (
            "【B2B 黄页】登记表账号 gdaisx，手机号+验证码注册，备注「可以发布文章」。"
            "｜发布入口 chinagysw.cn/member/，商讯正文禁留电话与微信二维码。"
        ),
    },
    {
        "code": "liebiao",
        "name": "列表网",
        "category": ChannelCategory.B2B,
        "primary_domain": "liebiao.com",
        "publishable": True,
        "aliases": [],
        "notes": (
            "【分类信息】登记表账号 m55321350，备注「可以发布文章」。"
            "｜分类信息站，适合发招生简章/课程信息，标题禁绝对化用语。"
        ),
    },
    {
        "code": "cnblogs",
        "name": "博客园",
        "category": ChannelCategory.COMMUNITY,
        "primary_domain": "cnblogs.com",
        "publishable": True,
        "aliases": [],
        "notes": (
            "【技术社区】登记表账号「广东省AI就业实训基地」，手机号或邮箱注册，备注「可以发布文章」。"
            "｜适合发实训技术向内容，正文可带官网链接，不做招生硬广。"
        ),
    },
    {
        "code": "shangyexinzhi",
        "name": "商业新知",
        "category": ChannelCategory.CONTENT_PLATFORM,
        "primary_domain": "shangyexinzhi.com",
        "publishable": True,
        "aliases": [],
        "notes": (
            "【商业资讯自媒体】登记表账号「广东省AI就业基地」，备注「可以发布文章」。"
            "｜后台 shangyexinzhi.com/my，偏商业分析稿，不走招生话术。"
        ),
    },
    {
        "code": "lieju",
        "name": "列举网",
        "category": ChannelCategory.B2B,
        "primary_domain": "lieju.com",
        "publishable": True,
        "aliases": [],
        "notes": (
            "【分类信息】登记表账号「广东省AI就业实训基地」，备注「可以发布文章」。"
            "｜发布入口 post.lieju.com，按城市站分发。"
        ),
    },
    {
        "code": "zbnews",
        "name": "淄博新闻网",
        "category": ChannelCategory.LOCAL_MEDIA,
        "primary_domain": "zbnews.net",
        "publishable": True,
        "aliases": [],
        "notes": (
            "【地方媒体】登记表备注「手机APP注册成功（只有手机APP）」，可发图文与视频。"
            "｜没有网页后台，只能手机端操作；山东淄博地方站，与广州基地地域不匹配，只做信源铺量。"
        ),
    },
    {
        "code": "govmade",
        "name": "国脉数字智库",
        "category": ChannelCategory.INDUSTRY_MEDIA,
        "primary_domain": None,
        "publishable": True,
        "aliases": [],
        "notes": (
            "【行业智库】登记表账号「广东省AI数字人才就业实训基地」（头像改不了），备注「可以发布文章」，"
            "但登记网址为空，域名待核验后补；未核实前不参与域名观测。"
        ),
    },
    {
        "code": "ccaonline",
        "name": "中国民用航空网",
        "category": ChannelCategory.INDUSTRY_MEDIA,
        "primary_domain": "ccaonline.cn",
        "publishable": True,
        "aliases": [],
        "notes": (
            "【行业媒体·民航】登记表账号「广东省AI就业实训基地」，备注可发图文与视频。"
            "｜民航垂直站，与招生业务弱相关，只做品牌背书，不排期。"
        ),
    },
    {
        "code": "yrdcity",
        "name": "长三角城市网",
        "category": ChannelCategory.LOCAL_MEDIA,
        "primary_domain": "yrdcity.com",
        "publishable": True,
        "aliases": [],
        "notes": (
            "【区域门户】登记表账号「广东省AI数字人才就业实训基地」，备注为空、未标注发布能力，"
            "按已注册可试探发布登记。｜长三角区域站，与广州基地地域不匹配。"
        ),
    },
    {
        "code": "smzdm",
        "name": "什么值得买",
        "category": ChannelCategory.CONTENT_PLATFORM,
        "primary_domain": "smzdm.com",
        "publishable": True,
        "aliases": [],
        "notes": (
            "【消费社区】登记表账号「值友4310733978（改名审核中，目标名：广东AI数字实训基地）」，"
            "备注可发图文与视频。｜消费决策社区，只发课程评测类软文，禁硬广。"
        ),
    },
]

# 已有渠道：补账号/发布能力备注（追加，不覆盖原有内容；标记去重）
NOTE_PATCHES: list[dict] = [
    {"code": "sohu", "mark": "登记表：账号「广东省AI数字人才就业实训基地」", "append": "｜登记表：账号「广东省AI数字人才就业实训基地」，可发图文与视频；密码不入库"},
    {"code": "toutiao", "mark": "登记表：账号「广东省AI数字人才就业实训基地」", "append": "｜登记表：账号「广东省AI数字人才就业实训基地」，可发图文与视频"},
    {"code": "netease", "mark": "登记表：网易号", "append": "｜登记表：网易号（mp.163.com）与网易（163.com）同主体，账号「广东省AI数字人才就业实训基地」，可发图文与视频"},
    {"code": "baijiahao", "mark": "登记表：账号「广东省AI数字人才就业实训基地」", "append": "｜登记表：账号「广东省AI数字人才就业实训基地」，已实名，可发图文与视频"},
    {"code": "zhihu", "mark": "登记表：账号「成才AI就业实训」", "append": "｜登记表：账号「成才AI就业实训」，可发图文"},
    {"code": "xiaohongshu", "mark": "登记表：两个账号", "append": "｜登记表：两个账号「广东省AI数字人才就业实训基地」「广东省成才培训」，可发图文与视频"},
    {"code": "douyin", "mark": "登记表：两个账号", "append": "｜登记表：两个账号「广东省AI数字人才就业实训基地官方号」「广东省成才人工智能产业孵化有限公司」，可发视频"},
    {"code": "bilibili", "mark": "登记表：账号「AI数字人才就业实训」", "append": "｜登记表：账号「AI数字人才就业实训」，可发图文与视频"},
    {"code": "weibo", "mark": "登记表：账号「广东省AI数字人才就业实训基地」", "append": "｜登记表：账号「广东省AI数字人才就业实训基地」，可发图文与视频"},
    {"code": "wechat-mp", "mark": "登记表：两个公众号", "append": "｜登记表：两个公众号「广东省AI数字人才就业实训基地」「广东成才数字实训基地」，可发图文与视频"},
    {"code": "channels-video", "mark": "登记表：两个视频号", "append": "｜登记表：两个视频号「成才AI人才就业实训」「广东省AI就业实训基地」，可发视频"},
    {"code": "tencent-open", "mark": "登记表：企鹅号", "append": "｜登记表：企鹅号（om.qq.com）账号「广东省AI数字人才就业实训基地」，可发图文与视频"},
    {"code": "zk71", "mark": "登记表：账号 gdccai", "append": "｜登记表：账号 gdccai，备注「不可以发布文章」——与上一轮「免费注册即可发布」的口径冲突，发布前先核实会员权限"},
    {"code": "b2b168", "mark": "登记表：账号 gdaisx", "append": "｜登记表：账号 gdaisx，备注「可以发布文章」（m.b2b168.com 会员中心）"},
]

# 域名修正：登记表证明免费黄页网就是黄页88
DOMAIN_FIXES: list[dict] = [
    {
        "code": "free-huangye",
        "domain": "huangye88.com",
        "note": (
            "【B2B 黄页】登记表证明「免费黄页网」就是「黄页88」，主域名 huangye88.com，"
            "上一轮「域名待核验」状态解除；账号 gdaisx，可发布文章。"
            "｜R1 真实采集（2026-11-27）域名级命中 0 次。｜准入仍为待审批，先免费铺量观察。"
        ),
    },
]

# 子域名落别名，便于信源层观测命中
ALIASES: list[dict] = [
    {"code": "netease", "domain": "mp.163.com", "alias_name": "网易号后台", "notes": "同上主体，登记表 mp.163.com"},
    {"code": "sohu", "domain": "mp.sohu.com", "alias_name": "搜狐号后台", "notes": "同上主体，登记表 mp.sohu.com"},
    {"code": "toutiao", "domain": "mp.toutiao.com", "alias_name": "头条号后台", "notes": "同上主体，登记表 mp.toutiao.com"},
]


def _append_note(current: str | None, extra: str) -> str:
    base = (current or "").strip()
    if extra.strip() in base:
        return base
    if not base:
        return extra.strip().lstrip("｜")
    return f"{base}{extra}"


def _strip_leading_separator(current: str | None) -> str:
    return (current or "").strip().lstrip("｜")


def main() -> int:
    parser = argparse.ArgumentParser(description="按注册信息登记表补录渠道")
    parser.add_argument("--project-code", default=PROJECT_CODE)
    parser.add_argument("--actor", default="geo_admin")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    created = skipped = patched = fixed = aliased = conflicts = 0

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

            domain = spec["primary_domain"]
            try:
                ensure_primary_domain(db, project_id=project.id, channel=None, domain=domain)
            except Exception as exc:
                print(f"域名冲突，中止：{spec['code']} → {domain}（{exc}）")
                conflicts += 1
                break

            approved = spec["publishable"]
            channel = Channel(
                project_id=project.id,
                code=spec["code"],
                name=spec["name"],
                category=spec["category"],
                status=ChannelStatus.CANDIDATE,
                primary_domain=domain,
                publish_url=None,
                login_url=None,
                owner_name=OWNER,
                owner_contact=None,
                notes=spec["notes"],
                is_active=True,
                approval_status=(
                    ChannelApprovalStatus.APPROVED
                    if approved
                    else ChannelApprovalStatus.PENDING_REVIEW
                ),
                submitted_by=actor.id,
                submitted_at=now,
                reviewed_by=actor.id if approved else None,
                reviewed_at=now if approved else None,
                decision_comment="注册信息登记表补录：账号已注册且平台侧可发布" if approved else None,
            )
            db.add(channel)
            db.flush()

            approval = ChannelApproval(
                project_id=project.id,
                channel_id=channel.id,
                submitted_by=actor.id,
                submitted_at=now,
                reviewed_by=actor.id if approved else None,
                reviewed_at=now if approved else None,
                decision=ReviewDecision.APPROVED if approved else None,
                comment="登记表补录：已注册可发布" if approved else "登记表补录：平台侧不可发布，待确认用途",
            )
            db.add(approval)
            db.flush()

            if approved:
                record_audit(
                    db,
                    project_id=project.id,
                    actor_id=actor.id,
                    action="channel.approve",
                    target_type="channel",
                    target_id=channel.id,
                    payload={
                        "code": channel.code,
                        "category": str(channel.category),
                        "primary_domain": channel.primary_domain,
                        "source": "registry_2026_11_27",
                    },
                )
            print(
                f"新增 {channel.code:<15} {channel.name}｜{channel.category}｜{channel.approval_status}"
                f"｜{channel.primary_domain or '(无域名)'}"
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
                if fix.get("note"):
                    channel.notes = fix["note"]
                print(f"域名修正 {channel.code} → {fix['domain']}")

            for patch in NOTE_PATCHES:
                channel = db.scalar(
                    select(Channel).where(
                        Channel.project_id == project.id, Channel.code == patch["code"]
                    )
                )
                if channel is None:
                    print(f"备注跳过 {patch['code']}（台账无此渠道）")
                    continue
                if patch["mark"] in (channel.notes or ""):
                    continue
                channel.notes = _append_note(channel.notes, patch["append"])
                patched += 1
                print(f"备注补强 {channel.code}（{channel.name}）")

            for alias in ALIASES:
                channel = db.scalar(
                    select(Channel).where(
                        Channel.project_id == project.id, Channel.code == alias["code"]
                    )
                )
                if channel is None:
                    print(f"别名跳过 {alias['code']}（台账无此渠道）")
                    continue
                exists = db.scalar(
                    select(ChannelAlias).where(
                        ChannelAlias.project_id == project.id,
                        ChannelAlias.domain == alias["domain"],
                    )
                )
                if exists is not None:
                    continue
                ensure_alias(
                    db,
                    project_id=project.id,
                    channel=channel,
                    domain=alias["domain"],
                    alias_name=alias["alias_name"],
                )
                db.flush()
                row = db.scalar(
                    select(ChannelAlias).where(
                        ChannelAlias.project_id == project.id,
                        ChannelAlias.domain == alias["domain"],
                    )
                )
                if row is not None and not row.notes:
                    row.notes = alias["notes"]
                aliased += 1
                print(f"别名 {alias['domain']} → {alias['code']}")

            # 上一轮把备注追加到空备注时留下了前导「｜」，这里统一清掉
            for patch in NOTE_PATCHES:
                channel = db.scalar(
                    select(Channel).where(
                        Channel.project_id == project.id, Channel.code == patch["code"]
                    )
                )
                if channel is None:
                    continue
                cleaned = _strip_leading_separator(channel.notes)
                if cleaned != (channel.notes or ""):
                    channel.notes = cleaned
                    print(f"备注去前导分隔符 {channel.code}")

        if args.dry_run:
            db.rollback()
            mode = "预演（已回滚，未写库）"
        else:
            db.commit()
            mode = "已写库"

    print(
        f"合计：新增 {created}、跳过 {skipped}、备注 {patched}、域名修正 {fixed}、别名 {aliased}、"
        f"冲突 {conflicts}；{mode}"
    )
    return 1 if conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
