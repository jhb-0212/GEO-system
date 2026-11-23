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


@pytest.fixture(autouse=True)
def _isolate_dotenv(monkeypatch):
    """测试只读进程环境，不读开发者本地 `.env`。

    生产读取顺序是“进程环境 → `.env` 白名单键”，但测试若继承真实 `.env`，
    “缺凭据应失败”的用例会被本机真实密钥干扰而失真。显式传 `env_paths` 的
    凭据单测不受影响。
    """
    from app.core import credentials

    monkeypatch.setattr(credentials, "ENV_PATHS", ())
    credentials._dotenv_credentials.cache_clear()
    yield
    credentials._dotenv_credentials.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_s3(monkeypatch):
    """测试默认走本地证据目录，避免开发者 `.env` 里的 S3 配置影响单测。"""
    for field in ("s3_endpoint", "s3_access_key", "s3_secret_key", "s3_bucket"):
        monkeypatch.setattr(settings, field, "")
    yield


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
        from app.models.industry import Organization

        org = db.scalar(select(Organization).where(Organization.code == "default-client"))
        if org is None:
            org = Organization(code="default-client", name="默认客户", status="active", branding={})
            db.add(org)
            db.flush()
        project = Project(
            code=code,
            name=name or f"测试项目-{code}",
            status=ProjectStatus.ACTIVE,
            timezone="Asia/Shanghai",
            organization_id=org.id,
        )
        db.add(project)
        db.flush()
        # 存量测试按「已选教育培训」的项目跑，保持既有断言；未选行业的场景单独测。
        from app.models.industry import ProjectStrategy

        db.add(
            ProjectStrategy(
                project_id=project.id,
                strategy_key="industry",
                config={"preset_code": "edu-training", "overrides": {}},
                version=1,
                status="active",
            )
        )
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
