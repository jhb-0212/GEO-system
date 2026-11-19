"""手测样本、证据上传、内容关联与发布状态联动的闭环测试。"""

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    BrandProfile,
    Channel,
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
    AnswerKind,
    ChannelCategory,
    ChannelStatus,
    ContentStatus,
    EngineEntryType,
    EngineProtocol,
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


def _create_task(db, project, *, suffix: str, status: TaskStatus = TaskStatus.DONE):
    engine = AiEngine(code=f"eng-{suffix}", name="测试引擎", vendor="测试厂商")
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(
        engine_id=engine.id,
        entry_type=EngineEntryType.WEB_USER,
        name=f"网页端-{suffix}",
        protocol=EngineProtocol.CUSTOM,
        model_name="test-model",
    )
    db.add(entry)
    db.flush()
    question = Question(
        project_id=project.id,
        code=f"Q-{suffix}",
        title="广州 AI 培训基地哪家靠谱？",
        question_type=QuestionType.BRAND,
        status=QuestionStatus.ACTIVE,
        current_version_no=1,
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(
        project_id=project.id,
        question_id=question.id,
        version_no=1,
        text=question.title,
    )
    db.add(version)
    db.flush()
    round_row = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="单测轮次",
        is_baseline=True,
        status=RoundStatus.COMPLETED,
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
        status=status,
        trace_id=uuid.uuid4().hex,
    )
    db.add(task)
    db.flush()
    return task, entry


def _approve_content(client, base, editor, reviewer, item_id, version_id):
    assert client.post(f"{base}/content-versions/{version_id}/submit", headers=_auth(editor)).status_code == 200
    approved = client.post(
        f"{base}/content-versions/{version_id}/review",
        json={"decision": "approved", "comment": "单测通过"},
        headers=_auth(reviewer),
    )
    assert approved.status_code == 200


