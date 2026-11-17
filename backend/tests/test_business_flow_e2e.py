"""已有业务链路 E2E：项目 / 任务 / 样本 / 引用 / 渠道 / 指标 / 导出。

缺失的 B 端点（monitoring/rounds、tasks/batch）不在这里伪造；轮次与任务由 DB 夹具
直接落库，只验证 C 侧已交付的读取、执行、口径与导出口径能串起来。B 端点补齐后，
同一套断言可替换为“API 建轮次 → 批量生成 → 执行 → 复核”。
"""

import csv
import io
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models import AuditLog, MonitoringCitation, MonitoringRound
from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    ChannelCategory,
    ChannelStatus,
    CitationReviewStatus,
    EngineEntryType,
    FailureCode,
    QuestionStatus,
    QuestionType,
    ReviewResult,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from app.services import stats


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _make_flow(db, project):
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(
        code=f"e2e-eng-{suffix}",
        name=f"E2E 引擎-{suffix}",
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
        name=f"E2E 网页端-{suffix}",
        supports_search=True,
        is_active=True,
    )
    db.add(entry)

    question = Question(
        project_id=project.id,
        code=f"E2E-Q-{suffix}",
        title="E2E 测试问题",
        question_type=QuestionType.BRAND,
        audience="零基础转行者",
        intent="了解课程",
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
        text="E2E 测试问题正文",
    )
    db.add(version)

    channel = Channel(
        project_id=project.id,
        code=f"e2e-ch-{suffix}",
        name=f"E2E 渠道-{suffix}",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.OBSERVED,
        primary_domain="e2e.example.com",
    )
    db.add(channel)
    db.flush()

    round_row = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="E2E 基线轮次",
        is_baseline=True,
        status=RoundStatus.RUNNING,
    )
    db.add(round_row)
    db.flush()

    task_done = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.DONE,
    )
    task_pending = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=2,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add_all([task_done, task_pending])
    db.flush()

    sampled_at = datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc)
    samples = [
        MonitoringSample(
            project_id=project.id,
            task_id=task_done.id,
            attempt_no=1,
            status=SampleStatus.HIT,
            sampled_at=sampled_at,
            sampling_mode=SamplingMode.SEARCH_ON,
            brand_mentioned=True,
            review_result=ReviewResult.HIT,
            raw_answer="  第一行\n第二行  ",
        ),
        MonitoringSample(
            project_id=project.id,
            task_id=task_done.id,
            attempt_no=2,
            status=SampleStatus.MISS,
            sampled_at=sampled_at,
            sampling_mode=SamplingMode.SEARCH_ON,
            brand_mentioned=False,
            review_result=ReviewResult.MISS,
        ),
        MonitoringSample(
            project_id=project.id,
            task_id=task_done.id,
            attempt_no=3,
            status=SampleStatus.FAILED,
            sampled_at=sampled_at,
            sampling_mode=SamplingMode.SEARCH_ON,
            failure_code=FailureCode.TIMEOUT,
        ),
    ]
    db.add_all(samples)
    db.flush()

    citation_a = MonitoringCitation(
        project_id=project.id,
        sample_id=samples[0].id,
        raw_url="https://e2e.example.com/a",
        normalized_url="https://e2e.example.com/a",
        domain="e2e.example.com",
        channel_id=channel.id,
        is_brand_related=True,
        review_status=CitationReviewStatus.MANUAL_CONFIRMED,
    )
    citation_b = MonitoringCitation(
        project_id=project.id,
        sample_id=samples[1].id,
        raw_url="https://e2e.example.com/a?utm=x",
        normalized_url="https://e2e.example.com/a",
        domain="e2e.example.com",
        channel_id=channel.id,
        is_brand_related=True,
        review_status=CitationReviewStatus.AUTO,
    )
    db.add_all([citation_a, citation_b])
    db.flush()

    return {
        "engine": engine,
        "entry": entry,
        "question": question,
        "version": version,
        "channel": channel,
        "round": round_row,
        "task_done": task_done,
        "task_pending": task_pending,
        "samples": samples,
    }


