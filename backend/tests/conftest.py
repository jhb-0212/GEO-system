"""测试夹具：所有测试跑在同一个事务里，结束整体回滚，不污染开发库。"""

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.deps import get_project_context
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models import Project, ProjectMember, Role, User
from app.models.enums import ProjectStatus, RoleCode


@pytest.fixture(scope="session")
def engine():
    return create_engine(settings.database_url, pool_pre_ping=True)


@pytest.fixture()
def db(engine) -> Generator[Session, None, None]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db) -> Generator[TestClient, None, None]:
    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def project_factory(db):
    def _create(code: str, name: str | None = None) -> Project:
        project = Project(
            code=code,
            name=name or f"测试项目-{code}",
            status=ProjectStatus.ACTIVE,
            timezone="Asia/Shanghai",
        )
        db.add(project)
        db.flush()
        return project

    return _create


@pytest.fixture()
def user_factory(db):
    def _create(username: str, *, is_system_admin: bool = False) -> User:
        user = User(
            username=username,
            display_name=username,
            password_hash=hash_password("unit-test-password"),
            is_active=True,
            is_system_admin=is_system_admin,
        )
        db.add(user)
        db.flush()
        return user

    return _create


@pytest.fixture()
def member_factory(db):
    def _create(project: Project, user: User, role: RoleCode = RoleCode.EDITOR) -> ProjectMember:
        role_row = db.scalar(select(Role).where(Role.code == role))
        assert role_row is not None, f"角色 {role} 未初始化，先跑 scripts/seed.py"
        member = ProjectMember(
            project_id=project.id,
            user_id=user.id,
            role_id=role_row.id,
            is_active=True,
        )
        db.add(member)
        db.flush()
        return member

    return _create


@pytest.fixture()
def two_projects(project_factory):
    suffix = uuid.uuid4().hex[:6]
    p1 = project_factory(f"t1-{suffix}")
    p2 = project_factory(f"t2-{suffix}")
    return p1, p2


@pytest.fixture()
def context_for(db):
    def _build(project: Project, user: User):
        return get_project_context(project_id=project.id, user=user, db=db)

    return _build
