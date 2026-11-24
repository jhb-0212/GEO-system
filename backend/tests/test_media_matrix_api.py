"""媒体资源矩阵后台：公开只读、系统管理员写入、恢复默认。"""

import uuid

from app.core.security import create_access_token


def _headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _payload(label: str = "新闻媒体") -> dict:
    return {
        "payload": [
            {
                "id": "news",
                "label": label,
                "title": "新闻媒体",
                "description": "测试分类",
                "sections": [
                    {
                        "title": "第三方新闻媒体",
                        "note": "测试分组",
                        "items": [
                            {"name": "网易", "domain": "163.com", "tone": "red", "logo": "/media-logos/netease.png"},
                        ],
                    },
                ],
            },
        ],
    }


def test_public_catalog_returns_null_without_config(client, db):
    response = client.get("/api/v1/media-matrix/catalog")
    assert response.status_code == 200
    assert response.json()["data"]["payload"] is None


def test_non_admin_cannot_save_config(client, db, user_factory):
    user = user_factory(f"operator-{uuid.uuid4().hex[:6]}")
    response = client.put("/api/v1/media-matrix/config", json=_payload(), headers=_headers(user))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "system_admin_only"


def test_system_admin_saves_and_public_reads_config(client, db, user_factory):
    admin = user_factory(f"sysadmin-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    response = client.put("/api/v1/media-matrix/config", json=_payload(), headers=_headers(admin))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["payload"][0]["label"] == "新闻媒体"

    public = client.get("/api/v1/media-matrix/catalog")
    assert public.status_code == 200
    assert public.json()["data"]["payload"][0]["sections"][0]["items"][0]["name"] == "网易"

    admin_read = client.get("/api/v1/media-matrix/config", headers=_headers(admin))
    assert admin_read.status_code == 200
    assert admin_read.json()["data"]["updated_by"] == str(admin.id)


def test_system_admin_can_reset_to_default(client, db, user_factory):
    admin = user_factory(f"sysadmin-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    client.put("/api/v1/media-matrix/config", json=_payload(), headers=_headers(admin))
    response = client.delete("/api/v1/media-matrix/config", headers=_headers(admin))
    assert response.status_code == 200
    assert client.get("/api/v1/media-matrix/catalog").json()["data"]["payload"] is None


def test_duplicate_category_ids_are_rejected(client, db, user_factory):
    admin = user_factory(f"sysadmin-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    body = _payload()
    body["payload"].append(dict(body["payload"][0], label="另一个分类"))
    response = client.put("/api/v1/media-matrix/config", json=body, headers=_headers(admin))
    assert response.status_code == 422
