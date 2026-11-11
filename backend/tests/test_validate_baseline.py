"""24 测试格验收脚本自身的回归：先证明 6×4 完整数据能通过，再证明缺样本会失败。"""

import uuid
from datetime import datetime, timezone

from app.models import (
    AiEngine,
    AiEngineEntry,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    EngineEntryType,
    QuestionStatus,
    QuestionType,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)
from scripts.validate_baseline import validate


def _make_24_cells(db, project):
    suffix = uuid.uuid4().hex[:6]
    questions = []
    versions = []
    for index in range(6):
        question = Question(
            project_id=project.id,
            code=f"Q{index + 1:02d}-{suffix}",
            title=f"验收问题 {index + 1}",
            question_type=QuestionType.BRAND if index < 3 else QuestionType.GENERAL,
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
            text=f"验收问题 {index + 1} 正文",
        )
        db.add(version)
        db.flush()
        questions.append(question)
        versions.append(version)

    entries = []
    for index in range(4):
        engine = AiEngine(
            code=f"VE{index + 1}-{suffix}",
            name=f"验收引擎 {index + 1}",
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
            name=f"验收入口 {index + 1}-{suffix}",
            supports_search=True,
            is_active=True,
        )
        db.add(entry)
        db.flush()
        entries.append(entry)

    round_row = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="验收基线",
        is_baseline=True,
        status=RoundStatus.COMPLETED,
    )
    db.add(round_row)
    db.flush()

    tasks = []
    for version in versions:
        for entry in entries:
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
                sampled_at=datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc),
                sampling_mode=SamplingMode.SEARCH_ON,
                brand_mentioned=True,
            )
            db.add(sample)
            db.flush()
            tasks.append(task)
    return round_row, tasks


def test_validate_baseline_passes_on_full_24_cells(db, project_factory):
    project = project_factory(f"validate-{uuid.uuid4().hex[:6]}")
    round_row, _ = _make_24_cells(db, project)
    issues = validate(
        db,
        project,
        round_row,
        expect_tasks=24,
        expect_questions=6,
        expect_engines=4,
    )
    assert issues == []


def test_validate_baseline_flags_missing_sample(db, project_factory):
    project = project_factory(f"validate-bad-{uuid.uuid4().hex[:6]}")
    round_row, tasks = _make_24_cells(db, project)
    missing = tasks[-1]
    sample = db.query(MonitoringSample).filter(MonitoringSample.task_id == missing.id).one()
    db.delete(sample)
    db.flush()
    issues = validate(
        db,
        project,
        round_row,
        expect_tasks=24,
        expect_questions=6,
        expect_engines=4,
    )
    assert any("没有任何样本" in issue for issue in issues)
