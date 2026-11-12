"""内容覆盖巡检脚本的验收：完整链路无阻断，缺内容/发布/归因能报出来。"""

import hashlib
import uuid
from datetime import datetime, timezone

from app.models import (
    ContentItem,
    ContentVersion,
    ContentVersionQuestion,
    Lead,
    PublishAccount,
    PublishReceipt,
    PublishTask,
    Question,
)
from app.models.enums import (
    ContentKind,
    ContentStatus,
    PublishTaskStatus,
    QuestionStatus,
    QuestionType,
)
from scripts.validate_content_coverage import analyze
from tests.test_stats_export import _make_fixture


def _content_and_receipt(db, project, question, channel):
    suffix = uuid.uuid4().hex[:6]
    body = "# 测试问题\n\n这是可直接摘取的答案。"
    item = ContentItem(
        project_id=project.id,
        kind=ContentKind.MASTER,
        title=f"内容-{suffix}",
        status=ContentStatus.APPROVED,
    )
    db.add(item)
    db.flush()
    version = ContentVersion(
        project_id=project.id,
        item_id=item.id,
        version_no=1,
        body=body,
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        status=ContentStatus.APPROVED,
    )
    db.add(version)
    db.flush()
    db.add(
        ContentVersionQuestion(
            project_id=project.id,
            version_id=version.id,
            question_id=question.id,
        )
    )
    account = PublishAccount(
        project_id=project.id,
        channel_id=channel.id,
        account_name=f"账号-{suffix}",
        credential_ref="secret://test",
    )
    db.add(account)
    db.flush()
    task = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"task-{suffix}",
        idempotency_key=f"idem-{suffix}",
        status=PublishTaskStatus.PUBLISHED,
    )
    db.add(task)
    db.flush()
    db.add(
        PublishReceipt(
            project_id=project.id,
            task_id=task.id,
            published_url="https://example.com/published",
            received_at=datetime.now(timezone.utc),
        )
    )
    return version, task


def test_content_coverage_full_chain_passes(db, project_factory):
    project = project_factory(f"cover-{uuid.uuid4().hex[:6]}")
    fixture = _make_fixture(db, project)
    _content_and_receipt(db, project, fixture["question"], fixture["channel"])
    db.add(
        Lead(
            project_id=project.id,
            contact_name="完整链路线索",
            source_question_id=fixture["question"].id,
            source_channel_id=fixture["channel"].id,
            source_engine_id=fixture["engine"].id,
        )
    )
    db.flush()

    report = analyze(db, project)
    assert report["summary"]["active_questions"] == 1
    assert report["summary"]["blockers"] == 0, report["issues"]
    assert report["questions"][0]["approved_content_count"] >= 1
    assert report["questions"][0]["published_task_count"] >= 1
    assert report["questions"][0]["citation_count"] >= 1
    assert report["questions"][0]["attributed_lead_count"] >= 1


def test_content_coverage_reports_missing_content(db, project_factory):
    project = project_factory(f"cover-gap-{uuid.uuid4().hex[:6]}")
    question = Question(
        project_id=project.id,
        code=f"Q-{uuid.uuid4().hex[:6]}",
        title="没有内容页的 active 题目",
        question_type=QuestionType.BRAND,
        audience="零基础转行者",
        intent="了解课程",
        priority=100,
        status=QuestionStatus.ACTIVE,
        current_version_no=None,
    )
    db.add(question)
    db.flush()

    report = analyze(db, project)
    codes = {item["code"] for item in report["issues"]}
    assert "active_question_no_version" in codes
    assert "active_question_no_content" in codes
    assert "active_question_no_publish" in codes
    assert report["summary"]["blockers"] >= 1
