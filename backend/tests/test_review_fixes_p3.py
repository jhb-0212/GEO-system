"""第二轮审查 P3 回归：素材魔数、公开 URL scheme、outbox topic 收口。"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.core.security import create_access_token
from app.models.enums import RoleCode
from app.schemas.pages import PageCreate
from app.schemas.publishing import PublishReceiptCreate
from app.services.outbox import emit_event


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_material_rejects_disguised_executable(
    client, db, tmp_path, monkeypatch, project_factory, user_factory, member_factory
):
    monkeypatch.setattr(settings, "evidence_local_root", str(tmp_path))
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"magic-{suffix}")
    editor = user_factory(f"magic-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    bad = client.post(
        f"/api/v1/projects/{project.id}/materials",
        data={"title": "伪装图片", "category": "document"},
        files={"file": ("fake.png", b"MZ\x90\x00not-a-png", "image/png")},
        headers=_auth(editor),
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "material_content_mismatch"

    good = client.post(
        f"/api/v1/projects/{project.id}/materials",
        data={"title": "真实 PNG", "category": "document"},
        files={"file": ("real.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "image/png")},
        headers=_auth(editor),
    )
    assert good.status_code == 201, good.text
    assert good.json()["data"]["content_type"] == "image/png"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "http://127.0.0.1/internal",
        "http://localhost/internal",
        "https://user:pass@example.com/x",
        "https://example.com/x#frag",
    ],
)
def test_public_url_rejects_unsafe_values(url):
    with pytest.raises(ValidationError):
        PublishReceiptCreate(published_url=url)


def test_public_page_url_rejects_unsafe_scheme():
    with pytest.raises(ValidationError):
        PageCreate(
            slug="bad",
            title="坏链接",
            page_type="other",
            url="javascript:alert(1)",
        )
    with pytest.raises(ValidationError):
        PageCreate(
            slug="bad-private",
            title="内网链接",
            page_type="other",
            url="http://192.168.1.10/admin",
        )


def test_outbox_rejects_topic_without_consumer(db, project_factory):
    project = project_factory(f"topic-{uuid.uuid4().hex[:6]}")
    with pytest.raises(ValueError):
        emit_event(
            db,
            project_id=project.id,
            topic="publish.task.execute",
            payload={"project_id": str(project.id)},
        )
