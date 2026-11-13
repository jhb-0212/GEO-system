"""seed 角色账号：只补缺失、幂等、生产拒绝默认弱密码。"""

from __future__ import annotations

import uuid

import pytest

from app.models import ProjectMember, Role, User
from app.models.enums import RoleCode
from scripts import seed


def test_seed_project_role_users_creates_four_accounts_and_is_idempotent(
    db, project_factory, monkeypatch
):
    suffix = uuid.uuid4().hex[:6]
    rows = [
        (f"seed_editor_{suffix}", "编辑", RoleCode.EDITOR),
        (f"seed_reviewer_{suffix}", "审核", RoleCode.REVIEWER),
        (f"seed_lead_{suffix}", "招生", RoleCode.LEAD_OPS),
        (f"seed_viewer_{suffix}", "只读", RoleCode.VIEWER),
    ]
    monkeypatch.setattr(seed, "ROLE_USER_SEED", rows)
    monkeypatch.delenv(seed.ROLE_USER_PASSWORD_ENV, raising=False)
    project = project_factory(f"seed-{suffix}")

    created_users, created_members = seed.seed_project_role_users(db, project)
    assert created_users == 4
    assert created_members == 4

    users = [db.get(User, db.scalar(seed.select(User.id).where(User.username == name))) for name, _, _ in rows]
    assert all(user is not None and user.is_active for user in users)
    assert all(user.is_system_admin is False for user in users)

    members = list(
        db.scalars(
            seed.select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id.in_([user.id for user in users]),
            )
        )
    )
    assert len(members) == 4
    role_by_code = {row.code: row for row in db.scalars(seed.select(Role))}
    role_by_username = {name: role_code for name, _, role_code in rows}
    for member in members:
        user = db.get(User, member.user_id)
        assert user is not None
        assert member.role_id == role_by_code[role_by_username[user.username]].id

    again = seed.seed_project_role_users(db, project)
    assert again == (0, 0)


def test_seed_project_role_users_prod_requires_password(
    db, project_factory, monkeypatch
):
    project = project_factory(f"seed-prod-{uuid.uuid4().hex[:6]}")
    monkeypatch.setattr(seed.settings, "app_env", "prod")
    monkeypatch.delenv(seed.ROLE_USER_PASSWORD_ENV, raising=False)
    with pytest.raises(SystemExit, match=seed.ROLE_USER_PASSWORD_ENV):
        seed.seed_project_role_users(db, project)
