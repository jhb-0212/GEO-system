"""C2-4 真实链路夹具：建 3 个不同时区的项目 + 边界事实 + 各自的登录账号。

用途：真实后端 + 真实 PostgreSQL + 真实前端联调验收（不是 mock）。
每个项目写入 4 条事实，落在“今天窗口”的边界上，用来验证
数据库过滤 → API 窗口/计数 → 前端展示 这条完整链路：

    start-1s   （窗口外，左开）
    start      （窗口内，左闭）
    end-1s     （窗口内）
    end        （窗口外，右开）

预期 today=2，all=4，week 由脚本按周窗口单独核算（周一当天可能只有 3）。

用法（在 backend 目录，含 .env 指向目标库）：

    python scripts/c2_live_fixture.py                # 建数据并打印 JSON
    python scripts/c2_live_fixture.py --cleanup      # 删除本脚本建的账号/项目
    python scripts/c2_live_fixture.py > c2_live.json

注意：脚本是幂等“重建”——同名项目/用户先删后建，只清理 `c2live-` 前缀对象。
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, select, text  # noqa: E402

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Fact, Project, ProjectMember, Role, User
from app.models.enums import FactStatus, FactType, RoleCode
from app.services.time_windows import project_calendar

PREFIX = "c2live"
PASSWORD = "c2-live-pass"
ZONES = ("Asia/Shanghai", "America/New_York", "Europe/Berlin")


def _organization_id(db) -> uuid.UUID:
    row = db.execute(text("select id from organizations order by created_at limit 1")).scalar()
    if row is None:
        raise SystemExit("organizations 为空，先跑 scripts/seed.py")
    return row


def cleanup(db) -> int:
    projects = db.scalars(select(Project).where(Project.code.like(f"{PREFIX}-%"))).all()
    users = db.scalars(select(User).where(User.username.like(f"{PREFIX}-%"))).all()
    for project in projects:
        db.execute(delete(Fact).where(Fact.project_id == project.id))
        db.execute(delete(ProjectMember).where(ProjectMember.project_id == project.id))
        db.delete(project)
    for user in users:
        db.execute(delete(ProjectMember).where(ProjectMember.user_id == user.id))
        db.delete(user)
    db.commit()
    return len(projects) + len(users)


def create(db, now: datetime) -> list[dict]:
    organization_id = _organization_id(db)
    role = db.scalar(select(Role).where(Role.code == RoleCode.PROJECT_ADMIN))
    if role is None:
        raise SystemExit("roles 未初始化，先跑 scripts/seed.py")

    result: list[dict] = []
    for zone in ZONES:
        suffix = uuid.uuid4().hex[:6]
        code = f"{PREFIX}-{suffix}"
        username = f"{PREFIX}-{suffix}"

        project = Project(
            code=code,
            name=f"C2 联调 {zone}",
            organization_id=organization_id,
            timezone=zone,
            description="C2-4 真实链路夹具，可随时清理",
        )
        db.add(project)
        db.flush()

        user = User(
            username=username,
            display_name=f"C2 {zone}",
            password_hash=hash_password(PASSWORD),
            is_active=True,
            is_system_admin=False,
        )
        db.add(user)
        db.flush()
        db.add(ProjectMember(project_id=project.id, user_id=user.id, role_id=role.id, is_active=True))
        db.flush()

        calendar = project_calendar(project, now=now)
        today = calendar.window("today")
        week = calendar.window("week")
        stamps = {
            "start-1s": today.start - timedelta(seconds=1),
            "start": today.start,
            "end-1s": today.end - timedelta(seconds=1),
            "end": today.end,
        }
        for label, at in stamps.items():
            fact = Fact(
                project_id=project.id,
                fact_type=FactType.BASE_ADDRESS,
                fact_key=f"c2-{zone}-{label}",
                fact_value=f"C2 边界样本 {label}",
                approval_status=FactStatus.DRAFT,
                entered_todo_at=at,
                source_url="https://example.com/c2-live",
            )
            db.add(fact)
            db.flush()

        # 期望计数用打印出来的窗口边界做纯算术，不调用窗口函数
        inside_today = sum(1 for at in stamps.values() if today.start <= at < today.end)
        inside_week = sum(1 for at in stamps.values() if week.start <= at < week.end)
        result.append(
            {
                "timezone": zone,
                "project_id": str(project.id),
                "username": username,
                "password": PASSWORD,
                "window": {"start": today.start.isoformat(), "end": today.end.isoformat()},
                "week": {"start": week.start.isoformat(), "end": week.end.isoformat()},
                "expected": {"today": inside_today, "week": inside_week, "all": len(stamps)},
                "stamps": {label: at.isoformat() for label, at in stamps.items()},
            }
        )

    db.commit()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--now", help="固定当前时刻（ISO8601），默认取真实 now")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.cleanup:
            print(json.dumps({"removed": cleanup(db)}, ensure_ascii=False))
            return
        now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cleanup(db)
        payload = {
            "database": get_settings().database_url.rsplit("/", 1)[-1],
            "freeze_at": now.astimezone(UTC).isoformat(),
            "projects": create(db, now),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
