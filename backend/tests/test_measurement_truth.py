"""测量事实层回归：问题版本语义快照、轮次测量快照、无答案面状态。

三条边界（改坏则历史数据不可比）：
1. 新建问题版本时快照 question_type/audience/intent/priority 与关键词；
   之后修改 Question 元数据不得改变旧版本的解释。
2. 轮次创建时固定品牌词表；轮次中途改 BrandProfile 只影响下一轮，
   本轮执行仍按快照判定。
3. 成功请求但空正文且无引用 → no_answer_surface，不进有效分母。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    BrandProfile,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
    QuestionVersionKeyword,
)
from app.models.enums import (
    EngineEntryType,
    QuestionStatus,
    QuestionType,
    RoleCode,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.measurement_snapshot import SNAPSHOT_VERSION
from app.services.monitoring_batch import create_round
from app.services.monitoring_collection import execute_task
from app.services.monitoring_extraction import AnswerPayload
from app.services.stats import geo_overview


def _auth(user) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"
    }


class FakeAdapter:
    def __init__(self, payload: AnswerPayload) -> None:
        self.payload = payload
        self.calls = 0

    def collect(self, task: MonitoringTask) -> AnswerPayload:
        self.calls += 1
        return self.payload


def _make_question(db, project, *, text="广州基地在哪，怎么报名？") -> tuple[Question, QuestionVersion]:
    question = Question(
        project_id=project.id,
        code=f"Q-{uuid.uuid4().hex[:6]}",
        title=text,
        question_type=QuestionType.BRAND,
        audience="转行人群",
        intent="报名咨询",
        priority=10,
        status=QuestionStatus.ACTIVE,
        current_version_no=1,
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(
        project_id=project.id,
        question_id=question.id,
        version_no=1,
        text=text,
        question_type=QuestionType.BRAND,
        audience="转行人群",
        intent="报名咨询",
        priority=10,
    )
    db.add(version)
    db.flush()
    return question, version


def _make_engine(db) -> tuple[AiEngine, AiEngineEntry]:
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(
        code=f"eng-{suffix}", name=f"引擎-{suffix}", vendor="测试", is_active=True
    )
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(
        engine_id=engine.id,
        entry_type=EngineEntryType.WEB_USER,
        name=f"入口-{suffix}",
        is_active=True,
    )
    db.add(entry)
    db.flush()
    return engine, entry


def _make_task(db, project, round_row, version, entry, *, sampling_no=1) -> MonitoringTask:
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_row.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=sampling_no,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()
    return task


def test_question_version_snapshots_metadata_and_keywords(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"ver-{suffix}")
    editor = user_factory(f"ver-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    headers = _auth(editor)
    base = f"/api/v1/projects/{project.id}"

    created = client.post(
        f"{base}/questions",
        headers=headers,
        json={
            "code": f"Q-{suffix}",
            "title": "广州基地在哪",
            "question_type": "brand",
            "audience": "转行人群",
            "intent": "报名咨询",
            "priority": 10,
            "text": "广州基地在哪，怎么报名？",
        },
    )
    assert created.status_code == 201, created.text
    question_id = created.json()["data"]["id"]

    # 给题目挂一个目标词
    keyword = client.post(
        f"{base}/keywords",
        headers=headers,
        json={
            "name": f"目标词-{suffix}",
            "category": "brand",
            "priority": 5,
            "question_ids": [question_id],
        },
    )
    assert keyword.status_code == 201, keyword.text

    versioned = client.post(
        f"{base}/questions/{question_id}/versions",
        headers=headers,
        json={"text": "广州基地具体地址和报名方式？", "change_note": "补充问法"},
    )
    assert versioned.status_code == 201, versioned.text

    rows = client.get(f"{base}/questions/{question_id}/versions", headers=headers).json()["data"]
    assert len(rows) == 2
    latest = rows[-1]
    assert latest["question_type"] == "brand"
    assert latest["audience"] == "转行人群"
    assert latest["intent"] == "报名咨询"
    assert latest["priority"] == 10

    db.expire_all()
    version2 = db.scalar(
        select(QuestionVersion).where(QuestionVersion.question_id == uuid.UUID(question_id))
        .order_by(QuestionVersion.version_no.desc())
    )
    snapshot_count = db.scalar(
        select(func.count())
        .select_from(QuestionVersionKeyword)
        .where(QuestionVersionKeyword.question_version_id == version2.id)
    )
    assert snapshot_count == 1

    # 改当前题目元数据 + 新开版本：旧版本语义不受影响
    changed = client.patch(
        f"{base}/questions/{question_id}",
        headers=headers,
        json={"intent": "了解课程", "priority": 99},
    )
    assert changed.status_code == 200, changed.text
    versioned2 = client.post(
        f"{base}/questions/{question_id}/versions",
        headers=headers,
        json={"text": "课程怎么选？"},
    )
    assert versioned2.status_code == 201, versioned2.text

    db.expire_all()
    version3 = db.scalar(
        select(QuestionVersion).where(QuestionVersion.question_id == uuid.UUID(question_id))
        .order_by(QuestionVersion.version_no.desc())
    )
    assert version2.intent == "报名咨询" and version2.priority == 10
    assert version3.intent == "了解课程" and version3.priority == 99


def test_round_snapshot_freezes_brand_vocabulary(db, project_factory, user_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"snap-{suffix}")
    actor = user_factory(f"snap-{suffix}")
    profile = BrandProfile(
        project_id=project.id,
        canonical_name="广东省AI数字人才就业实训基地",
        aliases=["旧别名"],
        identifiers=[],
        owned_domains=["gdccai.com"],
        is_active=True,
    )
    db.add(profile)
    db.flush()

    round_row = create_round(
        db,
        project_id=project.id,
        actor_id=actor.id,
        name="快照轮次",
        is_baseline=False,
        planned_at=None,
    )
    snapshot = round_row.analysis_config_snapshot
    assert snapshot["snapshot_version"] == SNAPSHOT_VERSION
    assert round_row.analysis_config_hash
    assert "旧别名" in snapshot["brand"]["mention_terms"]
    assert snapshot["brand"]["owned_domains"] == ["gdccai.com"]

    # 轮次建好后改品牌配置：只影响下一轮，不改变本轮快照
    profile.aliases = ["新别名"]
    db.flush()
    assert "旧别名" in round_row.analysis_config_snapshot["brand"]["mention_terms"]

    _question, version = _make_question(db, project)
    _engine, entry = _make_engine(db)
    task = _make_task(db, project, round_row, version, entry)

    adapter = FakeAdapter(AnswerPayload(text="旧别名提供 AI 实训"))
    result = execute_task(db, project_id=project.id, task_id=task.id, adapter=adapter)
    assert result["status"] == "hit"
    sample = db.scalar(select(MonitoringSample).where(MonitoringSample.task_id == task.id))
    assert sample.status == SampleStatus.HIT
    assert sample.analysis_version == round_row.analysis_config_version
    assert sample.analysis_config_hash == round_row.analysis_config_hash
    assert sample.analyzed_at is not None


def test_empty_answer_is_no_answer_surface_not_miss(db, project_factory, user_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"empty-{suffix}")
    actor = user_factory(f"empty-{suffix}")
    round_row = create_round(
        db,
        project_id=project.id,
        actor_id=actor.id,
        name="无答案面轮次",
        is_baseline=False,
        planned_at=None,
    )
    _question, version = _make_question(db, project)
    _engine, entry = _make_engine(db)
    task = _make_task(db, project, round_row, version, entry)

    adapter = FakeAdapter(AnswerPayload(text=""))
    result = execute_task(db, project_id=project.id, task_id=task.id, adapter=adapter)
    assert result["status"] == "no_answer_surface"
    sample = db.scalar(select(MonitoringSample).where(MonitoringSample.task_id == task.id))
    assert sample.status == SampleStatus.NO_ANSWER_SURFACE

    report = geo_overview(db, project.id, now=datetime.now(timezone.utc))
    assert report["counts"]["total_samples"] == 1
    assert report["counts"]["valid_answers"] == 0
    assert report["counts"]["failed_samples"] == 0
