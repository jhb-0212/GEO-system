"""Workbench activity reads are permissioned and project scoped."""

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode
from app.services.audit import record_audit


def _headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_audit_list_is_project_scoped_and_requires_audit_read(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    own = project_factory(f"audit-own-{suffix}")
    other = project_factory(f"audit-other-{suffix}")
    reviewer = user_factory(f"audit-reviewer-{suffix}")
    editor = user_factory(f"audit-editor-{suffix}")
    member_factory(own, reviewer, RoleCode.REVIEWER)
    member_factory(own, editor, RoleCode.EDITOR)
    record_audit(db, project_id=own.id, actor_id=editor.id, action="own.action")
    record_audit(db, project_id=other.id, actor_id=editor.id, action="other.action")
    db.flush()

    url = f"/api/v1/projects/{own.id}/audit-logs"
    response = client.get(url, headers=_headers(reviewer))
    assert response.status_code == 200
    assert "own.action" in [row["action"] for row in response.json()["data"]]
    assert "other.action" not in [row["action"] for row in response.json()["data"]]
    assert client.get(url, headers=_headers(editor)).status_code == 403
    assert client.get(f"/api/v1/projects/{other.id}/audit-logs", headers=_headers(reviewer)).status_code == 403
