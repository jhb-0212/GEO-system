"""P76：媒体预算绑报价，回执逐条挂预算。"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    Channel,
    ContentItem,
    ContentVersion,
    PublishAccount,
    PublishReceipt,
    PublishTask,
)
from app.models.enums import (
    BudgetApprovalStatus,
    BudgetCategory,
    ChannelApprovalStatus,
    ChannelCategory,
    ContentKind,
    ContentStatus,
    PublishTaskStatus,
    RoleCode,
)


def _auth(user) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"
    }


def _make_channel(db, project, *, code: str, name: str) -> Channel:
    channel = Channel(
        project_id=project.id,
        code=code,
        name=name,
        category=ChannelCategory.CONTENT_PLATFORM,
        approval_status=ChannelApprovalStatus.APPROVED,
    )
    db.add(channel)
    db.flush()
    return channel


def _make_quote(
    client, project, editor, reviewer, channel: Channel, *, unit_price="100.00", quantity=2
):
    plan = client.post(
        f"/api/v1/projects/{project.id}/plans",
        json={"title": f"P76 计划-{uuid.uuid4().hex[:6]}", "plan_type": "article"},
        headers=_auth(editor),
    )
    assert plan.status_code == 201, plan.text
    created = client.post(
        f"/api/v1/projects/{project.id}/media-quotes",
        json={
            "plan_id": plan.json()["data"]["id"],
            "channel_id": str(channel.id),
            "unit_price": unit_price,
            "quantity": quantity,
            "currency": "cny",
        },
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    quote_id = created.json()["data"]["id"]
    reviewed = client.post(
        f"/api/v1/projects/{project.id}/media-quotes/{quote_id}/review",
        json={"decision": "approved", "note": "P76 测试报价"},
        headers=_auth(reviewer),
    )
    assert reviewed.status_code == 200, reviewed.text
    return quote_id


def _make_channel_content(db, project, channel: Channel, editor) -> tuple[PublishTask, ContentVersion]:
    """造一条可发布的渠道稿 + 账号 + 任务，只用于 P76 关联测试。"""
    master = ContentItem(
        project_id=project.id,
        kind=ContentKind.MASTER,
        title=f"P76 母稿-{uuid.uuid4().hex[:6]}",
        status=ContentStatus.APPROVED,
    )
    db.add(master)
    db.flush()
    master_version = ContentVersion(
        project_id=project.id,
        item_id=master.id,
        version_no=1,
        body="P76 测试正文",
        content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status=ContentStatus.APPROVED,
    )
    db.add(master_version)
    db.flush()
    master.current_version_id = master_version.id

    channel_item = ContentItem(
        project_id=project.id,
        parent_id=master.id,
        channel_id=channel.id,
        kind=ContentKind.CHANNEL,
        title=f"P76 渠道稿-{uuid.uuid4().hex[:6]}",
        status=ContentStatus.APPROVED,
    )
    db.add(channel_item)
    db.flush()
    version = ContentVersion(
        project_id=project.id,
        item_id=channel_item.id,
        version_no=1,
        body="P76 渠道测试正文",
        content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status=ContentStatus.APPROVED,
    )
    db.add(version)
    db.flush()
    channel_item.current_version_id = version.id

    account = PublishAccount(
        project_id=project.id,
        channel_id=channel.id,
        account_name=f"P76 账号-{uuid.uuid4().hex[:6]}",
        is_active=True,
    )
    db.add(account)
    db.flush()
    task = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"p76-task-{uuid.uuid4().hex[:6]}",
        idempotency_key=f"p76-idem-{uuid.uuid4().hex[:10]}",
        status=PublishTaskStatus.PUBLISHED,
        created_by=editor.id,
    )
    db.add(task)
    db.flush()
    return task, version


def _make_receipt(db, project, task, editor, url: str) -> PublishReceipt:
    receipt = PublishReceipt(
        project_id=project.id,
        task_id=task.id,
        published_url=url,
        received_at=datetime.now(timezone.utc),
        verified_by=editor.id,
        verified_at=datetime.now(timezone.utc),
    )
    db.add(receipt)
    db.flush()
    return receipt


def _create_budget(
    client,
    project,
    editor,
    quote_id,
    *,
    quantity="1",
    unit_price="100.00",
    currency="CNY",
    title="媒体投放预算",
    category="media_placement",
):
    return client.post(
        f"/api/v1/projects/{project.id}/budget-approvals",
        json={
            "category": category,
            "media_quote_id": quote_id,
            "title": title,
            "quantity": quantity,
            "unit_price": unit_price,
            "amount": str(float(quantity) * float(unit_price)),
            "currency": currency,
        },
        headers=_auth(editor),
    )


def _approve_budget(client, project, reviewer, budget_id):
    return client.post(
        f"/api/v1/projects/{project.id}/budget-approvals/{budget_id}/review",
        json={"decision": "approved", "note": "P76 测试预算"},
        headers=_auth(reviewer),
    )


def test_media_budget_requires_approved_quote_and_stays_in_quote_quantity(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"p76-quote-{suffix}")
    editor = user_factory(f"p76-editor-{suffix}")
    reviewer = user_factory(f"p76-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel = _make_channel(db, project, code=f"p76-zhihu-{suffix}", name="知乎")

    base = f"/api/v1/projects/{project.id}/budget-approvals"

    # 媒体预算不传报价 → 422。
    no_quote = client.post(
        base,
        json={
            "category": "media_placement",
            "title": "无报价投放",
            "quantity": "1",
            "unit_price": "100",
            "amount": "100",
        },
        headers=_auth(editor),
    )
    assert no_quote.status_code == 422, no_quote.text
    assert no_quote.json()["error"]["code"] == "media_quote_required"

    # 非媒体预算传报价 → 422。
    wrong_category = client.post(
        base,
        json={
            "category": "content_production",
            "media_quote_id": str(uuid.uuid4()),
            "title": "错挂报价",
            "amount": "100",
        },
        headers=_auth(editor),
    )
    assert wrong_category.status_code == 422, wrong_category.text
    assert wrong_category.json()["error"]["code"] == "media_quote_not_allowed"

    # 未审批报价不能作为单价依据。
    draft_plan = client.post(
        f"/api/v1/projects/{project.id}/plans",
        json={"title": "P76 待审计划", "plan_type": "article"},
        headers=_auth(editor),
    )
    assert draft_plan.status_code == 201, draft_plan.text
    pending_quote = client.post(
        f"/api/v1/projects/{project.id}/media-quotes",
        json={
            "plan_id": draft_plan.json()["data"]["id"],
            "channel_id": str(channel.id),
            "unit_price": "100",
            "quantity": 1,
            "currency": "CNY",
        },
        headers=_auth(editor),
    )
    assert pending_quote.status_code == 201, pending_quote.text
    not_approved = _create_budget(
        client,
        project,
        editor,
        pending_quote.json()["data"]["id"],
    )
    assert not_approved.status_code == 422, not_approved.text
    assert not_approved.json()["error"]["code"] == "media_quote_not_approved"

    quote_id = _make_quote(client, project, editor, reviewer, channel)

    # 单价不一致。
    price_mismatch = _create_budget(
        client, project, editor, quote_id, unit_price="99.00"
    )
    assert price_mismatch.status_code == 422, price_mismatch.text
    assert (
        price_mismatch.json()["error"]["code"]
        == "budget_quote_unit_price_mismatch"
    )

    # 币种不一致。
    currency_mismatch = _create_budget(
        client, project, editor, quote_id, currency="USD"
    )
    assert currency_mismatch.status_code == 422, currency_mismatch.text
    assert (
        currency_mismatch.json()["error"]["code"]
        == "budget_quote_currency_mismatch"
    )

    # 报价 2 篇：先占 1 篇，再要 2 篇即超剩余。
    first = _create_budget(client, project, editor, quote_id, quantity="1")
    assert first.status_code == 201, first.text
    first_data = first.json()["data"]
    assert first_data["media_quote_id"] == quote_id
    assert first_data["media_quote"]["channel_name"] == "知乎"
    assert first_data["linked_receipt_count"] == 0
    assert first_data["remaining_quantity"] == 1.0

    exceeded = _create_budget(client, project, editor, quote_id, quantity="2")
    assert exceeded.status_code == 422, exceeded.text
    assert (
        exceeded.json()["error"]["code"] == "budget_quote_quantity_exceeded"
    )

    # 审批时再校验一次；审批通过后详情保留报价。
    approved = _approve_budget(client, project, reviewer, first_data["id"])
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "approved"
    assert approved.json()["data"]["media_quote"]["status"] == "approved"

    # 审批后不能再改预算状态。
    again = _approve_budget(client, project, reviewer, first_data["id"])
    assert again.status_code == 400, again.text


def test_receipt_links_to_budget_and_lists_task_and_receipt(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"p76-link-{suffix}")
    editor = user_factory(f"p76-link-editor-{suffix}")
    reviewer = user_factory(f"p76-link-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel = _make_channel(db, project, code=f"p76-zhihu-link-{suffix}", name="知乎")
    quote_id = _make_quote(client, project, editor, reviewer, channel, quantity=2)
    budget = _create_budget(client, project, editor, quote_id, quantity="2", title="知乎投放")
    assert budget.status_code == 201, budget.text
    budget_id = budget.json()["data"]["id"]
    approved = _approve_budget(client, project, reviewer, budget_id)
    assert approved.status_code == 200, approved.text

    task, _ = _make_channel_content(db, project, channel, editor)
    # 回执创建接口可顺带挂预算；任务从 publishing 结案。
    task.status = PublishTaskStatus.PUBLISHING
    db.flush()
    receipt_response = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task.id}/receipts",
        json={
            "published_url": "https://zhuanlan.zhihu.com/p/2106777058521114619",
            "budget_approval_id": budget_id,
        },
        headers=_auth(editor),
    )
    assert receipt_response.status_code == 200, receipt_response.text
    receipt_id = receipt_response.json()["data"]["receipt_id"]

    detail = client.get(
        f"/api/v1/projects/{project.id}/budget-approvals/{budget_id}",
        headers=_auth(editor),
    )
    assert detail.status_code == 200, detail.text
    row = detail.json()["data"]
    assert row["linked_receipt_count"] == 1
    assert row["remaining_quantity"] == 1.0
    assert row["receipt_complete"] is False
    assert row["receipts"][0]["receipt_id"] == receipt_id
    assert row["receipts"][0]["published_url"].startswith("https://zhuanlan.zhihu.com/p/")

    # 任务列表补回执与预算归属。
    tasks = client.get(
        f"/api/v1/projects/{project.id}/publish/tasks",
        headers=_auth(editor),
    )
    assert tasks.status_code == 200, tasks.text
    task_row = next(item for item in tasks.json()["data"] if item["id"] == str(task.id))
    assert task_row["receipt_id"] == receipt_id
    assert task_row["budget_approval_id"] == budget_id
    assert task_row["budget_title"] == "知乎投放"

    # 回执列表可按预算筛选。
    receipts = client.get(
        f"/api/v1/projects/{project.id}/publish/receipts",
        params={"has_budget": True},
        headers=_auth(editor),
    )
    assert receipts.status_code == 200, receipts.text
    assert receipts.json()["meta"]["total"] == 1
    assert receipts.json()["data"][0]["budget_approval_id"] == budget_id
    assert receipts.json()["data"][0]["channel_name"] == "知乎"

    # 同一条回执不能重复挂；解绑后可以再挂。
    duplicate = client.post(
        f"/api/v1/projects/{project.id}/budget-approvals/{budget_id}/receipt-links",
        json={"receipt_id": receipt_id},
        headers=_auth(editor),
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "budget_receipt_already_linked"

    unlinked = client.delete(
        f"/api/v1/projects/{project.id}/budget-approvals/{budget_id}/receipt-links/{receipt_id}",
        headers=_auth(editor),
    )
    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()["data"]["remaining_quantity"] == 2
    receipt_after = db.scalar(select(PublishReceipt).where(PublishReceipt.id == uuid.UUID(receipt_id)))
    assert receipt_after is not None and receipt_after.budget_approval_id is None

    relink = client.post(
        f"/api/v1/projects/{project.id}/budget-approvals/{budget_id}/receipt-links",
        json={"receipt_id": receipt_id},
        headers=_auth(editor),
    )
    assert relink.status_code == 200, relink.text
    assert relink.json()["data"]["remaining_quantity"] == 1


def test_receipt_link_rejects_test_url_wrong_channel_and_overflow(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"p76-rule-{suffix}")
    editor = user_factory(f"p76-rule-editor-{suffix}")
    reviewer = user_factory(f"p76-rule-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel = _make_channel(db, project, code=f"p76-zhihu-rule-{suffix}", name="知乎")
    other_channel = _make_channel(
        db, project, code=f"p76-xhs-rule-{suffix}", name="小红书"
    )
    quote_id = _make_quote(client, project, editor, reviewer, channel, quantity=1)
    budget = _create_budget(client, project, editor, quote_id, quantity="1")
    assert budget.status_code == 201, budget.text
    budget_id = budget.json()["data"]["id"]
    assert _approve_budget(client, project, reviewer, budget_id).status_code == 200

    task, _ = _make_channel_content(db, project, channel, editor)
    test_receipt = _make_receipt(
        db, project, task, editor, "https://example.com/p76-test"
    )
    test_link = client.post(
        f"/api/v1/projects/{project.id}/budget-approvals/{budget_id}/receipt-links",
        json={"receipt_id": str(test_receipt.id)},
        headers=_auth(editor),
    )
    assert test_link.status_code == 422, test_link.text
    assert test_link.json()["error"]["code"] == "budget_receipt_test_url_not_allowed"

    other_task, _ = _make_channel_content(db, project, other_channel, editor)
    wrong_channel_receipt = _make_receipt(
        db, project, other_task, editor, "https://www.xiaohongshu.com/explore/p76"
    )
    wrong_channel = client.post(
        f"/api/v1/projects/{project.id}/budget-approvals/{budget_id}/receipt-links",
        json={"receipt_id": str(wrong_channel_receipt.id)},
        headers=_auth(editor),
    )
    assert wrong_channel.status_code == 422, wrong_channel.text
    assert wrong_channel.json()["error"]["code"] == "budget_receipt_channel_mismatch"

    # 预算 1 篇，挂满后再挂第二条回执应 409。
    first_receipt = _make_receipt(
        db, project, task, editor, "https://zhuanlan.zhihu.com/p/p76-real"
    )
    linked = client.post(
        f"/api/v1/projects/{project.id}/budget-approvals/{budget_id}/receipt-links",
        json={"receipt_id": str(first_receipt.id)},
        headers=_auth(editor),
    )
    assert linked.status_code == 200, linked.text
    overflow_receipt = _make_receipt(
        db, project, task, editor, "https://zhuanlan.zhihu.com/p/p76-extra"
    )
    overflow = client.post(
        f"/api/v1/projects/{project.id}/budget-approvals/{budget_id}/receipt-links",
        json={"receipt_id": str(overflow_receipt.id)},
        headers=_auth(editor),
    )
    assert overflow.status_code == 409, overflow.text
    assert overflow.json()["error"]["code"] == "budget_receipt_quantity_exceeded"

    # 非 media 预算不能挂回执。
    content_budget = client.post(
        f"/api/v1/projects/{project.id}/budget-approvals",
        json={"category": "content_production", "title": "内容预算", "amount": "100"},
        headers=_auth(editor),
    )
    assert content_budget.status_code == 201, content_budget.text
    content_budget_id = content_budget.json()["data"]["id"]
    assert _approve_budget(client, project, reviewer, content_budget_id).status_code == 200
    not_media = client.post(
        f"/api/v1/projects/{project.id}/budget-approvals/{content_budget_id}/receipt-links",
        json={"receipt_id": str(first_receipt.id)},
        headers=_auth(editor),
    )
    assert not_media.status_code == 422, not_media.text
    assert (
        not_media.json()["error"]["code"]
        == "budget_receipt_link_requires_media"
    )
