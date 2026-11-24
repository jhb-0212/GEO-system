"""演练重置只清监测证据链，不碰题目、竞品、品牌与客户配置。"""

import uuid

from sqlalchemy import select

from app.models import MonitoringRound, Question
from app.models.enums import QuestionStatus, QuestionType, RoundStatus
from app.services.demo_reset import reset_project_monitoring


def test_reset_removes_monitoring_but_keeps_questions(db, project_factory):
    project = project_factory(f"reset-{uuid.uuid4().hex[:6]}")
    question = Question(
        project_id=project.id,
        code="Q1",
        title="保留题目",
        question_type=QuestionType.GENERAL,
        priority=100,
        status=QuestionStatus.ACTIVE,
        current_version_no=1,
    )
    db.add(question)
    row = MonitoringRound(
        project_id=project.id, seq=1, name="轮次", is_baseline=True, status=RoundStatus.PLANNING
    )
    db.add(row)
    db.flush()

    counts = reset_project_monitoring(db, project.id)
    assert counts["rounds"] == 1
    db.flush()
    assert db.scalar(select(MonitoringRound).where(MonitoringRound.project_id == project.id)) is None
    assert db.scalar(select(Question).where(Question.project_id == project.id)) is not None


def test_dry_run_reports_counts_without_deleting(db, project_factory):
    project = project_factory(f"reset-{uuid.uuid4().hex[:6]}")
    db.add(
        MonitoringRound(
            project_id=project.id, seq=1, name="轮次", is_baseline=True, status=RoundStatus.PLANNING
        )
    )
    db.flush()

    counts = reset_project_monitoring(db, project.id, dry_run=True)
    assert counts["rounds"] == 1
    assert (
        db.scalar(select(MonitoringRound).where(MonitoringRound.project_id == project.id))
        is not None
    )
