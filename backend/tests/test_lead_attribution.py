"""线索归因字段的接口级验收：能写入、能读回、跨项目引用被拒绝。"""

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import Channel, Lead, LeadAttribution, Question
from app.services.stats import lead_funnel
from app.models.enums import (
    ChannelCategory,
    ChannelStatus,
    QuestionStatus,
    QuestionType,
    RoleCode,
)


def auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _question(project, suffix: str) -> Question:
    return Question(
        project_id=project.id,
        code=f"Q-{suffix}",
        title="测试归因题目",
        question_type=QuestionType.BRAND,
        audience="零基础转行者",
        intent="了解课程",
        priority=100,
        status=QuestionStatus.DRAFT,
        current_version_no=1,
    )


def _channel(project, suffix: str) -> Channel:
    return Channel(
        project_id=project.id,
        code=f"ch-{suffix}",
        name=f"测试渠道-{suffix}",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
        primary_domain="example.com",
    )


def test_lead_attribution_roundtrip(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"lead-{suffix}")
    user = user_factory(f"lead-{suffix}")
    member_factory(project, user, RoleCode.LEAD_OPS)
    question = _question(project, suffix)
    channel = _channel(project, suffix)
    db.add_all([question, channel])
    db.flush()

    response = client.post(
        f"/api/v1/projects/{project.id}/leads",
        headers=auth(user),
        json={
            "contact_name": "归因线索",
            "contact_phone": f"1380000{suffix[:4]}",
            "source_question_id": str(question.id),
            "source_channel_id": str(channel.id),
            "landing_url": "https://base.example.com/landing/q01",
            "utm_campaign": "q-q01-ch-zhihu",
        },
    )
    assert response.status_code == 201, response.text

    lead = db.scalar(
        select(Lead).where(Lead.project_id == project.id, Lead.contact_name == "归因线索")
    )
    assert lead is not None
    assert lead.source_question_id == question.id
    assert lead.source_channel_id == channel.id
    assert lead.landing_url == "https://base.example.com/landing/q01"
    assert lead.utm_campaign == "q-q01-ch-zhihu"

    listed = client.get(
        f"/api/v1/projects/{project.id}/leads", headers=auth(user)
    )
    assert listed.status_code == 200, listed.text
    row = listed.json()["data"][0]
    assert row["source_question_id"] == str(question.id)
    assert row["source_channel_id"] == str(channel.id)
    assert row["utm_campaign"] == "q-q01-ch-zhihu"

    funnel = lead_funnel(db, project.id)
    assert funnel["total_leads"] == 1
    assert funnel["attributed_question"] == 1
    assert funnel["attributed_channel"] == 1
    assert funnel["question_attribution_rate"] == 1.0
    assert funnel["by_question"][0]["question_code"] == question.code
    assert funnel["by_channel"][0]["channel_code"] == channel.code


def test_lead_funnel_empty_project_returns_null_rates(db, project_factory):
    project = project_factory(f"lead-empty-{uuid.uuid4().hex[:6]}")
    funnel = lead_funnel(db, project.id)
    assert funnel["total_leads"] == 0
    assert funnel["question_attribution_rate"] is None
    assert funnel["channel_attribution_rate"] is None
    assert funnel["by_question"] == []


def test_lead_attribution_rejects_question_from_other_project(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"lead-a-{suffix}")
    other = project_factory(f"lead-b-{suffix}")
    user = user_factory(f"lead-a-{suffix}")
    member_factory(project, user, RoleCode.LEAD_OPS)
    other_question = _question(other, suffix)
    db.add(other_question)
    db.flush()

    response = client.post(
        f"/api/v1/projects/{project.id}/leads",
        headers=auth(user),
        json={"contact_name": "跨项目引用", "source_question_id": str(other_question.id)},
    )
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "resource_missing"


def test_attribution_row_and_funnel_dimensions(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"attr-{suffix}")
    editor = user_factory(f"attr-editor-{suffix}")
    member_factory(project, editor, RoleCode.LEAD_OPS)
    question = _question(project, suffix)
    db.add(question)
    db.flush()

    created = client.post(
        f"/api/v1/projects/{project.id}/leads",
        headers=auth(editor),
        json={
            "contact_name": "王先生", "contact_phone": "13800000001",
            "lead_source": "microsite", "utm_campaign": "geo-nov",
            "source_question_id": str(question.id), "landing_url": "https://example.com/s/demo",
        },
    )
    assert created.status_code == 201, created.text
    lead_id = created.json()["data"]["id"]

    row = db.scalar(select(LeadAttribution).where(LeadAttribution.lead_id == uuid.UUID(lead_id)))
    assert row is not None
    assert row.question_id == question.id
    assert row.confidence == "medium"

    detail = client.get(f"/api/v1/projects/{project.id}/leads/{lead_id}/attribution", headers=auth(editor))
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["question_id"] == str(question.id)
    assert detail.json()["data"]["confidence"] == "medium"

    funnel = client.get(f"/api/v1/projects/{project.id}/leads/funnel", headers=auth(editor))
    assert funnel.status_code == 200, funnel.text
    data = funnel.json()["data"]
    assert "by_engine" in data and "by_article" in data
    assert any(item["label"].endswith("测试归因题目") for item in data["by_question"])
