"""批量复核引用：把 `auto` 的引用一次性确认或驳回。

## 为什么需要这个脚本

`citation_rate` 的分母是有效回答，分子只数 `review_status='manual_confirmed'` 的引用
（见 `app/services/stats.py`）。而复核入口 `PATCH /citations/{id}` **一次只处理一条**，
一轮 24 格基线下大约会带出 40–60 条引用——让人在页面上逐条点不现实，结果就是：
样本有了、引用也有了，看板三个数（引用率 / 去重页面数 / 渠道数）**仍然全是 0**。

这个脚本把"逐条点"变成"按域名整批处理一次"，但**不绕过两件事**：

1. **权限**：`--as` 指定的操作人必须在本项目拥有 `evidence.review`
   （只有 `project_admin` / `reviewer` 有）。不带权限直接拒绝执行，不会退化成"谁都能改"。
2. **审计**：每条引用写一条 `audit_logs`，`action="citation.review"`、
   `target_type="monitoring_citation"`，与接口完全同格式，只是 payload 多了
   `source="bulk_script"` 与 `batch_id`，方便日后区分"人工点的"和"批量确认的"。

状态机与接口一致：**只能 auto → manual_confirmed / manual_rejected**，不能回写 auto。

## 用法

先看清单（默认 dry-run，不写库）：

    backend\\.venv\\Scripts\\python.exe backend\\scripts\\review_citations_bulk.py

按域名批量确认（先看一遍再决定）：

    ... --domain zhihu.com --domain bendibao.com --as geo_reviewer
    ... --domain zhihu.com --as geo_reviewer --apply

只处理某一轮 / 某个引擎 / 某道题：

    ... --round 2 --engine DeepSeek --question Q02
    ... --reject --domain example.com --as geo_reviewer --apply   # 驳回

## 判断口径提醒

批量确认的语义是"这条引用确实来自我们核过的那个页面/渠道"，**不是**"这条引用提到了我们"。
`is_brand_related` 是另一件事，本脚本不改它。
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Permission,
    Project,
    ProjectMember,
    Question,
    QuestionVersion,
    RolePermission,
    User,
)
from app.models.enums import CitationReviewStatus
from app.services.audit import record_audit

REQUIRED_PERMISSION = "evidence.review"


def _domain_of(raw_url: str, stored: str | None) -> str:
    if stored:
        return stored.lower()
    try:
        host = urlparse(raw_url).hostname or ""
    except ValueError:
        return ""
    return host.lower()


def _check_permission(db: Session, user: User, project: Project) -> str | None:
    """返回 None 表示有权限；否则返回拒绝原因。"""
    if user.is_system_admin:
        return None
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
            ProjectMember.is_active.is_(True),
        )
    )
    if member is None:
        return f"用户 {user.username} 不是项目 {project.code} 的成员"
    allowed = db.scalar(
        select(RolePermission.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            RolePermission.role_id == member.role_id,
            Permission.code == REQUIRED_PERMISSION,
        )
    )
    if allowed is None:
        return f"用户 {user.username} 的角色没有 {REQUIRED_PERMISSION} 权限"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-code", required=True, help="项目 code，必须显式指定")
    parser.add_argument("--round", type=int, help="只处理指定序号的轮次")
    parser.add_argument("--engine", help="引擎名包含该字符串（如 DeepSeek）")
    parser.add_argument("--question", help="题目 code（如 Q02）")
    parser.add_argument("--domain", action="append", help="只处理这些域名，可重复传")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条（0 = 不限）")
    parser.add_argument("--reject", action="store_true", help="驳回而不是确认")
    parser.add_argument("--note", help="写入 review_note")
    parser.add_argument("--as", dest="actor", help="操作人 username（--apply 时必填）")
    parser.add_argument("--apply", action="store_true", help="真正写库；不加只列清单")
    args = parser.parse_args()

    target_status = (
        CitationReviewStatus.MANUAL_REJECTED if args.reject else CitationReviewStatus.MANUAL_CONFIRMED
    )

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            print(f"找不到项目 {args.project_code}", file=sys.stderr)
            return 2

        query = (
            select(MonitoringCitation)
            .join(MonitoringSample, MonitoringSample.id == MonitoringCitation.sample_id)
            .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
            .join(MonitoringRound, MonitoringRound.id == MonitoringTask.round_id)
            .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
            .join(Question, Question.id == QuestionVersion.question_id)
            .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
            .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
            .where(
                MonitoringCitation.project_id == project.id,
                MonitoringCitation.review_status == CitationReviewStatus.AUTO,
            )
            .order_by(MonitoringCitation.domain, MonitoringCitation.raw_url)
        )
        if args.round is not None:
            query = query.where(MonitoringRound.seq == args.round)
        if args.engine:
            query = query.where(AiEngine.name.ilike(f"%{args.engine}%"))
        if args.question:
            query = query.where(Question.code == args.question)

        if args.domain:
            wanted = sorted({d.lower().strip() for d in args.domain})
            query = query.where(func.lower(MonitoringCitation.domain).in_(wanted))
        if args.limit and args.limit > 0:
            query = query.limit(args.limit)

        rows = list(db.scalars(query).all())

        # 按域名分组展示：批量复核是"按信源判"，不是"逐条读"
        by_domain: dict[str, list[MonitoringCitation]] = {}
        for row in rows:
            by_domain.setdefault(_domain_of(row.raw_url, row.domain) or "(未知域名)", []).append(row)

        print(f"项目 {project.code}（{project.name}）")
        print(f"待复核引用（review_status=auto）：{len(rows)} 条，来自 {len(by_domain)} 个域名")
        if not rows:
            print("没有需要处理的引用。")
            return 0

        print(f"\n目标状态：{target_status.value}")
        print(f"{'域名':<32}{'条数':>4}  样例 URL")
        for domain in sorted(by_domain, key=lambda d: (-len(by_domain[d]), d)):
            items = by_domain[domain]
            sample = items[0].raw_url
            print(f"{domain:<32}{len(items):>4}  {sample[:96]}")

        if not args.apply:
            print("\n[dry-run] 未写入。加 --apply --as <username> 落库。")
            print("提示：先用 --domain 缩到一两个域名试一批，再放开。")
            return 0

        if not args.actor:
            print("\n--apply 需要 --as <username> 指定操作人（写进 reviewed_by 与审计）。", file=sys.stderr)
            return 2

        user = db.scalar(select(User).where(User.username == args.actor))
        if user is None:
            print(f"找不到用户 {args.actor}", file=sys.stderr)
            return 2
        denial = _check_permission(db, user, project)
        if denial:
            # 权限不足直接拒绝，不落库，也不写审计（与接口的 permission_denied 语义一致）
            print(f"\n拒绝执行：{denial}", file=sys.stderr)
            return 3

        now = datetime.now(timezone.utc)
        batch_id = uuid.uuid4().hex[:12]
        for index, row in enumerate(rows, start=1):
            row.review_status = target_status
            row.reviewed_by = user.id
            row.reviewed_at = now
            if args.note is not None:
                row.review_note = args.note
            record_audit(
                db,
                project_id=project.id,
                actor_id=user.id,
                action="citation.review",
                target_type="monitoring_citation",
                target_id=row.id,
                payload={
                    "review_status": target_status.value,
                    "channel_id": str(row.channel_id) if row.channel_id else None,
                    "competitor_id": str(row.competitor_id) if row.competitor_id else None,
                    "source": "bulk_script",
                    "batch_id": batch_id,
                },
            )
            if index % 500 == 0:
                # 按批提交，避免一次长事务把整表锁在批量复核期间
                db.commit()
        db.commit()

        remaining = db.scalar(
            select(MonitoringCitation.id)
            .where(
                MonitoringCitation.project_id == project.id,
                MonitoringCitation.review_status == CitationReviewStatus.AUTO,
            )
            .limit(1)
        )
        left = db.execute(
            select(MonitoringCitation.review_status, func.count())
            .where(MonitoringCitation.project_id == project.id)
            .group_by(MonitoringCitation.review_status)
        ).all()

        print(f"\n已写入 {len(rows)} 条（batch_id={batch_id}，操作人={user.username}）。")
        for status, count in left:
            print(f"  {status.value}: {count}")
        if remaining is None:
            print("\n全部引用已复核完毕，citation_rate 的分母/分子现在都有数了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
