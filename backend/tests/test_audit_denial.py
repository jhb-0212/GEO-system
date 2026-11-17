"""越权拒绝审计：必须留痕，但不能顺手提交调用方未完成的业务写入。"""

import uuid

from sqlalchemy import select

from app.models import AuditLog, Project
from app.models.enums import ProjectStatus
from app.services.audit import record_denial


def _pending_project() -> Project:
    code = f"denial-pending-{uuid.uuid4().hex[:6]}"
    return Project(
        code=code,
        name=f"未提交项目-{code}",
        status=ProjectStatus.ACTIVE,
        timezone="Asia/Shanghai",
    )


def test_record_denial_skips_commit_when_business_write_pending(db, project_factory, monkeypatch):
    project = project_factory(f"denial-{uuid.uuid4().hex[:6]}")
    db.add(_pending_project())  # 模拟请求里尚未提交的业务写入

    commits: list[str] = []
    monkeypatch.setattr(db, "commit", lambda: commits.append("commit"))

    row = record_denial(
        db,
        project_id=project.id,
        actor_id=None,
        reason="permission_denied",
    )

    assert commits == []
    assert row in db.new
    assert any(isinstance(obj, AuditLog) for obj in db.new)


def test_record_denial_skips_commit_after_business_flush(db, project_factory, monkeypatch):
    """业务写入已 flush 后不在 session.new 里，仍不能替调用方提交。"""
    project = project_factory(f"denial-{uuid.uuid4().hex[:6]}")
    db.add(_pending_project())
    db.flush()

    commits: list[str] = []
    monkeypatch.setattr(db, "commit", lambda: commits.append("commit"))

    row = record_denial(
        db,
        project_id=project.id,
        actor_id=None,
        reason="permission_denied",
    )

    assert commits == []
    assert any(isinstance(obj, AuditLog) for obj in db.new)
    assert row in db.new


def test_record_denial_commits_when_only_audit_is_pending(db, project_factory, monkeypatch):
    project = project_factory(f"denial-{uuid.uuid4().hex[:6]}")
    db.commit()  # 先落定业务写入，当前事务只剩待写的拒绝审计

    commits: list[str] = []
    original = db.commit

    def spy() -> None:
        commits.append("commit")
        original()

    monkeypatch.setattr(db, "commit", spy)

    record_denial(
        db,
        project_id=project.id,
        actor_id=None,
        reason="permission_denied",
    )

    assert commits == ["commit"]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "permission_denied")) is not None
