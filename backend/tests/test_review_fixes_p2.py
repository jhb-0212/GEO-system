"""第二轮审查 P2 回归：CSV、公开 DTO、XFF、渠道域名唯一。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from app.core.config import settings
from app.core.net import client_ip
from app.core.security import create_access_token
from app.models import Channel, Project
from app.models.enums import ChannelCategory, ChannelStatus, ProjectStatus, RoleCode
from app.services.csv_safety import safe_csv_cell


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_csv_safety_escapes_formulas_but_preserves_numbers():
    assert safe_csv_cell("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
    assert safe_csv_cell("+HYPERLINK(\"http://x\")") == "'+HYPERLINK(\"http://x\")"
    assert safe_csv_cell("@SUM(1,2)") == "'@SUM(1,2)"
    assert safe_csv_cell("-12.5") == "-12.5"
    assert safe_csv_cell(+3) == 3
    assert safe_csv_cell("普通文本") == "普通文本"


def test_public_faq_hides_internal_fields_and_rejects_inactive_project(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"pub-{suffix}")
    editor = user_factory(f"pub-editor-{suffix}")
    reviewer = user_factory(f"pub-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    created = client.post(
        f"/api/v1/projects/{project.id}/faqs",
        json={"question": "公开问题", "answer": "公开答案", "status": "draft"},
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    faq_id = created.json()["data"]["id"]
    submitted = client.post(
        f"/api/v1/projects/{project.id}/faqs/{faq_id}/submit-review",
        headers=_auth(editor),
    )
    assert submitted.status_code == 200, submitted.text
    published = client.post(
        f"/api/v1/projects/{project.id}/faqs/{faq_id}/review",
        json={"action": "approve"},
        headers=_auth(reviewer),
    )
    assert published.status_code == 200, published.text

    public = client.get(f"/api/v1/public/projects/{project.code}/faqs")
    assert public.status_code == 200
    row = public.json()["data"][0]
    assert set(row) == {"id", "question", "answer", "category", "sort_order", "updated_at"}

    project.status = ProjectStatus.ARCHIVED
    db.flush()
    hidden = client.get(f"/api/v1/public/projects/{project.code}/faqs")
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "project_missing"


def test_client_ip_ignores_forwarded_header_without_trusted_proxy(monkeypatch):
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-forwarded-for", b"1.2.3.4, 10.0.0.1")],
            "client": ("127.0.0.1", 12345),
        }
    )
    monkeypatch.setattr(settings, "trusted_proxy_count", 0)
    assert client_ip(request) == "127.0.0.1"

    monkeypatch.setattr(settings, "trusted_proxy_count", 1)
    assert client_ip(request) == "10.0.0.1"


def test_channel_primary_domain_is_unique_at_database_layer(db, project_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"ch-uniq-{suffix}")
    first = Channel(
        project_id=project.id,
        code=f"a-{suffix}",
        name="渠道 A",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
        primary_domain="same.example.com",
    )
    db.add(first)
    db.flush()

    db.add(
        Channel(
            project_id=project.id,
            code=f"b-{suffix}",
            name="渠道 B",
            category=ChannelCategory.CONTENT_PLATFORM,
            status=ChannelStatus.CANDIDATE,
            primary_domain="same.example.com",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
