"""Real login and token invalidation through the public HTTP API."""

import uuid

import jwt
import pytest

from app.core.config import settings
from app.core.security import create_access_token
from app.models.enums import RoleCode


def test_login_me_and_bad_credentials(client, db, project_factory, user_factory, member_factory):
    project = project_factory("auth-project")
    user = user_factory("auth-editor")
    member_factory(project, user, RoleCode.EDITOR)

    bad = client.post("/api/v1/auth/login", json={"username": user.username, "password": "wrong"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_credentials"
    assert user.last_login_at is None

    response = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "unit-test-password"},
    )
    assert response.status_code == 200
    assert user.last_login_at is not None
    token = response.json()["data"]["access_token"]
    assert jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])["tv"] == 0

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["data"]["username"] == user.username
    assert me.json()["data"]["projects"][0]["id"] == str(project.id)
    assert "monitoring.execute" in me.json()["data"]["projects"][0]["permissions"]
    assert "password_hash" not in me.text


@pytest.mark.parametrize(
    ("role", "resource", "permission"),
    [
        (RoleCode.PROJECT_ADMIN, "members", "project.member.manage"),
        (RoleCode.EDITOR, "monitoring/rounds", "monitoring.read"),
        (RoleCode.REVIEWER, "audit-logs", "audit.read"),
        (RoleCode.VIEWER, "channels", "channel.read"),
        (RoleCode.LEAD_OPS, "leads", "lead.read"),
    ],
)
def test_each_project_role_uses_real_login(
    client, project_factory, user_factory, member_factory, role, resource, permission
):
    suffix = uuid.uuid4().hex[:8]
    project = project_factory(f"auth-{suffix}")
    user = user_factory(f"{role.value}-{suffix}")
    member_factory(project, user, role)

    login = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "unit-test-password"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    projects = me.json()["data"]["projects"]
    assert len(projects) == 1
    assert projects[0]["id"] == str(project.id)
    assert projects[0]["role_code"] == role.value
    assert permission in projects[0]["permissions"]
    assert client.get(f"/api/v1/projects/{project.id}/{resource}", headers=headers).status_code == 200


def test_password_change_invalidates_old_token(client, user_factory):
    user = user_factory("auth-password")
    old_token = create_access_token(user.id, token_version=user.token_version)
    headers = {"Authorization": f"Bearer {old_token}"}

    changed = client.post(
        "/api/v1/auth/password",
        json={"current_password": "unit-test-password", "new_password": "new-test-password"},
        headers=headers,
    )
    assert changed.status_code == 200
    new_token = changed.json()["data"]["access_token"]
    assert user.token_version == 1
    assert client.get("/api/v1/auth/me", headers=headers).json()["error"]["code"] == "token_stale"
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"username": user.username, "password": "unit-test-password"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": user.username, "password": "new-test-password"}).status_code == 200


def test_inactive_and_legacy_token_rejected(client, db, user_factory):
    user = user_factory("auth-inactive")
    legacy = jwt.encode(
        {"sub": str(user.id), "type": "access"}, settings.secret_key, algorithm=settings.jwt_algorithm
    )
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {legacy}"}).json()["error"]["code"] == "token_stale"

    token = create_access_token(user.id, token_version=user.token_version)
    user.is_active = False
    db.flush()
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "user_inactive"
