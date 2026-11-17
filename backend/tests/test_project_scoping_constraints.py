"""数据库级项目归属约束：跨项目关联必须被拒绝（GEO-04）。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringRound,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    EngineEntryType,
    QuestionStatus,
    QuestionType,
    RoundStatus,
    SamplingMode,
    TaskStatus,
)


def _engine_entry(db) -> AiEngineEntry:
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
    return entry


def _question_version(db, project) -> QuestionVersion:
    suffix = uuid.uuid4().hex[:6]
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
        text="正文",
    )
    db.add(version)
    db.flush()
    return version


def test_task_cannot_reference_other_project_round(db, project_factory):
    project_a = project_factory(f"scope-a-{uuid.uuid4().hex[:6]}")
    project_b = project_factory(f"scope-b-{uuid.uuid4().hex[:6]}")
    round_b = MonitoringRound(project_id=project_b.id, seq=1, name="B轮次", status=RoundStatus.RUNNING)
    version_b = _question_version(db, project_b)
    entry = _engine_entry(db)
    db.flush()

    task = MonitoringTask(
        project_id=project_a.id,
        round_id=round_b.id,
        question_version_id=version_b.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
