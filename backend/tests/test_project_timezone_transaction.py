"""项目时区事务原子性与并发审计链：真实数据库、独立 Session。"""

from __future__ import annotations

import threading
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.api.projects import update_project_timezone
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import AuditLog, Project, ProjectMember, Role, User
from app.models.enums import ProjectStatus, RoleCode
from app.models.industry import Organization
from app.schemas import ProjectTimezoneUpdate


def _persistent_project() -> dict[str, object]:
    session = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    try:
        org = session.scalar(select(Organization).where(Organization.code == "default-client"))
        role = session.scalar(select(Role).where(Role.code == RoleCode.PROJECT_ADMIN))
        assert org is not None and role is not None
        user = User(
            username=f"tz-tx-{suffix}",
            display_name="时区事务测试",
            password_hash=hash_password("test-only"),
            is_active=True,
        )
        project = Project(
            code=f"tz-tx-{suffix}",
            name="时区事务测试",
            status=ProjectStatus.ACTIVE,
            timezone="Asia/Shanghai",
            organization_id=org.id,
        )
        session.add_all([user, project])
        session.flush()
        session.add(
            ProjectMember(
                project_id=project.id,
                user_id=user.id,
                role_id=role.id,
                is_active=True,
                granted_by=user.id,
            )
        )
        session.commit()
        return {"project_id": project.id, "user_id": user.id}
    finally:
        session.close()


def _cleanup(project_id, user_id) -> None:
    session = SessionLocal()
    try:
        session.query(AuditLog).filter(AuditLog.project_id == project_id).delete()
        session.query(ProjectMember).filter(ProjectMember.project_id == project_id).delete()
        session.query(Project).filter(Project.id == project_id).delete()
        session.query(User).filter(User.id == user_id).delete()
        session.commit()
    finally:
        session.close()


def _context(project_id, user_id):
    session = SessionLocal()
    project = session.get(Project, project_id)
    user = session.get(User, user_id)
    assert project is not None and user is not None
    return session, SimpleNamespace(project=project, user=user, permissions=frozenset())


def test_audit_flush_failure_rolls_back_project_timezone():
    ids = _persistent_project()
    project_id, user_id = ids["project_id"], ids["user_id"]
    session = None
    try:
        session, ctx = _context(project_id, user_id)
        import app.api.projects as projects_api
        from app.models import AuditLog as AuditModel

        original = projects_api.record_audit

        def _broken_audit(db, **kwargs):
            # 真实数据库拒绝：action 超长，flush 时由 PostgreSQL 抛错。
            db.add(AuditModel(action="x" * 100, project_id=project_id))
            db.flush()

        projects_api.record_audit = _broken_audit
        try:
            with pytest.raises(Exception):
                update_project_timezone(
                    ProjectTimezoneUpdate(timezone="America/New_York"), ctx, session
                )
        finally:
            projects_api.record_audit = original

        verify = SessionLocal()
        try:
            project = verify.get(Project, project_id)
            assert project is not None
            assert project.timezone == "Asia/Shanghai"
            count = verify.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.project_id == project_id, AuditLog.action == "project.timezone.update")
            )
            assert count == 0
        finally:
            verify.close()
    finally:
        if session is not None:
            session.close()
        _cleanup(project_id, user_id)


def test_concurrent_timezone_updates_form_continuous_audit_chain():
    ids = _persistent_project()
    project_id, user_id = ids["project_id"], ids["user_id"]
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _change(target: str) -> None:
        session = None
        try:
            session, ctx = _context(project_id, user_id)
            barrier.wait(timeout=10)
            update_project_timezone(
                ProjectTimezoneUpdate(timezone=target), ctx, session
            )
        except BaseException as exc:  # noqa: BLE001 - 线程内异常回传给主线程
            errors.append(exc)
        finally:
            if session is not None:
                session.close()

    threads = [
        threading.Thread(target=_change, args=("America/New_York",)),
        threading.Thread(target=_change, args=("Asia/Tokyo",)),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        assert not errors, errors

        verify = SessionLocal()
        try:
            project = verify.get(Project, project_id)
            assert project is not None
            audits = verify.scalars(
                select(AuditLog)
                .where(AuditLog.project_id == project_id, AuditLog.action == "project.timezone.update")
                .order_by(AuditLog.serial_no)
            ).all()
            assert len(audits) == 2
            assert audits[0].payload["old_timezone"] == "Asia/Shanghai"
            assert audits[1].payload["old_timezone"] == audits[0].payload["new_timezone"]
            assert project.timezone == audits[1].payload["new_timezone"]
        finally:
            verify.close()
    finally:
        _cleanup(project_id, user_id)
