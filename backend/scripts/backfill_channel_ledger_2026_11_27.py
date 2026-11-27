"""补录 2026-11-27 渠道增补批次到 `gz-base` 台账（14 条 + 2 条存量备注补强）。

口径：只补台账，不建发布账号/任务/回执。引用归因（`monitoring_citations.channel_id`）
仍要靠 `publish_receipts.published_url` → `publish_tasks.channel_id`，微录渠道不会
自动回填——`backfill_citation_channels.py` 的域名级匹配早已废弃，不要指望它。

准入状态的分界：
- 在 R1 真实采集里已被 AI 引用的站 → `approved` + `observed`，视作"历史已发布渠道
  补录"，同时写一条 `channel_approvals` 通过记录留痕；
- 尚无引用、只是候选的站 → `pending_review` + `candidate`，等发布前再由项目管理员
  在页面上审批，不提前放行建任务权限。

幂等：按 code 判存在，已存在则跳过（不覆盖人工改过的字段）。域名冲突直接中断，
不静默改归属。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_channel_ledger_2026_11_27.py --dry-run
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_channel_ledger_2026_11_27.py
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
from app.services.channel_registry import ensure_primary_domain

PROJECT_CODE = "gz-base"
OWNER = "渠道运营组"

# (code, name, category, status, primary_domain, aliases, notes)
NEW_CHANNELS: list[dict] = [
    {
        "code": "b2b168",
        "name": "八方资源网",
        "category": ChannelCategory.B2B,
        "status": ChannelStatus.OBSERVED,
        "primary_domain": "b2b168.com",
        "aliases": ["b2b168.org"],
        "notes": (
            "【B2B 黄页】自助注册企业会员后发供应信息/商讯，普通会员免费；金钻会员与建站会员付费（"
            "建站约 500 元/年），首页推荐位另计。"
            "｜R1 真实采集（2026-11-27）域名级命中 4 次（b2b168.com 1 次、b2b168.org 3 次；"
            "只证明该域名被 AI 引用，未区分是否我方稿件），旧域名已登记为别名。"
            "｜合规：商讯正文不放电话/微信二维码，企业资质按平台要求上传。"
        ),
    },
    {
        "code": "zk71",
        "name": "中科商务网",
        "category": ChannelCategory.B2B,
        "status": ChannelStatus.OBSERVED,
        "primary_domain": "zk71.com",
        "aliases": [],
        "notes": (
            "【B2B 黄页】免费注册即可发布供应/求购，金牌推广会员约 1500 元/年，单条推广位约 700 元。"
            "｜R1 真实采集域名级命中 1 次（m.zk71.com，未区分是否我方稿件）。"
            "｜合规：医疗/教育类目需资质，正文禁留外链与联系方式。"
        ),
    },
    {
        "code": "51sole",
        "name": "搜了网",
        "category": ChannelCategory.B2B,
        "status": ChannelStatus.CANDIDATE,
        "primary_domain": "51sole.com",
        "aliases": [],
        "notes": (
            "【B2B 黄页】域名是 51sole.com（不是 soule.com）。免费注册企业黄页、发产品与资讯；"
            "黄金商铺/首页推广为付费位。｜R1 真实采集被引用 0 次，暂不投预算，先免费铺量观察。"
        ),
    },
    {
        "code": "soohoo",
        "name": "搜好货网",
        "category": ChannelCategory.B2B,
        "status": ChannelStatus.OBSERVED,
        "primary_domain": "912688.com",
        "aliases": [],
        "notes": (
            "【B2B 黄页】需企业资质认证后入驻，与百度爱采购联动；免费采通通会员已暂停新开。"
            "｜R1 真实采集域名级命中 1 次（未区分是否我方稿件）。"
            "｜合规：认证信息与营业执照一致，禁用绝对化用语。"
        ),
    },
    {
        "code": "zgsrcn",
        "name": "中国商人网",
        "category": ChannelCategory.INDUSTRY_MEDIA,
        "status": ChannelStatus.OBSERVED,
        "primary_domain": "zgsrcn.com",
        "aliases": [],
        "notes": (
            "【行业媒体·编辑制】《中国商人》杂志社官网，走投稿/合作，不能自助注册发稿。"
            "｜R1 真实采集域名级命中 3 次（未区分是否我方稿件），是本批次性价比最高的一站。"
            "｜合规：投稿需署真实主体，"
            "软文须标广告或合作，禁承诺保过/包就业。"
        ),
    },
    {
        "code": "100ec",
        "name": "网经社",
        "category": ChannelCategory.INDUSTRY_MEDIA,
        "status": ChannelStatus.OBSERVED,
        "primary_domain": "100ec.cn",
        "aliases": [],
        "notes": (
            "【行业媒体·合同制】不按篇零售，走年度合同：会员约 6 万/年、自媒体发布约 2 万/篇起，"
            "另有保证金与通道费，需先谈单篇试投。｜R1 真实采集域名级命中 1 次（未区分是否我方稿件）。"
            "｜合规：电商/教育类稿件需提供办学或经营资质。"
        ),
    },
    {
        "code": "haljl",
        "name": "海安零距离",
        "category": ChannelCategory.LOCAL_MEDIA,
        "status": ChannelStatus.OBSERVED,
        "primary_domain": "haljl.com",
        "aliases": [],
        "notes": (
            "【地方门户·论坛】江苏海安地方站（Discuz），注册即可发帖，审核较松。"
            "｜R1 真实采集域名级命中 1 次（未区分是否我方稿件）。"
            "｜地域与广州基地不匹配，只做低成本铺量与信源占位，不投预算。"
        ),
    },
    {
        "code": "51g3",
        "name": "云盟在线",
        "category": ChannelCategory.B2B,
        "status": ChannelStatus.CANDIDATE,
        "primary_domain": "51g3.com.cn",
        "aliases": [],
        "notes": (
            "【B2B 商贸】运营 18 年的企业商贸平台，自助发布供求与商情。"
            "｜R1 真实采集被引用 0 次，暂不投预算。"
        ),
    },
    {
        "code": "dzysw",
        "name": "大众艺术网",
        "category": ChannelCategory.INDUSTRY_MEDIA,
        "status": ChannelStatus.CANDIDATE,
        "primary_domain": "dzysw.com.cn",
        "aliases": [],
        "notes": (
            "【行业媒体·文化艺术】综合艺术门户，可投稿。｜R1 真实采集被引用 0 次；"
            "与招生/AIGC 培训业务关联弱，列为备选，不排期。"
        ),
    },
    {
        "code": "free-huangye",
        "name": "免费黄页网",
        "category": ChannelCategory.B2B,
        "status": ChannelStatus.CANDIDATE,
        "primary_domain": None,
        "aliases": [],
        "notes": (
            "【B2B 黄页】同名的站有多个（yellowurl.cn、gongsihuangye.com 等候选互相矛盾），"
            "域名待核验后再录 primary_domain，未核实前不参与域名观测。｜R1 真实采集被引用 0 次。"
        ),
    },
    {
        "code": "11467",
        "name": "顺企网",
        "category": ChannelCategory.B2B,
        "status": ChannelStatus.CANDIDATE,
        "primary_domain": "11467.com",
        "aliases": [],
        "notes": (
            "【B2B 黄页】免费入驻发布企业信息；会员 2880–29800 元/年，平台自己在卖"
            "「GEO 主推版 9800」，与其买会员不如自建内容。｜R1 真实采集被引用 0 次，"
            "只做免费铺量，不买会员。"
        ),
    },
    {
        "code": "liqing-online",
        "name": "沥青在线城市分站",
        "category": ChannelCategory.INDUSTRY_MEDIA,
        "status": ChannelStatus.CANDIDATE,
        "primary_domain": None,
        "aliases": [],
        "notes": (
            "【垂直行业站】沥青行业门户的城市分站，域名待核验，未核实前不参与域名观测。"
            "｜R1 真实采集被引用 0 次；与业务不匹配，仅登记备查，不排期。"
        ),
    },
    {
        "code": "assoc-ai-gd",
        "name": "广东省人工智能产业协会（公众号）",
        "category": ChannelCategory.INSTITUTION,
        "status": ChannelStatus.CANDIDATE,
        "primary_domain": None,
        "aliases": [],
        "notes": (
            "【协会公众号】不能自助注册，需会员单位身份或走投稿/活动合作。"
            "｜主域名留空：mp.weixin.qq.com 已归 wechat-mp，重复占用会撞唯一索引，"
            "本行只作发布洽谈标的与背书资源，不参与域名归因。"
        ),
    },
    {
        "code": "assoc-hr-gd",
        "name": "广东省人力资源管理协会（公众号）",
        "category": ChannelCategory.INSTITUTION,
        "status": ChannelStatus.CANDIDATE,
        "primary_domain": None,
        "aliases": [],
        "notes": (
            "【协会公众号】同上，需会员/投稿；主域名留空，只作洽谈标的与背书资源，不参与域名归因。"
        ),
    },
]

# 存量渠道的备注补强：追加引用计数与平台侧合规要求，不动分类/状态
NOTE_PATCHES: list[dict] = [
    {
        "code": "sohu",
        "append": (
            "｜R1 真实采集（2026-11-27）域名级命中 2 次（m.sohu.com，未区分是否我方稿件）。"
            "｜合规：搜狐教育类内容需《办学许可证》等资质核验，正文禁电话/微信/外链。"
        ),
    },
    {
        "code": "toutiao",
        "append": (
            "｜R1 真实采集（2026-11-27）域名级命中 1 次（未区分是否我方稿件）。"
            "｜合规：2026-10-20 起教育领域发布需资质认证，教育培训广告不得承诺保过/包就业。"
        ),
    },
]


def _append_note(current: str | None, extra: str) -> str:
    base = (current or "").strip()
    if extra.strip() in base:
        return base
    return f"{base}{extra}" if base else extra.strip()


def _resolve_project(db, code: str) -> Project:
    project = db.scalar(select(Project).where(Project.code == code))
    if project is None:
        raise SystemExit(f"未找到项目：{code}")
    return project


def _resolve_actor(db, username: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise SystemExit(f"未找到操作人：{username}")
    return user


def main() -> int:
    parser = argparse.ArgumentParser(description="补录 2026-11-27 渠道增补批次")
    parser.add_argument("--project-code", default=PROJECT_CODE)
    parser.add_argument("--actor", default="geo_admin", help="写入 submitted_by / reviewed_by 的用户名")
    parser.add_argument("--dry-run", action="store_true", help="只预演，不写库")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    created = skipped = patched = conflicts = 0

    with SessionLocal() as db:
        project = _resolve_project(db, args.project_code)
        actor = _resolve_actor(db, args.actor)

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
                ensure_primary_domain(
                    db, project_id=project.id, channel=None, domain=domain
                )
            except Exception as exc:  # AppError: channel_domain_conflict
                print(f"域名冲突，中止：{spec['code']} → {domain}（{exc}）")
                conflicts += 1
                break

            approved = spec["status"] is ChannelStatus.OBSERVED
            channel = Channel(
                project_id=project.id,
                code=spec["code"],
                name=spec["name"],
                category=spec["category"],
                status=spec["status"],
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
                decision_comment="历史已发布/已获引用渠道补录，按已准入登记" if approved else None,
            )
            db.add(channel)
            db.flush()

            for alias_domain in spec["aliases"]:
                db.add(
                    ChannelAlias(
                        project_id=project.id,
                        channel_id=channel.id,
                        domain=alias_domain,
                        alias_name=f"{spec['name']}（历史域名）",
                        notes="R1 采集命中的旧域名",
                    )
                )
            db.flush()

            approval = ChannelApproval(
                project_id=project.id,
                channel_id=channel.id,
                submitted_by=actor.id,
                submitted_at=now,
                reviewed_by=actor.id if approved else None,
                reviewed_at=now if approved else None,
                decision=ReviewDecision.APPROVED if approved else None,
                comment="历史已发布渠道补录" if approved else "补录候选渠道，待发布前审批",
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
                        "status": str(channel.status),
                        "primary_domain": channel.primary_domain,
                        "source": "backfill_2026_11_27",
                    },
                )
            print(
                f"新增 {channel.code:<14} {channel.name}｜{channel.category}｜{channel.status}"
                f"｜{channel.approval_status}｜{channel.primary_domain or '(域名待核验)'}"
            )
            created += 1

        if conflicts == 0:
            for patch in NOTE_PATCHES:
                channel = db.scalar(
                    select(Channel).where(
                        Channel.project_id == project.id, Channel.code == patch["code"]
                    )
                )
                if channel is None:
                    print(f"备注补强跳过 {patch['code']}（台账无此渠道）")
                    continue
                new_notes = _append_note(channel.notes, patch["append"])
                if new_notes == (channel.notes or ""):
                    print(f"备注补强跳过 {patch['code']}（已含本批次结论）")
                    continue
                channel.notes = new_notes
                patched += 1
                print(f"备注补强 {patch['code']}（{channel.name}）")

        if args.dry_run:
            db.rollback()
            mode = "预演（已回滚，未写库）"
        else:
            db.commit()
            mode = "已写库"

    print(
        f"合计：新增 {created} 条、跳过 {skipped} 条、备注补强 {patched} 条、域名冲突 {conflicts} 条；{mode}"
    )
    return 1 if conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
