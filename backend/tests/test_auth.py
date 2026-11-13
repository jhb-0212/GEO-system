"""B1 认证：登录、当前用户、项目可见范围。

本期只做 `auth/login` 与 `auth/me`；不做改密、不引入 token_version。
- 登录成功回写 `last_login_at`（UTC），失败不写。
- `me.projects` 只返回当前用户仍是活跃成员的项目；系统管理员不因 `is_system_admin` 自动拿全量。
"""

from app.core.security import create_access_token


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_login_success(client, user_factory):
    user_factory("alice")
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "unit-test-password"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "alice"


def test_login_wrong_password(client, user_factory):
    user_factory("bob")
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "bob", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_login_unknown_user(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "nobody", "password": "x"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_login_writes_last_login_at(client, db, user_factory):
    user = user_factory("carol")
    assert user.last_login_at is None

    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "carol", "password": "unit-test-password"},
    )
    assert resp.status_code == 200
    db.refresh(user)
    assert user.last_login_at is not None


def test_login_failure_does_not_write_last_login_at(client, db, user_factory):
    user = user_factory("dave")
    client.post(
        "/api/v1/auth/login",
        json={"username": "dave", "password": "wrong-password"},
    )
    db.refresh(user)
    assert user.last_login_at is None


def test_me_returns_current_user(client, user_factory):
    user = user_factory("erin")
    resp = client.get("/api/v1/auth/me", headers=_auth(user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["username"] == "erin"
    assert data["projects"] == []


def test_me_without_token_is_unauthorized(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_inactive_user_is_unauthorized(client, db, user_factory):
    user = user_factory("frank")
    token = create_access_token(user.id)
    user.is_active = False
    db.flush()

    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "user_inactive"


def test_me_projects_regular_member_non_empty(client, db, user_factory, project_factory, member_factory):
    user = user_factory("grace")
    project = project_factory("p-grace")
    member_factory(project, user)

    resp = client.get("/api/v1/auth/me", headers=_auth(user))
    assert resp.status_code == 200
    projects = resp.json()["data"]["projects"]
    assert len(projects) == 1
    assert projects[0]["code"] == "p-grace"


def test_me_projects_sysadmin_without_membership_is_empty(client, user_factory):
    admin = user_factory("sysadmin", is_system_admin=True)
    resp = client.get("/api/v1/auth/me", headers=_auth(admin))
    assert resp.status_code == 200
    assert resp.json()["data"]["projects"] == []


def test_me_projects_sysadmin_with_membership_non_empty(
    client, user_factory, project_factory, member_factory
):
    admin = user_factory("sysadmin2", is_system_admin=True)
    project = project_factory("p-sysadmin")
    member_factory(project, admin)

    resp = client.get("/api/v1/auth/me", headers=_auth(admin))
    assert resp.status_code == 200
    projects = resp.json()["data"]["projects"]
    assert len(projects) == 1
    assert projects[0]["code"] == "p-sysadmin"
