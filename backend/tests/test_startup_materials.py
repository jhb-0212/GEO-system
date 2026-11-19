"""P78 启动材料待补清单回归。"""

import uuid

from app.core.security import create_access_token
from app.models import BrandProfile
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_startup_material_gaps_lists_missing(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"startup-{suffix}")
    admin = user_factory(f"startup-admin-{suffix}")
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    db.add(
        BrandProfile(
            project_id=project.id,
            canonical_name="广东省AI数字人才就业实训基地",
            owned_domains=["gdccai.com"],
        )
    )
    db.commit()

    resp = client.get(
        f"/api/v1/projects/{project.id}/startup-materials/gaps",
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["ready"] is False
    assert "域名" not in data["missing"]
    platform = next(item for item in data["items"] if item["key"] == "platform_accounts")
    assert platform["count"] == 0, platform
    assert any("平台账号" in item for item in data["missing"]), platform
    assert any("CMS" in item for item in data["missing"])
    domain = next(item for item in data["items"] if item["key"] == "domain")
    assert domain["status"] == "ready"
    assert domain["detail"] == "gdccai.com"
