"""撤销按“来源域名”回填的 citation.channel_id。

项目口径（citation_attribution.py）：channel_id 只认发布回执里的真实 URL；
域名级匹配会把整站算成我们的渠道成果，必须撤销。只撤本次脚本写入的 120 条，
保留原本就由发布回执命中的行。
"""

from __future__ import annotations

import argparse
import json
import uuid

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Channel, MonitoringCitation, Project, User
from app.services.audit import record_audit

PROJECT_ID = uuid.UUID("154640d4-6356-4a1c-8bde-2d511cfb06cd")
EXACT_DOMAINS = {
    "mp.weixin.qq.com",
    "baijiahao.baidu.com",
    "sohu.com",
    "163.com",
    "toutiao.com",
    "baike.baidu.com",
    "bilibili.com",
    "woshipm.com",
    "weibo.com",
    "douyin.com",
    "zhidao.baidu.com",
    "zhipin.com",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        parser.error("必须指定 --dry-run 或 --apply")

    db = SessionLocal()
    try:
        project = db.get(Project, PROJECT_ID)
        actor = db.scalar(select(User).where(User.username == "geo_admin"))
        if not project or not actor:
            raise SystemExit("项目或执行人不存在")
        channels = db.execute(
            select(Channel.primary_domain, Channel.id)
            .where(Channel.project_id == PROJECT_ID, Channel.primary_domain.in_(EXACT_DOMAINS))
        ).all()
        channel_map = {domain: channel_id for domain, channel_id in channels}
        rows = db.scalars(
            select(MonitoringCitation).where(
                MonitoringCitation.project_id == PROJECT_ID,
                MonitoringCitation.channel_id.is_not(None),
                MonitoringCitation.domain.in_(list(channel_map)),
            )
        ).all()
        # 只撤“channel_id 正好等于该域名对应渠道”的行；若有人工改到别的渠道，保留。
        targets = [row for row in rows if row.channel_id == channel_map.get(row.domain)]
        if args.apply:
            for row in targets:
                row.channel_id = None
            db.flush()
            record_audit(
                db,
                project_id=PROJECT_ID,
                actor_id=actor.id,
                action="citation.channel_backfill_revert",
                target_type="monitoring_citation",
                target_id=None,
                payload={
                    "count": len(targets),
                    "reason": "domain_level_channel_backfill_is_invalid",
                    "note": "channel_id 只认发布回执 URL；来源域名不等于我们的发布渠道",
                    "domains": sorted({row.domain for row in targets}),
                },
            )
            db.commit()
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "reverted": len(targets),
                    "remaining_with_channel": int(
                        db.scalar(
                            select(func.count(MonitoringCitation.id)).where(
                                MonitoringCitation.project_id == PROJECT_ID,
                                MonitoringCitation.channel_id.is_not(None),
                            )
                        )
                        or 0
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
