"""渠道准入审批流测试：待审核/已准入/已驳回状态机、审批留痕与准入门禁。

覆盖：
- 新建渠道默认待审核并写入首条审批周期；
- 仅项目管理员（channel.approve）可审批，editor 越权 403；
- 通过 / 驳回留痕，驳回必须填意见；驳回后可重新提交并追加新周期；
- 已审批渠道不能重复审批；
- 未准入渠道不能挂接引用回执、不能登记发布账号。
"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
    ChannelApproval,
    ContentItem,
    ContentVersion,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    ChannelApprovalStatus,
    ChannelCategory,
    ChannelStatus,
    CitationReviewStatus,
    CitationUsage,
    ContentKind,
    ContentStatus,
    EngineEntryType,
    QuestionStatus,
    QuestionType,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _create_channel(client, project, user, code_suffix: str) -> dict:
    resp = client.post(
        f"/api/v1/projects/{project.id}/channels",
        json={
            "code": f"ch-{code_suffix}",
            "name": "审批测试渠道",
            "category": "content_platform",
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _seed_sample(db, project) -> MonitoringSample:
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(
        code=f"eng-{suffix}",
        name="引擎",
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
    db.add(entry)
    db.flush()
    question = Question(
        project_id=project.id,
        code=f"Q-{suffix}",
        title="测试问题",
        question_type=QuestionType.GENERAL,
        audience="人群",
        intent="意图",
        priority=100,
        status=QuestionStatus.ACTIVE,
        current_version_no=1,
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(
        project_id=project.id,
        question_id=question.id,
        version_no=1,
        text="测试正文",
    )
    db.add(version)
    db.flush()
    round_row = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="轮次-1",
        status=RoundStatus.RUNNING,
    )
    db.add(round_row)
    db.flush()
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.DONE,
    )
    db.add(task)
    db.flush()
    sample = MonitoringSample(
        project_id=project.id,
        task_id=task.id,
        attempt_no=1,
        status=SampleStatus.HIT,
        sampling_mode=SamplingMode.SEARCH_ON,
    )
    db.add(sample)
    db.flush()
    return sample


def _add_citation(db, sample) -> MonitoringCitation:
    citation = MonitoringCitation(
        project_id=sample.project_id,
        sample_id=sample.id,
        raw_url="https://example.com/a",
        normalized_url="https://example.com/a",
        domain="example.com",
        citation_usage=CitationUsage.CITED,
        is_brand_related=False,
        review_status=CitationReviewStatus.AUTO,
    )
    db.add(citation)
    db.flush()
    return citation


def test_create_channel_starts_pending_and_records_submission(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"appr-{suffix}")
    editor = user_factory(f"appr-ed-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    data = _create_channel(client, project, editor, suffix)
    assert data["approval_status"] == ChannelApprovalStatus.PENDING_REVIEW.value

    channel = db.scalar(select(Channel).where(Channel.code == f"ch-{suffix}"))
    assert channel.approval_status == ChannelApprovalStatus.PENDING_REVIEW
    assert channel.submitted_by == editor.id
    assert channel.submitted_at is not None

    approvals = db.scalars(
        select(ChannelApproval).where(ChannelApproval.channel_id == channel.id)
    ).all()
    assert len(approvals) == 1
    assert approvals[0].submitted_by == editor.id
    assert approvals[0].decision is None


def test_editor_cannot_review_channel(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"appr-ed-{suffix}")
    editor = user_factory(f"appr-ed2-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    data = _create_channel(client, project, editor, suffix)

    resp = client.post(
        f"/api/v1/projects/{project.id}/channels/{data['id']}/review",
        json={"decision": "approved"},
        headers=_auth(editor),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "insufficient_permission"


def test_project_admin_approves_channel(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"appr-adm-{suffix}")
    editor = user_factory(f"appr-adm-ed-{suffix}")
    admin = user_factory(f"appr-adm-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    data = _create_channel(client, project, editor, suffix)

    resp = client.post(
        f"/api/v1/projects/{project.id}/channels/{data['id']}/review",
        json={"decision": "approved", "comment": "域名核验通过"},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["approval_status"] == ChannelApprovalStatus.APPROVED.value
    assert body["reviewed_by"] == str(admin.id)
    assert body["decision_comment"] == "域名核验通过"

    channel = db.scalar(select(Channel).where(Channel.id == uuid.UUID(data["id"])))
    assert channel.approval_status == ChannelApprovalStatus.APPROVED
    assert channel.reviewed_by == admin.id

    approval = db.scalar(select(ChannelApproval).where(ChannelApproval.channel_id == channel.id))
    assert approval.decision.value == "approved"
    assert approval.reviewed_by == admin.id


def test_reject_requires_comment(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"appr-rj-{suffix}")
    editor = user_factory(f"appr-rj-ed-{suffix}")
    admin = user_factory(f"appr-rj-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    data = _create_channel(client, project, editor, suffix)

    resp = client.post(
        f"/api/v1/projects/{project.id}/channels/{data['id']}/review",
        json={"decision": "rejected"},
        headers=_auth(admin),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "channel_reject_comment_required"


def test_reject_resubmit_then_approve(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"appr-rs-{suffix}")
    editor = user_factory(f"appr-rs-ed-{suffix}")
    admin = user_factory(f"appr-rs-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    data = _create_channel(client, project, editor, suffix)

    rejected = client.post(
        f"/api/v1/projects/{project.id}/channels/{data['id']}/review",
        json={"decision": "rejected", "comment": "域名归属存疑"},
        headers=_auth(admin),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["approval_status"] == ChannelApprovalStatus.REJECTED.value

    resubmit = client.post(
        f"/api/v1/projects/{project.id}/channels/{data['id']}/submit",
        headers=_auth(editor),
    )
    assert resubmit.status_code == 200, resubmit.text
    assert resubmit.json()["data"]["approval_status"] == ChannelApprovalStatus.PENDING_REVIEW.value

    channel = db.scalar(select(Channel).where(Channel.id == uuid.UUID(data["id"])))
    assert channel.submitted_by == editor.id

    approvals = db.scalars(
        select(ChannelApproval)
        .where(ChannelApproval.channel_id == channel.id)
        .order_by(ChannelApproval.submitted_at.asc(), ChannelApproval.id.asc())
    ).all()
    assert len(approvals) == 2
    assert approvals[0].decision.value == "rejected"
    assert approvals[1].decision is None

    approved = client.post(
        f"/api/v1/projects/{project.id}/channels/{data['id']}/review",
        json={"decision": "approved", "comment": "复核通过"},
        headers=_auth(admin),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["approval_status"] == ChannelApprovalStatus.APPROVED.value


def test_cannot_review_already_reviewed(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"appr-dbl-{suffix}")
    editor = user_factory(f"appr-dbl-ed-{suffix}")
    admin = user_factory(f"appr-dbl-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    data = _create_channel(client, project, editor, suffix)

    first = client.post(
        f"/api/v1/projects/{project.id}/channels/{data['id']}/review",
        json={"decision": "approved"},
        headers=_auth(admin),
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/projects/{project.id}/channels/{data['id']}/review",
        json={"decision": "rejected", "comment": "再驳一次"},
        headers=_auth(admin),
    )
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "channel_already_reviewed"


def test_pending_channel_cannot_attach_citation_then_approved_can(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"appr-cit-{suffix}")
    reviewer = user_factory(f"appr-cit-rv-{suffix}")
    admin = user_factory(f"appr-cit-adm-{suffix}")
    member_factory(project, reviewer, RoleCode.REVIEWER)
    member_factory(project, admin, RoleCode.PROJECT_ADMIN)
    sample = _seed_sample(db, project)
    citation = _add_citation(db, sample)

    channel = Channel(
        project_id=project.id,
        code=f"cit-{suffix}",
        name="待准入渠道",
        category=ChannelCategory.COMMUNITY,
        status=ChannelStatus.CANDIDATE,
    )
    db.add(channel)
    db.flush()

    blocked = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}",
        json={
            "review_status": CitationReviewStatus.MANUAL_CONFIRMED.value,
            "channel_id": str(channel.id),
        },
        headers=_auth(reviewer),
    )
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "channel_not_approved"

    approve = client.post(
        f"/api/v1/projects/{project.id}/channels/{channel.id}/review",
        json={"decision": "approved"},
        headers=_auth(admin),
    )
    assert approve.status_code == 200, approve.text

    attached = client.patch(
        f"/api/v1/projects/{project.id}/citations/{citation.id}",
        json={
            "review_status": CitationReviewStatus.MANUAL_CONFIRMED.value,
            "channel_id": str(channel.id),
        },
        headers=_auth(reviewer),
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["data"]["channel_id"] == str(channel.id)


def test_pending_channel_cannot_create_publish_account(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"appr-acc-{suffix}")
    editor = user_factory(f"appr-acc-ed-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    channel = Channel(
        project_id=project.id,
        code=f"acc-{suffix}",
        name="待准入渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
    )
    db.add(channel)
    db.flush()

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/accounts",
        json={"channel_id": str(channel.id), "account_name": "待准入账号"},
        headers=_auth(editor),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "channel_not_approved"


def test_pending_channel_cannot_create_publish_task(
    client, db, project_factory, user_factory, member_factory
):
    # 未准入渠道不能建发布任务：这道闸门此前只有账号/引用两处有用例，任务侧是空的。
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"appr-task-{suffix}")
    editor = user_factory(f"appr-task-ed-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    channel = Channel(
        project_id=project.id,
        code=f"task-{suffix}",
        name="待准入渠道-任务",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
    )
    db.add(channel)
    db.flush()

    master = ContentItem(project_id=project.id, kind=ContentKind.MASTER, title=f"母稿-{suffix}", status=ContentStatus.APPROVED)
    db.add(master)
    db.flush()
    master_version = ContentVersion(
        project_id=project.id, item_id=master.id, version_no=1, body="正文",
        content_hash=uuid.uuid4().hex, status=ContentStatus.APPROVED,
    )
    db.add(master_version)
    db.flush()
    master.current_version_id = master_version.id

    channel_item = ContentItem(
        project_id=project.id, kind=ContentKind.CHANNEL, parent_id=master.id,
        channel_id=channel.id, title=f"渠道稿-{suffix}", status=ContentStatus.APPROVED,
    )
    db.add(channel_item)
    db.flush()
    channel_version = ContentVersion(
        project_id=project.id, item_id=channel_item.id, version_no=1, body="渠道正文",
        content_hash=uuid.uuid4().hex, status=ContentStatus.APPROVED,
    )
    db.add(channel_version)
    db.flush()
    channel_item.current_version_id = channel_version.id
    db.flush()

    resp = client.post(
        f"/api/v1/projects/{project.id}/publish/tasks",
        json={
            "version_id": str(channel_version.id),
            "channel_id": str(channel.id),
            "account_id": str(uuid.uuid4()),
            "publish_mode": "manual",
            "task_key": f"tk-{suffix}",
        },
        headers=_auth(editor),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "channel_not_approved"
