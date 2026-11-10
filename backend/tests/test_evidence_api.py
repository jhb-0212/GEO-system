"""证据文件访问测试：项目授权、路径穿越、未登录三条防线都要生效。"""

import uuid

from app.core.config import settings
from app.core.security import create_access_token
from app.models import EvidenceFile
from app.models.enums import EvidenceFileType, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_evidence_download_requires_membership(
    client, db, two_projects, user_factory, member_factory, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "evidence_local_root", str(tmp_path))
    p1, p2 = two_projects

    owner = user_factory(f"ev-owner-{uuid.uuid4().hex[:8]}")
    member_factory(p1, owner, RoleCode.VIEWER)
    outsider = user_factory(f"ev-out-{uuid.uuid4().hex[:8]}")
    member_factory(p2, outsider, RoleCode.ADMIN)

    (tmp_path / "shot.png").write_bytes(b"evidence-bytes")
    evidence = EvidenceFile(
        project_id=p1.id,
        storage_key="shot.png",
        file_type=EvidenceFileType.SCREENSHOT,
        content_type="image/png",
        checksum="sha256:test",
    )
    db.add(evidence)
    db.flush()

    url = f"/api/v1/projects/{p1.id}/evidence/{evidence.id}/download"
    assert client.get(url).status_code == 401

    ok = client.get(url, headers=_auth(owner))
    assert ok.status_code == 200
    assert ok.content == b"evidence-bytes"

    # 另一个项目的管理员也不能读
    denied = client.get(url, headers=_auth(outsider))
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "project_forbidden"


def test_evidence_path_traversal_blocked(
    client, db, project_factory, user_factory, member_factory, tmp_path, monkeypatch
):
    root = tmp_path / "evidence"
    root.mkdir()
    monkeypatch.setattr(settings, "evidence_local_root", str(root))

    project = project_factory(f"trav-{uuid.uuid4().hex[:6]}")
    user = user_factory(f"trav-user-{uuid.uuid4().hex[:8]}")
    member_factory(project, user, RoleCode.EDITOR)

    (tmp_path / "secret.txt").write_bytes(b"should-not-be-served")
    evidence = EvidenceFile(
        project_id=project.id,
        storage_key="../secret.txt",
        file_type=EvidenceFileType.OTHER,
    )
    db.add(evidence)
    db.flush()

    response = client.get(
        f"/api/v1/projects/{project.id}/evidence/{evidence.id}/download", headers=_auth(user)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "path_escape"
