"""题库的读取口径：题目分页、当前版本正文、版本历史与关键词快照。

`api/questions.py` 只留状态迁移、版本追加与审计：

- `question_row` / `page_questions` / `page_versions`：取数与分页；
- `current_text`：题目「当前版本正文」这一列的实际来源；
- `version_keyword_rows`：新版本落关键词快照时读题目当前关键词；
- `code_exists` / `max_version_no`：唯一性与版本号的数据库侧判定。
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ResourceMissingError
from app.models import Question, QuestionKeyword, QuestionVersion


def question_row(
    db: Session,
    project_id: uuid.UUID,
    question_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Question:
    query = select(Question).where(
        Question.id == question_id,
        Question.project_id == project_id,
    )
    if for_update:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise ResourceMissingError("题目不存在或不属于当前项目", code="question_missing")
    return row


def current_text(db: Session, row: Question) -> str | None:
    return db.scalar(
        select(QuestionVersion.text).where(
            QuestionVersion.project_id == row.project_id,
            QuestionVersion.question_id == row.id,
            QuestionVersion.version_no == row.current_version_no,
        )
    )


def version_keyword_rows(
    db: Session, project_id: uuid.UUID, question_id: uuid.UUID
) -> list[QuestionKeyword]:
    return list(
        db.scalars(
            select(QuestionKeyword).where(
                QuestionKeyword.project_id == project_id,
                QuestionKeyword.question_id == question_id,
            )
        ).all()
    )


def page_questions(
    db: Session, filters, *, page: int, page_size: int
) -> tuple[list[Question], int]:
    total = db.scalar(select(func.count()).select_from(Question).where(*filters)) or 0
    rows = db.scalars(
        select(Question)
        .where(*filters)
        .order_by(Question.code, Question.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), int(total)


def page_versions(
    db: Session, filters, *, page: int, page_size: int
) -> tuple[list[QuestionVersion], int]:
    total = (
        db.scalar(select(func.count()).select_from(QuestionVersion).where(*filters)) or 0
    )
    rows = db.scalars(
        select(QuestionVersion)
        .where(*filters)
        .order_by(QuestionVersion.version_no)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), int(total)


def code_exists(db: Session, project_id: uuid.UUID, code: str) -> bool:
    return (
        db.scalar(
            select(Question.id).where(
                Question.project_id == project_id,
                Question.code == code,
            )
        )
        is not None
    )


def max_version_no(
    db: Session, project_id: uuid.UUID, question_id: uuid.UUID
) -> int:
    value = db.scalar(
        select(func.max(QuestionVersion.version_no)).where(
            QuestionVersion.project_id == project_id,
            QuestionVersion.question_id == question_id,
        )
    )
    return int(value or 0)
