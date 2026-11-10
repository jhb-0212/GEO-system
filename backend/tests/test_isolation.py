"""隔离测试：跨项目访问必须被拒绝；系统管理员没有项目授权时也不能读项目业务数据。"""

import uuid

import pytest

from app.core.errors import ProjectAccessError
from app.models import Channel
from app.models.enums import RoleCode
from app.services.project_scope import ensure_same_project, require_scoped_row, scoped_where


def test_member_of_other_project_is_rejected(context_for, two_projects, user_factory, member_factory):
    p1, p2 = two_projects
    user = user_factory(f"u-{uuid.uuid4().hex[:8]}")
    member_factory(p1, user, RoleCode.EDITOR)

    ctx = context_for(p1, user)
    assert ctx.role == RoleCode.EDITOR
    assert "question.write" in ctx.permissions

    with pytest.raises(ProjectAccessError):
        context_for(p2, user)


def test_system_admin_without_membership_is_rejected(context_for, two_projects, user_factory, member_factory):
    """系统管理员不默认拥有项目业务权限：先建项目，但读写项目数据必须被加入项目。"""
    p1, p2 = two_projects
    admin = user_factory(f"sys-{uuid.uuid4().hex[:8]}", is_system_admin=True)

    with pytest.raises(ProjectAccessError):
        context_for(p1, admin)

    member_factory(p2, admin, RoleCode.PROJECT_ADMIN)
    ctx = context_for(p2, admin)
    assert ctx.role == RoleCode.PROJECT_ADMIN
    assert ctx.is_system_admin is True
    assert "project.member.manage" in ctx.permissions
    # 系统级能力不来自项目角色
    assert "project.create" not in ctx.permissions


def test_capability_sets_match_role_boundaries(context_for, project_factory, user_factory, member_factory):
    project = project_factory(f"cap-{uuid.uuid4().hex[:6]}")
    expected = {
        RoleCode.VIEWER: ({"export.data", "lead.read"}, {"question.write", "content.write", "content.review"}),
        RoleCode.EDITOR: ({"content.write", "monitoring.execute"}, {"content.review", "project.member.manage", "lead.read"}),
        RoleCode.REVIEWER: ({"content.review", "evidence.review"}, {"content.write", "publish.execute"}),
        RoleCode.LEAD_OPS: ({"lead.read", "lead.write"}, {"monitoring.read", "evidence.read", "content.read", "publish.read"}),
        RoleCode.PROJECT_ADMIN: ({"project.member.manage", "content.review"}, {"content.write", "publish.execute"}),
    }
    for role, (has, lacks) in expected.items():
        user = user_factory(f"{role.value}-{uuid.uuid4().hex[:6]}")
        member_factory(project, user, role)
        perms = context_for(project, user).permissions
        assert has <= perms, f"{role} 缺少能力 {has - perms}"
        assert not (lacks & perms), f"{role} 不应拥有 {lacks & perms}"


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
