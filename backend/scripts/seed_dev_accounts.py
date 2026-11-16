"""Create local-only project role accounts without storing passwords in Git.

Set GEO_DEV_EDITOR_PASSWORD, GEO_DEV_REVIEWER_PASSWORD,
GEO_DEV_LEAD_OPS_PASSWORD, or GEO_DEV_VIEWER_PASSWORD to create the
corresponding account. Existing passwords and role assignments are preserved.
"""

import os
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import Project, ProjectMember, Role, User  # noqa: E402
from app.models.enums import RoleCode  # noqa: E402


ACCOUNTS = (
    ("geo_editor", RoleCode.EDITOR, "GEO_DEV_EDITOR_PASSWORD"),
    ("geo_reviewer", RoleCode.REVIEWER, "GEO_DEV_REVIEWER_PASSWORD"),
    ("geo_lead_ops", RoleCode.LEAD_OPS, "GEO_DEV_LEAD_OPS_PASSWORD"),
    ("geo_viewer", RoleCode.VIEWER, "GEO_DEV_VIEWER_PASSWORD"),
)


def main() -> None:
    if settings.app_env.lower() not in {"dev", "local", "test"}:
        raise SystemExit("只允许在本地开发/测试环境创建联调账号")
    project_code = sys.argv[1] if len(sys.argv) > 1 else "gz-base"
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == project_code))
        if project is None:
            raise SystemExit(f"项目 {project_code} 不存在；请先执行 seed.py")
        for username, role_code, env_name in ACCOUNTS:
            password = os.getenv(env_name)
            if not password:
                continue
            if len(password) < 12:
                raise SystemExit(f"{env_name} 至少 12 个字符")
            role = db.scalar(select(Role).where(Role.code == role_code))
            if role is None:
                raise SystemExit(f"角色 {role_code.value} 不存在；请先执行 seed.py")
            user = db.scalar(select(User).where(User.username == username))
            if user is None:
                user = User(username=username, display_name=username, password_hash=hash_password(password),
                            is_active=True, is_system_admin=False)
                db.add(user)
                db.flush()
                print(f"已创建 {username}；密码只读取环境变量")
            membership = db.scalar(select(ProjectMember).where(
                ProjectMember.project_id == project.id, ProjectMember.user_id == user.id,
            ))
            if membership is None:
                db.add(ProjectMember(project_id=project.id, user_id=user.id, role_id=role.id, is_active=True))
                print(f"已加入 {username} → {project_code} / {role_code.value}")
            elif membership.role_id != role.id or not membership.is_active:
                print(f"已存在 {username} 的其他角色或停用记录；未改动，请人工复核")
            else:
                print(f"{username} 已存在；密码与成员关系未改动")
        db.commit()


if __name__ == "__main__":
    main()
