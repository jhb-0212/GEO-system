"""归档内容条目：把联调残留稿退出统计与工作台列表。

## 为什么需要单独一个脚本

内容接口没有"归档"端点（`content.py` 只有创建 / 改正文 / 送审 / 审核 / 导出），
而 `DRAFT → ARCHIVED` 与 `APPROVED → ARCHIVED` 在状态机里都是合法流转
（`services/state_machine.CONTENT_TRANSITIONS`）。所以这里直接走状态机服务，
不自己拼状态，避免绕过校验。

同时补上审计：`action="content.archive"`，payload 记录 `from_status` / `to_status` /
`version_ids` / `reason`。接口侧没有这个动作名，本脚本是它的唯一来源，便于日后审计区分。

## 用法

先看哪些是可疑稿（正文 < 200 字，或标题含"联调/测试/mock"）：

    ... --all-suspicious
    ... --item 交付包联调
    ... --item 09ad3e29 --item 8390a8fd --apply --as geo_editor

归档需要 `content.write` 权限（本项目只有 `editor` 角色有），操作人必须显式指定。
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import (
    ContentItem,
    ContentVersion,
    Permission,
    Project,
    ProjectMember,
    RolePermission,
    User,
)
from app.models.enums import ContentStatus
from app.services.audit import record_audit
from app.services.state_machine import ensure_content_transition

REQUIRED_PERMISSION = "content.write"
SUSPICIOUS_MARKERS = ("联调", "测试", "mock", "demo", "样例数据")
MIN_BODY_LEN = 200


def _check_permission(db: Session, user: User, project: Project) -> str | None:
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


def _is_suspicious(item: ContentItem, versions: list[ContentVersion]) -> str | None:
    if any(m in item.title for m in SUSPICIOUS_MARKERS):
        return "标题含联调/测试字样"
    short = [v for v in versions if len(v.body or "") < MIN_BODY_LEN]
    if short:
        return f"正文过短（{min(len(v.body or '') for v in short)} 字）"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-code", default="gz-base")
    parser.add_argument("--item", action="append", help="条目 id 前 8 位或标题片段，可重复")
    parser.add_argument("--all-suspicious", action="store_true", help="自动挑出可疑联调稿")
    parser.add_argument("--reason", default="联调残留稿，退出内容统计")
    parser.add_argument("--as", dest="actor", help="操作人 username（--apply 时必填）")
    parser.add_argument("--apply", action="store_true", help="真正写库；不加只列清单")
    args = parser.parse_args()

    if not args.item and not args.all_suspicious:
        parser.print_help()
        return 2
    if args.apply and args.all_suspicious:
        print(
            "--all-suspicious 只用于列清单；确认后请用 --item 逐个指定，再 --apply。",
            file=sys.stderr,
        )
        return 2

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            print(f"找不到项目 {args.project_code}", file=sys.stderr)
            return 2

        items = list(
            db.scalars(select(ContentItem).where(ContentItem.project_id == project.id)).all()
        )
        versions: dict[uuid.UUID, list[ContentVersion]] = {}
        for version in db.scalars(
            select(ContentVersion).where(ContentVersion.project_id == project.id)
        ).all():
            versions.setdefault(version.item_id, []).append(version)

        targets: list[ContentItem] = []
        if args.all_suspicious:
            for item in items:
                if _is_suspicious(item, versions.get(item.id, [])):
                    targets.append(item)
        for token in args.item or []:
            matched = [
                i
                for i in items
                if str(i.id).startswith(token.lower()) or token in i.title
            ]
            if not matched:
                print(f"找不到条目：{token}", file=sys.stderr)
                return 2
            if len(matched) > 1:
                print(f"条目 {token} 匹配到 {len(matched)} 个，请用 id 前 8 位指定：", file=sys.stderr)
                for i in matched:
                    print(f"  {str(i.id)[:8]}  {i.title}", file=sys.stderr)
                return 2
            targets.append(matched[0])

        print(f"项目 {project.code}（{project.name}）")
        print(f"待归档条目：{len(targets)} 个\n")

        plan: list[tuple[ContentItem, list[ContentVersion], list[tuple[ContentVersion, ContentStatus, ContentStatus]]]] = []
        for item in targets:
            item_versions = versions.get(item.id, [])
            rows = []
            for version in item_versions:
                if version.status == ContentStatus.ARCHIVED:
                    continue
                # 走状态机校验：非法流转直接抛出，不做静默降级
                ensure_content_transition(version.status, ContentStatus.ARCHIVED)
                rows.append((version, version.status, ContentStatus.ARCHIVED))
            reason = _is_suspicious(item, item_versions) or "手动指定"
            print(f"{str(item.id)[:8]}  {item.title}")
            print(f"        状态 {item.status.value} → archived    理由：{reason}")
            for version, before, after in rows:
                print(f"        版本 v{version.version_no} {before.value} → {after.value}（{len(version.body or '')} 字）")
            if not rows:
                print("        已全部归档，跳过")
            plan.append((item, item_versions, rows))

        archivable = [p for p in plan if p[2]]
        if not archivable:
            print("\n没有需要归档的条目。")
            return 0

        if not args.apply:
            print("\n[dry-run] 未写入。加 --apply --as <username> 落库。")
            return 0

        if not args.actor:
            print("\n--apply 需要 --as <username>（写进审计）。", file=sys.stderr)
            return 2
        user = db.scalar(select(User).where(User.username == args.actor))
        if user is None:
            print(f"找不到用户 {args.actor}", file=sys.stderr)
            return 2
        denial = _check_permission(db, user, project)
        if denial:
            print(f"\n拒绝执行：{denial}", file=sys.stderr)
            return 3

        now = datetime.now(timezone.utc)
        archived_versions = 0
        for item, item_versions, rows in archivable:
            before_item = item.status
            # 条目级也走状态机，不能只校验版本
            item.status = ensure_content_transition(item.status, ContentStatus.ARCHIVED)
            for version, before, after in rows:
                version.status = after
                archived_versions += 1
            record_audit(
                db,
                project_id=project.id,
                actor_id=user.id,
                action="content.archive",
                target_type="content_item",
                target_id=item.id,
                payload={
                    "title": item.title,
                    "from_status": before_item.value,
                    "to_status": ContentStatus.ARCHIVED.value,
                    "version_ids": [str(v.id) for v, _, _ in rows],
                    "reason": args.reason,
                    "source": "archive_content_items_script",
                },
            )
        db.commit()
        print(f"\n已归档 {len(archivable)} 个条目、{archived_versions} 个版本（操作人 {user.username}）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
