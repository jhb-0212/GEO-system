"""媒体渠道适配器：人工渠道不伪造下单、幂等键、发布回填。"""

from __future__ import annotations

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_manual_provider_quote_order_idempotent_and_publish(client, project_factory, user_factory, member_factory):
    project = project_factory(f"media-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"media-editor-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)

    created = client.post(
        f"/api/v1/projects/{project.id}/media-providers",
        json={
            "code": "manual-wire", "name": "人工媒体供应商", "adapter": "manual",
            "config": {"inventory": [{"name": "行业观察", "category": "industry_media"}], "unit_price": 800, "currency": "CNY"},
            "capabilities": ["list_inventory", "quote", "order", "publish", "status"],
        },
        headers=_auth(editor),
    )
    assert created.status_code == 200, created.text
    provider_id = created.json()["data"]["id"]

    inventory = client.post(f"/api/v1/projects/{project.id}/media-providers/{provider_id}/inventory", headers=_auth(editor))
    assert inventory.status_code == 200, inventory.text
    assert inventory.json()["data"]["items"][0]["media_name"] == "行业观察"

    quote = client.post(
        f"/api/v1/projects/{project.id}/media-providers/{provider_id}/quote",
        json={"media_name": "行业观察", "quantity": 2}, headers=_auth(editor),
    )
    assert quote.status_code == 200, quote.text
    assert quote.json()["data"]["unit_price"] == 800
    assert quote.json()["data"]["adapter"] == "manual"

    payload = {"idempotency_key": "press-release-001", "media_name": "行业观察", "quantity": 1, "unit_price": 800}
    first = client.post(
        f"/api/v1/projects/{project.id}/media-providers/{provider_id}/orders",
        json=payload, headers=_auth(editor),
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["created"] is True
    assert first.json()["data"]["status"] == "draft"
    order_id = first.json()["data"]["id"]

    again = client.post(
        f"/api/v1/projects/{project.id}/media-providers/{provider_id}/orders",
        json=payload, headers=_auth(editor),
    )
    assert again.status_code == 200, again.text
    assert again.json()["data"]["created"] is False
    assert again.json()["data"]["id"] == order_id

    blocked = client.post(f"/api/v1/projects/{project.id}/media-providers/orders/{order_id}/publish", headers=_auth(editor))
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "media_publish_url_required"

    manual = client.post(
        f"/api/v1/projects/{project.id}/media-providers/orders/{order_id}/manual-status",
        json={"status": "confirmed", "external_order_id": "SUP-9001", "note": "供应商已确认"},
        headers=_auth(editor),
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["data"]["external_order_id"] == "SUP-9001"

    published = client.post(
        f"/api/v1/projects/{project.id}/media-providers/orders/{order_id}/publish",
        params={"publish_url": "https://media.example.com/a"}, headers=_auth(editor),
    )
    assert published.status_code == 200, published.text
    assert published.json()["data"]["status"] == "published"
    assert published.json()["data"]["publish_url"] == "https://media.example.com/a"
