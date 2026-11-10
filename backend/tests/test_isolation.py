"""隔离测试：跨项目访问必须被拒绝，项目内授权按角色判断。"""

import uuid

import pytest

from app.api.deps import require_project_role
from app.core.errors import InsufficientRoleError, ProjectAccessError
from app.models import Channel
from app.models.enums import RoleCode
from app.services.project_scope import ensure_same_project, require_scoped_row, scoped_where


def test_member_of_other_project_is_rejected(context_for, two_projects, user_factory, member_factory):
    p1, p2 = two_projects
    user = user_factory(f"u-{uuid.uuid4().hex[:8]}")
    member_factory(p1, user, RoleCode.EDITOR)

    ctx = context_for(p1, user)
    assert ctx.role == RoleCode.EDITOR

    with pytest.raises(ProjectAccessError):
        context_for(p2, user)


def test_system_admin_can_cross_projects(context_for, two_projects, user_factory):
    p1, p2 = two_projects
    admin = user_factory(f"admin-{uuid.uuid4().hex[:8]}", is_system_admin=True)
    ctx = context_for(p2, admin)
    assert ctx.is_system_admin is True
    assert ctx.role == RoleCode.ADMIN


def test_role_gate_blocks_insufficient_role(context_for, project_factory, user_factory, member_factory):
    project = project_factory(f"gate-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"viewer-{uuid.uuid4().hex[:8]}")
    member_factory(project, viewer, RoleCode.VIEWER)
    ctx = context_for(project, viewer)

    gate = require_project_role(RoleCode.REVIEWER, RoleCode.ADMIN)
    with pytest.raises(InsufficientRoleError):
        gate(ctx=ctx)

    assert gate(ctx=context_for(project, _admin(user_factory, project, member_factory))).role == RoleCode.ADMIN


def _admin(user_factory, project, member_factory):
    admin = user_factory(f"padm-{uuid.uuid4().hex[:8]}")
    member_factory(project, admin, RoleCode.ADMIN)
    return admin


def test_record_from_other_project_is_not_readable(db, two_projects):
    p1, p2 = two_projects
    channel = Channel(
        project_id=p1.id,
        code=f"ch-{uuid.uuid4().hex[:6]}",
        name="渠道",
        category="content_platform",
        status="candidate",
    )
    db.add(channel)
    db.flush()

    assert db.scalar(scoped_where(Channel, p1.id, Channel.id == channel.id)) is not None
    assert db.scalar(scoped_where(Channel, p2.id, Channel.id == channel.id)) is None

    ensure_same_project(channel, p1.id)
    with pytest.raises(ProjectAccessError):
        ensure_same_project(channel, p2.id)

    with pytest.raises(ProjectAccessError):
        require_scoped_row(db, Channel, p2.id, resource="channel", id=channel.id)
