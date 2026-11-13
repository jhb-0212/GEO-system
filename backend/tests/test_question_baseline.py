"""技术基线激活：保留 v1、生成 v2、6 题进入 active。"""

import uuid

from sqlalchemy import select

from app.models import Question, QuestionVersion
from app.models.enums import QuestionStatus
from app.services.question_baseline import (
    BASELINE_QUESTIONS,
    BASELINE_VERSION_NO,
    activate_technical_baseline,
)


def test_activate_technical_baseline_keeps_v1_and_creates_v2(db, project_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"baseline-{suffix}")
    for item in BASELINE_QUESTIONS:
        question = Question(
            project_id=project.id,
            code=item.code,
            title="【占位待定】旧问法",
            question_type=item.question_type,
            audience="旧人群",
            intent="旧意图",
            priority=100,
            status=QuestionStatus.DRAFT,
            current_version_no=1,
        )
        db.add(question)
        db.flush()
        db.add(
            QuestionVersion(
                project_id=project.id,
                question_id=question.id,
                version_no=1,
                text="【占位待定】旧问法",
                change_note="seed 初始占位版本",
            )
        )
    db.flush()

    result = activate_technical_baseline(db, project.code)

    assert result["activated"] == 6
    assert result["created_versions"] == 6

    rows = db.scalars(
        select(Question).where(Question.project_id == project.id).order_by(Question.code)
    ).all()
    assert len(rows) == 6
    for row, item in zip(rows, BASELINE_QUESTIONS, strict=True):
        assert row.status == QuestionStatus.ACTIVE
        assert row.current_version_no == BASELINE_VERSION_NO
        assert row.title == item.text
        assert row.question_type == item.question_type
        versions = db.scalars(
            select(QuestionVersion)
            .where(QuestionVersion.question_id == row.id)
            .order_by(QuestionVersion.version_no)
        ).all()
        assert [version.version_no for version in versions] == [1, 2]
        assert versions[0].text == "【占位待定】旧问法"
        assert versions[1].text == item.text
        assert versions[1].change_note == "technical-baseline-v1"

    second = activate_technical_baseline(db, project.code)
    assert second["created_versions"] == 0
    assert second["already_active"] == 6
