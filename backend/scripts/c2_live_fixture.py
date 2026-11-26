"""C2-4 真实链路夹具：建 3 个不同时区的项目 + 边界事实 + 各自的登录账号。

用途：真实后端 + 真实 PostgreSQL + 真实前端联调验收（不是 mock）。
每个项目写入 4 条事实，落在“今天窗口”的边界上，用来验证
数据库过滤 → API 窗口/计数 → 前端展示 这条完整链路：

    start-1s   （窗口外，左开）
    start      （窗口内，左闭）
    end-1s     （窗口内）
    end        （窗口外，右开）

预期 today=2，all=4，week 由脚本按周窗口单独核算（周一当天可能只有 3）。

安全约束（本脚本会在真实库上删数据，必须 fail-closed）：
1. 数据库身份用 SQLAlchemy URL 解析，不用字符串切分；
2. 默认只允许 `geo_dev_migrated`，其他库直接拒绝；需要加库时显式设
   `C2_LIVE_ALLOW_DATABASES="db1,db2"`；
3. 每次创建生成独立 `fixture_run_id`，项目/账号名前缀都带这个 ID；
4. 清理只接受本次创建的 manifest，按精确 UUID 删除，不再按 `c2live-%` 扫描；
5. 清理前打印库名、fixture ID、待删除对象数量；库或 manifest 不匹配则拒绝。

用法（在 backend 目录，含 .env 指向目标库）：

    python scripts/c2_live_fixture.py --manifest c2_live.json
    python scripts/c2_live_fixture.py --cleanup --manifest c2_live.json

注意：本脚本用 `project_calendar()` 取窗口边界，不是独立的日历算法 oracle；
独立的硬编码 UTC 期望在 `tests/test_dst_matrix_e2e.py` 中。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, func, select, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import Fact, Project, ProjectMember, Role, User  # noqa: E402
from app.models.enums import FactStatus, FactType, RoleCode  # noqa: E402
from app.services.time_windows import project_calendar  # noqa: E402

PREFIX = "c2live"
PASSWORD = "c2-live-pass"
ZONES = ("Asia/Shanghai", "America/New_York", "Europe/Berlin")
ZONE_SLUGS = {"Asia/Shanghai": "sh", "America/New_York": "ny", "Europe/Berlin": "bl"}

DEFAULT_ALLOWED_DATABASES = frozenset({"geo_dev_migrated"})
ALLOW_ENV = "C2_LIVE_ALLOW_DATABASES"


class FixtureRefused(SystemExit):
    """安全校验不通过：直接终止，不做任何写/删。"""


def database_name(url: str) -> str:
    """用 SQLAlchemy URL 解析库名，避免 `rsplit("/")` 在带参数/路径时误判。"""
    return make_url(url).database or ""


def allowed_databases() -> set[str]:
    extra = {item.strip() for item in os.getenv(ALLOW_ENV, "").split(",") if item.strip()}
    return set(DEFAULT_ALLOWED_DATABASES) | extra


def assert_database_allowed(name: str) -> None:
    allowed = allowed_databases()
    if name not in allowed:
        raise FixtureRefused(
            f"拒绝执行：当前库 {name!r} 不在允许列表 {sorted(allowed)}。"
            f"确认是开发/验收库后，重跑并显式设置 {ALLOW_ENV}。"
        )


def _organization_id(db) -> uuid.UUID:
    row = db.execute(text("select id from organizations order by created_at limit 1")).scalar()
    if row is None:
        raise FixtureRefused("organizations 为空，先跑 scripts/seed.py")
    return row


def _role_id(db) -> uuid.UUID:
    role = db.scalar(select(Role).where(Role.code == RoleCode.PROJECT_ADMIN))
    if role is None:
        raise FixtureRefused("roles 未初始化，先跑 scripts/seed.py")
    return role.id


def create(db, now: datetime, run_id: str) -> dict:
    organization_id = _organization_id(db)
    role_id = _role_id(db)
    items: list[dict] = []

    for zone in ZONES:
        suffix = uuid.uuid4().hex[:4]
        slug = ZONE_SLUGS[zone]
        # project.code 上限 32 字符：c2live-<run8>-<slug>-<suffix>
        code = f"{PREFIX}-{run_id}-{slug}-{suffix}"
        username = f"{PREFIX}-{run_id}-{slug}-{suffix}"

        project = Project(
            code=code,
            name=f"C2 联调 {zone}",
            organization_id=organization_id,
            timezone=zone,
            description=f"C2-4 真实链路夹具（run {run_id}），用 manifest 清理",
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
        db.add(ProjectMember(project_id=project.id, user_id=user.id, role_id=role_id, is_active=True))
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
        facts: list[str] = []
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
            facts.append(str(fact.id))

        # 期望计数只用打印出来的窗口边界做纯算术，不调用窗口函数；
        # 但这只是“同一窗口下的区间比较”，不构成独立算法 oracle。
        inside_today = sum(1 for at in stamps.values() if today.start <= at < today.end)
        inside_week = sum(1 for at in stamps.values() if week.start <= at < week.end)
        items.append(
            {
                "timezone": zone,
                "project_id": str(project.id),
                "project_code": code,
                "user_id": str(user.id),
                "username": username,
                "password": PASSWORD,
                "window": {"start": today.start.isoformat(), "end": today.end.isoformat()},
                "week": {"start": week.start.isoformat(), "end": week.end.isoformat()},
                "expected": {"today": inside_today, "week": inside_week, "all": len(stamps)},
                "stamps": {label: at.isoformat() for label, at in stamps.items()},
                "fact_ids": facts,
            }
        )

    db.commit()
    return {
        "fixture_run_id": run_id,
        "database": database_name(get_settings().database_url),
        "created_at": now.astimezone(UTC).isoformat(),
        "projects": items,
    }


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        raise FixtureRefused(f"找不到 manifest：{path}。清理必须提供本次创建的 manifest。")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureRefused(f"manifest 不是合法 JSON：{path}") from exc
    for key in ("fixture_run_id", "database", "projects"):
        if key not in manifest:
            raise FixtureRefused(f"manifest 缺少字段 {key!r}，拒绝清理")
    if not manifest["projects"]:
        raise FixtureRefused("manifest 没有项目，拒绝清理")
    return manifest


def cleanup(db, manifest: dict, db_name: str) -> dict:
    if manifest["database"] != db_name:
        raise FixtureRefused(
            f"拒绝清理：manifest 属于库 {manifest['database']!r}，当前库是 {db_name!r}"
        )

    run_id = str(manifest["fixture_run_id"])
    project_ids: list[uuid.UUID] = []
    user_ids: list[uuid.UUID] = []
    for item in manifest["projects"]:
        code = str(item.get("project_code", ""))
        if not code.startswith(f"{PREFIX}-{run_id}-"):
            raise FixtureRefused(f"manifest 项目 {code!r} 不属于 run {run_id}，拒绝清理")
        try:
            project_ids.append(uuid.UUID(item["project_id"]))
            user_ids.append(uuid.UUID(item["user_id"]))
        except (KeyError, ValueError) as exc:
            raise FixtureRefused("manifest 中的 project_id/user_id 不是合法 UUID") from exc

    existing_projects = db.scalars(select(Project).where(Project.id.in_(project_ids))).all()
    existing_users = db.scalars(select(User).where(User.id.in_(user_ids))).all()
    fact_count = db.scalar(select(func.count()).select_from(Fact).where(Fact.project_id.in_(project_ids)))
    member_count = db.scalar(
        select(func.count()).select_from(ProjectMember).where(ProjectMember.project_id.in_(project_ids))
    )

    summary = {
        "database": db_name,
        "fixture_run_id": run_id,
        "manifest_projects": len(project_ids),
        "projects_found": len(existing_projects),
        "users_found": len(existing_users),
        "facts_to_delete": int(fact_count or 0),
        "members_to_delete": int(member_count or 0),
    }
    print(json.dumps({"cleanup_plan": summary}, ensure_ascii=False), file=sys.stderr)
    if len(existing_projects) != len(project_ids):
        raise FixtureRefused("manifest 中的项目在当前库不存在或数量不符，拒绝清理（可能连错库）")

    db.execute(delete(Fact).where(Fact.project_id.in_(project_ids)))
    db.execute(delete(ProjectMember).where(ProjectMember.project_id.in_(project_ids)))
    for project in existing_projects:
        db.delete(project)
    for user in existing_users:
        db.delete(user)
    db.commit()
    return summary


def _fixture_payload(manifest: dict) -> dict:
    """不把密码写进 manifest 之外的输出；manifest 本身含账号，视为验收凭据。"""
    return {
        "database": manifest["database"],
        "fixture_run_id": manifest["fixture_run_id"],
        "freeze_at": manifest["created_at"],
        "projects": manifest["projects"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true", help="按 manifest 精确清理本次夹具")
    parser.add_argument("--manifest", default="c2_live_manifest.json", help="manifest 路径（创建时写入、清理时读取）")
    parser.add_argument("--now", help="固定当前时刻（ISO8601），默认取真实 now")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser().resolve()
    db_name = database_name(get_settings().database_url)
    assert_database_allowed(db_name)

    with SessionLocal() as db:
        if args.cleanup:
            manifest = _load_manifest(manifest_path)
            summary = cleanup(db, manifest, db_name)
            print(json.dumps({"removed": summary}, ensure_ascii=False))
            return

        now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        run_id = uuid.uuid4().hex[:8]
        manifest = create(db, now, run_id)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {"written_manifest": str(manifest_path), "database": db_name, "fixture_run_id": run_id},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        print(json.dumps(_fixture_payload(manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