def test_manual_sample_and_evidence_upload(
    client, db, project_factory, user_factory, member_factory, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "evidence_local_root", str(tmp_path))
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"manual-{suffix}")
    editor = user_factory(f"manual-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    task, _ = _create_task(db, project, suffix=suffix)
    db.add(
        BrandProfile(
            project_id=project.id,
            canonical_name="广东省AI数字人才就业实训基地",
            aliases=["广东省AI数字人才就业实训基地", "成才基地"],
            identifiers=["广州市天河区测试路 1 号", "020-88888888"],
            owned_domains=["gdccai.com"],
        )
    )
    db.flush()

    response = client.post(
        f"/api/v1/projects/{project.id}/monitoring/tasks/{task.id}/samples",
        headers=_auth(editor),
        json={
            "raw_answer": "推荐广东省AI数字人才就业实训基地，地址是广州市天河区测试路 1 号。",
            "answer_kind": "answer",
            "citation_urls": ["https://36kr.com/p/manual-sample"],
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()["data"]
    assert created["attempt_no"] == 1
    assert created["status"] == "hit"
    assert created["brand_mentioned"] is True
    assert created["brand_identified"] is True
    assert created["citation_count"] == 1
    assert created["answer_kind"] == "answer"
    assert created["conversation_mode"] == "manual"
    assert len(created["conversation_id"]) == 32
    assert created["sampling_mode"] == "search_on"

    # 同一任务再录一次，attempt 追加，不改写第一条自动/手测样本。
    second = client.post(
        f"/api/v1/projects/{project.id}/monitoring/tasks/{task.id}/samples",
        headers=_auth(editor),
        json={"raw_answer": "没有找到相关机构。", "answer_kind": "search_result"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["data"]["attempt_no"] == 2
    assert second.json()["data"]["status"] == "miss"

    sample = db.scalar(select(MonitoringSample).where(MonitoringSample.id == uuid.UUID(created["sample_id"])))
    assert sample is not None
    assert sample.status == SampleStatus.HIT
    assert sample.answer_kind == AnswerKind.ANSWER

    png = b"\x89PNG\r\n\x1a\n" + b"unit-test-evidence"
    uploaded = client.post(
        f"/api/v1/projects/{project.id}/evidence",
        headers=_auth(editor),
        data={"sample_id": created["sample_id"], "file_type": "screenshot"},
        files={"file": ("shot.png", png, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    evidence = uploaded.json()["data"]
    assert evidence["byte_size"] == len(png)
    assert evidence["checksum"] == hashlib.sha256(png).hexdigest()
    stored = tmp_path / "evidence" / str(project.id) / created["sample_id"]
    assert any(stored.glob("*.png"))

    downloaded = client.get(
        f"/api/v1/projects/{project.id}/evidence/{evidence['evidence_id']}/download",
        headers=_auth(editor),
    )
    assert downloaded.status_code == 200
    assert downloaded.content == png

    bad = client.post(
        f"/api/v1/projects/{project.id}/evidence",
        headers=_auth(editor),
        data={"sample_id": created["sample_id"], "file_type": "other"},
        files={"file": ("malware.exe", b"MZ...", "application/octet-stream")},
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "evidence_type_not_allowed"

    task.status = TaskStatus.RUNNING
    db.flush()
    rejected = client.post(
        f"/api/v1/projects/{project.id}/monitoring/tasks/{task.id}/samples",
        headers=_auth(editor),
        json={"raw_answer": "运行中任务补录", "answer_kind": "answer"},
    )
    assert rejected.status_code == 409


def test_content_links_and_status_guard(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"links-{suffix}")
    editor = user_factory(f"links-editor-{suffix}")
    reviewer = user_factory(f"links-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    base = f"/api/v1/projects/{project.id}"

    item_resp = client.post(
        f"{base}/contents",
        json={"title": "证据关联母稿", "kind": "master"},
        headers=_auth(editor),
    )
    assert item_resp.status_code == 201, item_resp.text
    item_id = item_resp.json()["data"]["item_id"]
    version_resp = client.post(
        f"{base}/contents/{item_id}/versions",
        json={"body": "母稿正文：先监测、再写作、后发布。", "change_note": "初稿"},
        headers=_auth(editor),
    )
    assert version_resp.status_code == 201, version_resp.text
    version_id = version_resp.json()["data"]["version_id"]
    _approve_content(client, base, editor, reviewer, item_id, version_id)

    task, _ = _create_task(db, project, suffix=suffix, status=TaskStatus.DONE)
    sample = MonitoringSample(
        project_id=project.id,
        task_id=task.id,
        attempt_no=1,
        status=SampleStatus.HIT,
        sampled_at=datetime.now(timezone.utc),
        raw_answer="广东省AI数字人才就业实训基地",
        answer_kind=AnswerKind.ANSWER,
    )
    db.add(sample)
    db.flush()
    citation = MonitoringCitation(
        project_id=project.id,
        sample_id=sample.id,
        raw_url="https://36kr.com/p/content-link",
        normalized_url="https://36kr.com/p/content-link",
        domain="36kr.com",
    )
    db.add(citation)
    db.flush()

    question_id = str(task.question_version_id)
    # 用 task 关联的问题版本反查 question_id，避免再造一套题库。
    question = db.get(QuestionVersion, task.question_version_id)
    assert question is not None
    question_id = str(question.question_id)

    links = client.put(
        f"{base}/content-versions/{version_id}/links",
        headers=_auth(editor),
        json={"question_ids": [question_id], "citation_ids": [str(citation.id)]},
    )
    assert links.status_code == 200, links.text
    assert links.json()["data"]["question_ids"] == [question_id]
    assert links.json()["data"]["citation_ids"] == [str(citation.id)]

    detail = client.get(f"{base}/content-versions/{version_id}", headers=_auth(editor))
    assert detail.status_code == 200
    assert detail.json()["data"]["question_ids"] == [question_id]
    assert detail.json()["data"]["citation_ids"] == [str(citation.id)]

    scheduled = client.post(
        f"{base}/content-versions/{version_id}/status",
        headers=_auth(editor),
        json={"status": "scheduled"},
    )
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["data"]["status"] == "scheduled"
    assert scheduled.json()["data"]["item_status"] == "scheduled"

    published_manual = client.post(
        f"{base}/content-versions/{version_id}/status",
        headers=_auth(editor),
        json={"status": "published"},
    )
    assert published_manual.status_code == 409
    assert published_manual.json()["error"]["code"] == "review_state_conflict"

    attention = client.post(
        f"{base}/content-versions/{version_id}/status",
        headers=_auth(editor),
        json={"status": "needs_attention"},
    )
    assert attention.status_code == 200, attention.text
    assert attention.json()["data"]["status"] == "needs_attention"

    # 新版本成为 current 后，旧版本不能再改关联。
    next_version = client.post(
        f"{base}/contents/{item_id}/versions",
        json={"body": "第二版正文", "change_note": "替代版本"},
        headers=_auth(editor),
    )
    assert next_version.status_code == 201, next_version.text
    old_links = client.put(
        f"{base}/content-versions/{version_id}/links",
        headers=_auth(editor),
        json={"question_ids": [], "citation_ids": []},
    )
    assert old_links.status_code == 409
    assert old_links.json()["error"]["code"] == "review_state_conflict"


def test_publish_requires_current_version_and_syncs_content_status(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"publish-sync-{suffix}")
    editor = user_factory(f"publish-editor-{suffix}")
    reviewer = user_factory(f"publish-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    base = f"/api/v1/projects/{project.id}"

    channel = Channel(
        project_id=project.id,
        code=f"ch-{suffix}",
        name="单测渠道",
        category=ChannelCategory.INDUSTRY_MEDIA,
        status=ChannelStatus.PUBLISHED,
        primary_domain=f"{suffix}.example.com",
    )
    db.add(channel)
    db.flush()
    account = client.post(
        f"{base}/publish/accounts",
        json={"channel_id": str(channel.id), "account_name": "单测账号"},
        headers=_auth(editor),
    )
    assert account.status_code == 201, account.text
    account_id = account.json()["data"]["id"]

    master = client.post(
        f"{base}/contents", json={"title": "发布母稿", "kind": "master"}, headers=_auth(editor)
    ).json()["data"]["item_id"]
    channel_item = client.post(
        f"{base}/contents",
        json={"title": "渠道稿", "kind": "channel", "parent_id": master, "channel_id": str(channel.id)},
        headers=_auth(editor),
    )
    assert channel_item.status_code == 201, channel_item.text
    item_id = channel_item.json()["data"]["item_id"]

    version_ids = []
    for index in range(2):
        created = client.post(
            f"{base}/contents/{item_id}/versions",
            json={"body": f"渠道正文第 {index + 1} 版", "change_note": f"v{index + 1}"},
            headers=_auth(editor),
        )
        assert created.status_code == 201, created.text
        version_ids.append(created.json()["data"]["version_id"])
        if index == 0:
            _approve_content(client, base, editor, reviewer, item_id, version_ids[0])

    # v1 已通过但已被 v2 替代；发布旧版本必须拒绝。
    old_task = client.post(
        f"{base}/publish/tasks",
        json={
            "version_id": version_ids[0],
            "channel_id": str(channel.id),
            "account_id": account_id,
            "task_key": "old-version",
        },
        headers=_auth(editor),
    )
    assert old_task.status_code == 409
    assert "当前内容版本" in old_task.text

    _approve_content(client, base, editor, reviewer, item_id, version_ids[1])
    task = client.post(
        f"{base}/publish/tasks",
        json={
            "version_id": version_ids[1],
            "channel_id": str(channel.id),
            "account_id": account_id,
            "task_key": "current-version",
        },
        headers=_auth(editor),
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["data"]["task_id"]

    version = db.get(ContentVersion, uuid.UUID(version_ids[1]))
    item = db.get(ContentItem, uuid.UUID(item_id))
    assert version is not None and item is not None
    assert version.status == ContentStatus.SCHEDULED
    assert item.status == ContentStatus.SCHEDULED

    attempt = client.post(
        f"{base}/publish/tasks/{task_id}/attempts",
        json={"result": "success", "mode": "manual"},
        headers=_auth(editor),
    )
    assert attempt.status_code == 201, attempt.text
    db.refresh(version); db.refresh(item)
    assert version.status == ContentStatus.SCHEDULED

    receipt = client.post(
        f"{base}/publish/tasks/{task_id}/receipts",
        json={"published_url": "https://36kr.com/p/publish-sync"},
        headers=_auth(editor),
    )
    assert receipt.status_code == 200, receipt.text
    db.refresh(version); db.refresh(item)
    assert version.status == ContentStatus.PUBLISHED
    assert item.status == ContentStatus.PUBLISHED

    # 同一四元组再次建单仍走幂等复用，不因版本已排期而 409。
    reused = client.post(
        f"{base}/publish/tasks",
        json={
            "version_id": version_ids[1],
            "channel_id": str(channel.id),
            "account_id": account_id,
            "task_key": "current-version",
        },
        headers=_auth(editor),
    )
    assert reused.status_code == 201
    assert reused.json()["data"]["reused"] is True
