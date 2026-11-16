"""B9 发布闭环：建单 / 回执结案 / 核实二分，含幂等、归属校验、hash 守卫与状态机约束。"""

import uuid

from sqlalchemy import func, select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
    ContentItem,
    ContentVersion,
    ContentVersionCitation,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    PublishAccount,
    PublishReceipt,
    PublishTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    ChannelCategory,
    ChannelStatus,
    CitationUsage,
    ContentStatus,
    EngineEntryType,
    PublishTaskStatus,
    QuestionStatus,
    QuestionType,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _channel_and_account(db, project, suffix):
    channel = Channel(
        project_id=project.id,
        code=f"ch-{suffix}",
        name="发布测试渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.OBSERVED,
        is_active=True,
    )
    db.add(channel)
    db.flush()
    account = PublishAccount(
        project_id=project.id,
        channel_id=channel.id,
        account_name=f"acc-{suffix}",
        credential_ref="vault://test/publish",
        is_active=True,
    )
    db.add(account)
    db.flush()
    return channel, account


def _approved_channel_version(client, db, project, editor, reviewer, suffix, *, kind="channel"):
    item = client.post(
        f"/api/v1/projects/{project.id}/contents",
        json={"title": f"发布测试稿-{suffix}", "kind": kind},
        headers=_auth(editor),
    )
    assert item.status_code == 201
    item_id = item.json()["data"]["item_id"]
    version = client.post(
        f"/api/v1/projects/{project.id}/contents/{item_id}/versions",
        json={"body": f"渠道稿正文-{suffix}", "change_note": "初稿"},
        headers=_auth(editor),
    )
    assert version.status_code == 201
    version_id = version.json()["data"]["version_id"]
    assert client.post(
        f"/api/v1/projects/{project.id}/content-versions/{version_id}/submit",
        headers=_auth(editor),
    ).status_code == 200
    review = client.post(
        f"/api/v1/projects/{project.id}/content-versions/{version_id}/review",
        json={"decision": "approved", "comment": "通过"},
        headers=_auth(reviewer),
    )
    assert review.status_code == 200
    return version_id


def _link_monitoring_citation(db, project, version_id, trace_id=None):
    """给内容版本挂一条监测引用，用来验证发布侧 trace 继承。"""
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(
        code=f"eng-{suffix}",
        name="发布链路引擎",
        vendor="测试",
        supports_search=True,
        supports_citation=True,
        is_active=True,
    )
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(
        engine_id=engine.id,
        entry_type=EngineEntryType.WEB_USER,
        name="网页端",
        supports_search=True,
        is_active=True,
    )
    question = Question(
        project_id=project.id,
        code=f"Q-{suffix}",
        title="发布 trace 问题",
        question_type=QuestionType.GENERAL,
        status=QuestionStatus.ACTIVE,
        current_version_no=1,
    )
    db.add_all([entry, question])
    db.flush()
    version = QuestionVersion(
        project_id=project.id,
        question_id=question.id,
        version_no=1,
        text="发布 trace 问题正文",
    )
    round_row = MonitoringRound(
        project_id=project.id,
        seq=(db.scalar(select(func.max(MonitoringRound.seq)).where(
            MonitoringRound.project_id == project.id
        )) or 0) + 1,
        name="发布 trace 轮次",
        status=RoundStatus.RUNNING,
    )
    db.add_all([version, round_row])
    db.flush()
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.DONE,
        trace_id=trace_id,
    )
    db.add(task)
    db.flush()
    sample = MonitoringSample(
        project_id=project.id,
        task_id=task.id,
        attempt_no=1,
        status=SampleStatus.HIT,
        sampling_mode=SamplingMode.SEARCH_ON,
        raw_answer="发布引用回答",
        trace_id=trace_id,
    )
    db.add(sample)
    db.flush()
    citation = MonitoringCitation(
        project_id=project.id,
        sample_id=sample.id,
        trace_id=trace_id,
        raw_url="https://example.com/publish-trace",
        normalized_url="https://example.com/publish-trace",
        domain="example.com",
        citation_usage=CitationUsage.CITED,
        is_brand_related=True,
    )
    db.add(citation)
    db.flush()
    db.add(
        ContentVersionCitation(
            project_id=project.id,
            version_id=version_id,
            citation_id=citation.id,
        )
    )
    db.flush()
    return citation