def test_existing_chain_task_to_channel_export_and_stats(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"e2e-flow-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"e2e-viewer-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"e2e-editor-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)
    member_factory(project, editor, RoleCode.EDITOR)
    flow = _make_flow(db, project)

    # 1) 任务列表：C 侧读取链路
    tasks = client.get(
        f"/api/v1/projects/{project.id}/monitoring/tasks",
        headers=_auth(viewer),
    )
    assert tasks.status_code == 200
    data = tasks.json()["data"]
    meta = tasks.json()["meta"]
    assert meta["total"] == 2
    assert {row["status"] for row in data} == {"done", "pending"}

    # 2) 执行限制：done 拒绝，pending 受理，重复受理拒绝
    done_exec = client.post(
        f"/api/v1/projects/{project.id}/monitoring/tasks/{flow['task_done'].id}/execute",
        headers=_auth(editor),
    )
    assert done_exec.status_code == 409
    assert done_exec.json()["error"]["code"] == "task_rejected"

    first_exec = client.post(
        f"/api/v1/projects/{project.id}/monitoring/tasks/{flow['task_pending'].id}/execute",
        headers=_auth(editor),
    )
    assert first_exec.status_code == 202
    assert first_exec.json()["data"]["status"] == "running"

    second_exec = client.post(
        f"/api/v1/projects/{project.id}/monitoring/tasks/{flow['task_pending'].id}/execute",
        headers=_auth(editor),
    )
    assert second_exec.status_code == 409
    assert second_exec.json()["error"]["code"] == "task_rejected"

    audit = db.scalars(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.action == "monitoring.execute",
        )
    ).all()
    assert len(audit) == 1
    assert audit[0].payload["from"] == "pending"
    assert audit[0].payload["to"] == "running"

    # 3) 渠道台账 + 明细：引用页去重与回答摘要
    channels = client.get(
        f"/api/v1/projects/{project.id}/channels",
        headers=_auth(viewer),
    )
    assert channels.status_code == 200
    assert channels.json()["meta"]["total"] == 1

    detail = client.get(
        f"/api/v1/projects/{project.id}/channels/{flow['channel'].id}",
        headers=_auth(viewer),
    )
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["citation_count"] == 2
    assert detail_data["sample_count"] == 2
    assert detail_data["page_count"] == 1
    assert detail_data["page_urls"] == ["https://e2e.example.com/a"]
    hit_citations = [
        row
        for row in detail_data["citations"]
        if row["sample_id"] == str(flow["samples"][0].id)
    ]
    assert len(hit_citations) == 1
    assert hit_citations[0]["answer_excerpt"] == "第一行 第二行"

    # 列表只回摘要字段：大字段留在单条详情里，避免一页放大到几十 MB
    sample_list = client.get(
        f"/api/v1/projects/{project.id}/monitoring/samples",
        headers=_auth(editor),
    )
    assert sample_list.status_code == 200
    listed = sample_list.json()["data"]
    assert listed
    # 列表不再回传大字段内容：字段存在但为 null，避免破坏既有契约
    assert listed[0]["raw_answer"] is None
    assert listed[0]["raw_response"] is None
    assert listed[0]["request_payload"] is None
    assert any(row["answer_excerpt"] for row in listed)

    # 4) 多维导出：同一渠道一行，筛选参数进审计
    export = client.get(
        f"/api/v1/projects/{project.id}/channels/export",
        params={
            "engine_id": str(flow["engine"].id),
            "question_id": str(flow["question"].id),
            "start_date": "2026-11-11",
            "end_date": "2026-11-11",
        },
        headers=_auth(viewer),
    )
    assert export.status_code == 200
    rows = list(csv.DictReader(io.StringIO(export.content.decode("utf-8"))))
    assert len(rows) == 1
    assert rows[0]["code"] == flow["channel"].code
    assert rows[0]["citation_count"] == "2"
    assert rows[0]["sample_count"] == "2"
    assert rows[0]["page_count"] == "1"
    assert flow["engine"].code in rows[0]["engine_codes"]
    assert flow["question"].code in rows[0]["question_codes"]

    # 5) 指标口径：failed 不进分母，manual_confirmed 才算引用
    overview = stats.overview(db, project.id)
    assert overview["valid_answers"] == 2
    assert overview["brand_mention_rate"] == 0.5
    assert overview["citation_rate"] == 0.5
    assert overview["channel_count"] == 1
    assert overview["page_count"] == 1
    assert overview["excluded"] == {"failed": 1, "manual_review": 0, "pending_or_running": 0}


def test_filtered_channel_export_blocks_when_citation_rows_exceed_limit(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    """筛选导出的上限按「引用行数」卡：渠道只有 1 个，但引用超过同步上限也要拒。"""
    project = project_factory(f"e2e-export-limit-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"e2e-export-viewer-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)
    flow = _make_flow(db, project)  # 同一渠道带 2 条引用

    monkeypatch.setattr(settings, "export_sync_row_limit", 1)

    blocked = client.get(
        f"/api/v1/projects/{project.id}/channels/export",
        params={"engine_id": str(flow["engine"].id)},
        headers=_auth(viewer),
    )
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "export_too_large"

    # 无筛选的全量渠道导出只有 1 行，不受影响
    full = client.get(
        f"/api/v1/projects/{project.id}/channels/export",
        headers=_auth(viewer),
    )
    assert full.status_code == 200


def test_existing_chain_permission_and_scope_gate(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"e2e-gate-{uuid.uuid4().hex[:6]}")
    viewer = user_factory(f"e2e-gate-viewer-{uuid.uuid4().hex[:6]}")
    outsider = user_factory(f"e2e-gate-outsider-{uuid.uuid4().hex[:6]}")
    member_factory(project, viewer, RoleCode.VIEWER)
    flow = _make_flow(db, project)

    # 非项目成员不能读任务 / 渠道明细，且不能借 404 探测存在性
    outsider_tasks = client.get(
        f"/api/v1/projects/{project.id}/monitoring/tasks",
        headers=_auth(outsider),
    )
    assert outsider_tasks.status_code == 403
    assert outsider_tasks.json()["error"]["code"] == "project_forbidden"

    outsider_detail = client.get(
        f"/api/v1/projects/{project.id}/channels/{flow['channel'].id}",
        headers=_auth(outsider),
    )
    assert outsider_detail.status_code == 403

    # 只读成员不能触发执行
    viewer_exec = client.post(
        f"/api/v1/projects/{project.id}/monitoring/tasks/{flow['task_pending'].id}/execute",
        headers=_auth(viewer),
    )
    assert viewer_exec.status_code == 403
    assert viewer_exec.json()["error"]["code"] == "insufficient_permission"

    # 不存在的渠道返回 404，不泄露项目内其他资源
    missing = client.get(
        f"/api/v1/projects/{project.id}/channels/{uuid.uuid4()}",
        headers=_auth(viewer),
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "resource_missing"
