"""把 R1 真实采集里出现过的国内信源域名补进 `gz-base` 渠道台账（第四批）。

数据源：`backend/data/source_domains_2026_11_27.csv`
- 前 51 行来自 `GEO_R1_真实采集_2026-11-27/citations.csv` 的域名聚合（140 条引用、
  102 个域名按根域归并后剩下的国内站点），备注里带各自的域名级命中次数；
- 后 10 行是 R1 未命中但属于主流权威媒体的补充信源（人民网/新华网/央视网等）。

口径：
- `status=observed`（R1 有命中）或 `candidate`（补充信源）；
- 全部 `pending_review`：这批只做**信源池**，没有账号、没有报价、没有发布事实，
  不预设可发布，避免被误算成渠道效果；
- 备注统一带「信源」标记与 R1 命中次数，并声明「域名级命中，未区分是否我方稿件」。

去重：主域名或别名已存在的跳过；code 冲突时自动加后缀。幂等。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_source_domains_2026_11_27.py --dry-run
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\backfill_source_domains_2026_11_27.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Channel, ChannelAlias, ChannelApproval, Project, User
from app.models.enums import ChannelApprovalStatus, ChannelCategory, ChannelStatus
from app.services.channel_registry import ensure_alias, ensure_primary_domain

PROJECT_CODE = "gz-base"
OWNER = "渠道运营组"
CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "source_domains_2026_11_27.csv"

# 与存量台账同主体的特殊说明
EXTRA_NOTES = {
    "zhinengxiehui.com": "｜同主体说明：台账 assoc-ai-gd 是协会公众号，本行是协会官网，两者分开归因。",
}


def _code_for(domain: str) -> str:
    code = domain.split(".")[0]
    return code.replace("_", "-")[:64]


def _pick_code(db, project_id, domain: str) -> str:
    base = _code_for(domain)
    code = base
    index = 2
    while db.scalar(
        select(Channel.id).where(Channel.project_id == project_id, Channel.code == code)
    ):
        code = f"{base}-{index}"
        index += 1
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="补录 R1 信源域名")
    parser.add_argument("--project-code", default=PROJECT_CODE)
    parser.add_argument("--actor", default="geo_admin")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not CSV_PATH.exists():
        raise SystemExit(f"数据文件不存在：{CSV_PATH}")

    now = datetime.now(timezone.utc)
    created = skipped = conflicts = 0

    with open(CSV_PATH, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            raise SystemExit(f"未找到项目：{args.project_code}")
        actor = db.scalar(select(User).where(User.username == args.actor))
        if actor is None:
            raise SystemExit(f"未找到操作人：{args.actor}")

        for row in rows:
            domain = row["domain"].strip().lower()
            name = row["name"].strip()
            category = ChannelCategory(row["category"].strip())
            aliases = [a.strip().lower() for a in row["aliases"].split(",") if a.strip()]
            count = int(row["r1_count"] or 0)
            brand = int(row["brand_count"] or 0)

            existing_domain = db.scalar(
                select(Channel).where(
                    Channel.project_id == project.id, Channel.primary_domain == domain
                )
            )
            existing_alias = db.scalar(
                select(ChannelAlias).where(
                    ChannelAlias.project_id == project.id, ChannelAlias.domain == domain
                )
            )
            if existing_domain is not None or existing_alias is not None:
                print(f"跳过 {domain}（已在台账）")
                skipped += 1
                continue

            try:
                ensure_primary_domain(db, project_id=project.id, channel=None, domain=domain)
            except Exception as exc:
                print(f"域名冲突，跳过：{domain}（{exc}）")
                conflicts += 1
                continue

            code = _pick_code(db, project.id, domain)
            note_head = "【R1 信源】" if count else "【补充信源·主流媒体】"
            notes = f"{note_head}{row['note'].strip()}{EXTRA_NOTES.get(domain, '')}"

            channel = Channel(
                project_id=project.id,
                code=code,
                name=name,
                category=category,
                status=ChannelStatus.OBSERVED if count else ChannelStatus.CANDIDATE,
                primary_domain=domain,
                publish_url=None,
                login_url=None,
                owner_name=OWNER,
                owner_contact=None,
                notes=notes,
                is_active=True,
                approval_status=ChannelApprovalStatus.PENDING_REVIEW,
                submitted_by=actor.id,
                submitted_at=now,
            )
            db.add(channel)
            db.flush()

            for alias in aliases:
                ensure_alias(
                    db, project_id=project.id, channel=channel, domain=alias, alias_name=name
                )

            db.add(
                ChannelApproval(
                    project_id=project.id,
                    channel_id=channel.id,
                    submitted_by=actor.id,
                    submitted_at=now,
                    comment="信源池补录：仅域名观测，未建发布账号",
                )
            )
            print(f"新增 {code:<18} {name}｜{category}｜{'命中 %d' % count if count else '补充'}")
            created += 1

        if args.dry_run:
            db.rollback()
            mode = "预演（已回滚，未写库）"
        else:
            db.commit()
            mode = "已写库"

    print(f"合计：新增 {created}、跳过 {skipped}、冲突 {conflicts}；{mode}")
    return 1 if conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