def _create_task(client, project, editor, version_id, channel_id, account_id, task_key=None):
    body = {
        "version_id": str(version_id),
        "channel_id": str(channel_id),
        "account_id": str(account_id),
        "task_key": task_key or f"tk-{str(version_id)[:8]}",
    }
    return client.post(
        f"/api/v1/projects/{project.id}/publish/tasks",
        json=body,
        headers=_auth(editor),
    )


def test_create_task_success_and_idempotent_reuse(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9-{suffix}")
    editor = user_factory(f"b9-editor-{suffix}")
    reviewer = user_factory(f"b9-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)

    first = _create_task(client, project, editor, version_id, channel.id, account.id)
    assert first.status_code == 201
    data = first.json()["data"]
    assert data["status"] == "pending"
    assert data["reused"] is False
    task_id = data["task_id"]

    second = _create_task(client, project, editor, version_id, channel.id, account.id)
    assert second.status_code == 201
    assert second.json()["data"]["reused"] is True
    assert second.json()["data"]["task_id"] == task_id

    tasks = db.query(PublishTask).filter(PublishTask.project_id == project.id).all()
    assert len(tasks) == 1


def test_publish_task_inherits_unique_trace_from_content_citation(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9t-{suffix}")
    editor = user_factory(f"b9t-editor-{suffix}")
    reviewer = user_factory(f"b9t-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)
    trace_id = "trace-publish-unique"
    _link_monitoring_citation(db, project, version_id, trace_id=trace_id)

    first = _create_task(client, project, editor, version_id, channel.id, account.id)
    assert first.status_code == 201, first.text
    assert first.json()["data"]["trace_id"] == trace_id

    second = _create_task(client, project, editor, version_id, channel.id, account.id)
    assert second.status_code == 201, second.text
    assert second.json()["data"]["reused"] is True
    assert second.json()["data"]["trace_id"] == trace_id

    listed = client.get(
        f"/api/v1/projects/{project.id}/publish/tasks",
        headers=_auth(editor),
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"][0]["trace_id"] == trace_id


def test_publish_task_does_not_guess_trace_when_citations_disagree(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9a-{suffix}")
    editor = user_factory(f"b9a-editor-{suffix}")
    reviewer = user_factory(f"b9a-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)
    _link_monitoring_citation(db, project, version_id, trace_id="trace-a")
    _link_monitoring_citation(db, project, version_id, trace_id="trace-b")

    resp = _create_task(client, project, editor, version_id, channel.id, account.id)
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["trace_id"] is None


def test_create_task_rejects_master_item(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9m-{suffix}")
    editor = user_factory(f"b9m-editor-{suffix}")
    reviewer = user_factory(f"b9m-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(
        client, db, project, editor, reviewer, suffix, kind="master"
    )

    resp = _create_task(client, project, editor, version_id, channel.id, account.id)
    assert resp.status_code == 409


def test_create_task_rejects_unapproved_version(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9u-{suffix}")
    editor = user_factory(f"b9u-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel, account = _channel_and_account(db, project, suffix)
    item = client.post(
        f"/api/v1/projects/{project.id}/contents",
        json={"title": f"未审稿-{suffix}", "kind": "channel"},
        headers=_auth(editor),
    )
    item_id = item.json()["data"]["item_id"]
    version = client.post(
        f"/api/v1/projects/{project.id}/contents/{item_id}/versions",
        json={"body": f"未审正文-{suffix}"},
        headers=_auth(editor),
    )
    version_id = version.json()["data"]["version_id"]

    resp = _create_task(client, project, editor, version_id, channel.id, account.id)
    assert resp.status_code == 409


def test_create_task_rejects_account_not_bound_to_channel(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9x-{suffix}")
    editor = user_factory(f"b9x-editor-{suffix}")
    reviewer = user_factory(f"b9x-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    other_channel = Channel(
        project_id=project.id,
        code=f"ch-other-{suffix}",
        name="另一渠道",
        category=ChannelCategory.VIDEO,
        status=ChannelStatus.OBSERVED,
        is_active=True,
    )
    db.add(other_channel)
    db.flush()
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)

    resp = _create_task(client, project, editor, version_id, other_channel.id, account.id)
    assert resp.status_code == 403


def test_receipt_closes_publishing_task(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9r-{suffix}")
    editor = user_factory(f"b9r-editor-{suffix}")
    reviewer = user_factory(f"b9r-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)
    task_id = _create_task(client, project, editor, version_id, channel.id, account.id).json()["data"]["task_id"]

    task = db.get(PublishTask, uuid.UUID(task_id))
    task.status = PublishTaskStatus.PUBLISHING
    db.flush()

    receipt = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/receipts",
        json={"published_url": "https://example.com/post/1"},
        headers=_auth(editor),
    )
    assert receipt.status_code == 200
    assert receipt.json()["data"]["status"] == "published"

    saved = db.get(PublishTask, uuid.UUID(task_id))
    assert saved.status == PublishTaskStatus.PUBLISHED
    receipts = db.query(PublishReceipt).filter(PublishReceipt.task_id == saved.id).all()
    assert len(receipts) == 1
    assert receipts[0].published_url == "https://example.com/post/1"


def test_verify_not_published_returns_to_pending(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9v-{suffix}")
    editor = user_factory(f"b9v-editor-{suffix}")
    reviewer = user_factory(f"b9v-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)
    task_id = _create_task(client, project, editor, version_id, channel.id, account.id).json()["data"]["task_id"]

    task = db.get(PublishTask, uuid.UUID(task_id))
    task.status = PublishTaskStatus.UNKNOWN
    db.flush()

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/verify",
        json={"outcome": "not_published"},
        headers=_auth(editor),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "pending"
    assert db.get(PublishTask, uuid.UUID(task_id)).status == PublishTaskStatus.PENDING


def test_verify_published_closes_with_receipt(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9w-{suffix}")
    editor = user_factory(f"b9w-editor-{suffix}")
    reviewer = user_factory(f"b9w-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)
    task_id = _create_task(client, project, editor, version_id, channel.id, account.id).json()["data"]["task_id"]

    task = db.get(PublishTask, uuid.UUID(task_id))
    task.status = PublishTaskStatus.UNKNOWN
    db.flush()

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/verify",
        json={"outcome": "published", "published_url": "https://example.com/verified/9"},
        headers=_auth(editor),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "published"
    receipts = db.query(PublishReceipt).filter(PublishReceipt.task_id == task.id).all()
    assert len(receipts) == 1
    assert receipts[0].published_url == "https://example.com/verified/9"


def test_verify_only_unknown_allowed(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9z-{suffix}")
    editor = user_factory(f"b9z-editor-{suffix}")
    reviewer = user_factory(f"b9z-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)
    task_id = _create_task(client, project, editor, version_id, channel.id, account.id).json()["data"]["task_id"]

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/verify",
        json={"outcome": "not_published"},
        headers=_auth(editor),
    )
    assert resp.status_code == 409


def test_hash_drift_guard_returns_version_to_pending_review(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9h-{suffix}")
    editor = user_factory(f"b9h-editor-{suffix}")
    reviewer = user_factory(f"b9h-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)

    version = db.get(ContentVersion, uuid.UUID(version_id))
    version.content_hash = "drifted-hash-after-approval"
    db.flush()

    resp = _create_task(client, project, editor, version_id, channel.id, account.id)
    assert resp.status_code == 409
    db.refresh(version)
    assert version.status == ContentStatus.PENDING_REVIEW


def test_verify_published_requires_url_422(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9u2-{suffix}")
    editor = user_factory(f"b9u2-editor-{suffix}")
    reviewer = user_factory(f"b9u2-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)
    task_id = _create_task(client, project, editor, version_id, channel.id, account.id).json()["data"]["task_id"]

    task = db.get(PublishTask, uuid.UUID(task_id))
    task.status = PublishTaskStatus.UNKNOWN
    db.flush()

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/verify",
        json={"outcome": "published"},
        headers=_auth(editor),
    )
    assert resp.status_code == 422
    saved = db.get(PublishTask, uuid.UUID(task_id))
    assert saved.status == PublishTaskStatus.UNKNOWN
    receipts = db.query(PublishReceipt).filter(PublishReceipt.task_id == saved.id).all()
    assert len(receipts) == 0


def test_receipt_rejects_unknown_task(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9r2-{suffix}")
    editor = user_factory(f"b9r2-editor-{suffix}")
    reviewer = user_factory(f"b9r2-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)
    task_id = _create_task(client, project, editor, version_id, channel.id, account.id).json()["data"]["task_id"]

    task = db.get(PublishTask, uuid.UUID(task_id))
    task.status = PublishTaskStatus.UNKNOWN
    db.flush()

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/receipts",
        json={"published_url": "https://example.com/unknown"},
        headers=_auth(editor),
    )
    assert resp.status_code == 409
    receipts = db.query(PublishReceipt).filter(PublishReceipt.task_id == task.id).all()
    assert len(receipts) == 0


def test_receipt_url_must_be_http_scheme(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9u3-{suffix}")
    editor = user_factory(f"b9u3-editor-{suffix}")
    reviewer = user_factory(f"b9u3-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)
    task_id = _create_task(client, project, editor, version_id, channel.id, account.id).json()["data"]["task_id"]

    task = db.get(PublishTask, uuid.UUID(task_id))
    task.status = PublishTaskStatus.PUBLISHING
    db.flush()

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks/{task_id}/receipts",
        json={"published_url": "example.com/no-scheme"},
        headers=_auth(editor),
    )
    assert resp.status_code == 422


def test_list_accounts(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9a-{suffix}")
    editor = user_factory(f"b9a-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    channel, account = _channel_and_account(db, project, suffix)

    resp = client.get(
        f"/api/v1/projects/{project.id}/publish/accounts", headers=_auth(editor)
    )
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert any(row["account_name"] == account.account_name for row in rows)
    row = next(r for r in rows if r["id"] == str(account.id))
    assert row["channel_id"] == str(channel.id)
    assert "credential_ref" not in row


def test_create_task_requires_task_key_422(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9k-{suffix}")
    editor = user_factory(f"b9k-editor-{suffix}")
    reviewer = user_factory(f"b9k-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks",
        json={
            "version_id": str(version_id),
            "channel_id": str(channel.id),
            "account_id": str(account.id),
        },
        headers=_auth(editor),
    )
    assert resp.status_code == 422

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks",
        json={
            "version_id": str(version_id),
            "channel_id": str(channel.id),
            "account_id": str(account.id),
            "task_key": "bad key",
        },
        headers=_auth(editor),
    )
    assert resp.status_code == 422


def test_reviewer_cannot_create_task(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9p-{suffix}")
    editor = user_factory(f"b9p-editor-{suffix}")
    reviewer = user_factory(f"b9p-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    channel, account = _channel_and_account(db, project, suffix)
    version_id = _approved_channel_version(client, db, project, editor, reviewer, suffix)

    resp = _create_task(client, project, reviewer, version_id, channel.id, account.id)
    assert resp.status_code == 403


def test_create_publish_account_endpoint(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"b9a-{suffix}")
    editor = user_factory(f"b9a-editor-{suffix}")
    admin = user_factory(f"b9a-admin-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)

    channel = Channel(
        project_id=project.id,
        code=f"ch-acc-{suffix}",
        name="账号登记测试渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.OBSERVED,
        is_active=True,
    )
    db.add(channel)
    db.flush()

    body = {"channel_id": str(channel.id), "account_name": "测试发布账号", "notes": "本地联调"}
    created = client.post(
        f"/api/v1/projects/{project.id}/publish/accounts",
        json=body,
        headers=_auth(editor),
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["account_name"] == "测试发布账号"
    assert data["channel_id"] == str(channel.id)
    assert "credential_ref" not in data

    duplicate = client.post(
        f"/api/v1/projects/{project.id}/publish/accounts",
        json=body,
        headers=_auth(editor),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "publish_account_exists"

    forbidden = client.post(
        f"/api/v1/projects/{project.id}/publish/accounts",
        json={"channel_id": str(channel.id), "account_name": "管理员不允许建"},
        headers=_auth(admin),
    )
    assert forbidden.status_code == 403
