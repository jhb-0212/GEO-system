"""关键词与题目/内容版本的关联：读取、校验、挂载。

改造前同一套关联有两条实现：
- `_keyword_data`：单个关键词各查两条（题目、版本），用于创建/更新/删除的单条响应；
- `_keyword_rows_data`：批量两条分组查询，用于列表。

两条实现对同一份数据给出的顺序、字段完全靠人肉对齐；新增一个字段就得改两处。
现在只有一条批量实现，单条响应就是「批量传一个」。

`keyword_links` 的读取口径：
- 一个关键词可以挂多个题目（同一批搜索词），也可以挂多个内容版本；
- 顺序按关联 id 升序，保证同一关键词两次请求拿到同样的列表。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    ContentVersion,
    ContentVersionKeyword,
    Keyword,
    Question,
    QuestionKeyword,
)


def keyword_row(
    db: Session,
    project_id: uuid.UUID,
    keyword_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Keyword:
    from app.core.errors import ResourceMissingError

    query = select(Keyword).where(
        Keyword.id == keyword_id,
        Keyword.project_id == project_id,
    )
    if for_update:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise ResourceMissingError("关键词不存在或不属于当前项目", code="keyword_missing")
    return row


def name_exists(
    db: Session,
    project_id: uuid.UUID,
    name: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    stmt = select(Keyword.id).where(
        Keyword.project_id == project_id,
        Keyword.name == name,
    )
    if exclude_id is not None:
        stmt = stmt.where(Keyword.id != exclude_id)
    return db.scalar(stmt) is not None


def page_keywords(
    db: Session,
    project_id: uuid.UUID,
    *,
    category: str | None,
    is_active: bool | None,
    page: int,
    page_size: int,
) -> tuple[int, list[Keyword]]:
    from sqlalchemy import func

    filters = [Keyword.project_id == project_id]
    if category is not None:
        filters.append(Keyword.category == category)
    if is_active is not None:
        filters.append(Keyword.is_active == is_active)
    total = db.scalar(select(func.count()).select_from(Keyword).where(*filters)) or 0
    rows = db.scalars(
        select(Keyword)
        .where(*filters)
        .order_by(Keyword.name, Keyword.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return int(total), list(rows)


def categories(db: Session, project_id: uuid.UUID) -> list[str]:
    rows = db.scalars(
        select(Keyword.category)
        .where(Keyword.project_id == project_id, Keyword.category.is_not(None))
        .distinct()
        .order_by(Keyword.category)
    ).all()
    return [value for value in rows if value]


def keyword_payload(
    row: Keyword,
    question_ids: list[uuid.UUID],
    content_version_ids: list[uuid.UUID],
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "category": row.category,
        "priority": row.priority,
        "is_active": row.is_active,
        "notes": row.notes,
        "question_ids": [str(value) for value in question_ids],
        "content_version_ids": [str(value) for value in content_version_ids],
        "content_version_count": len(content_version_ids),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def keywords_data(db: Session, rows: list[Keyword]) -> list[dict[str, Any]]:
    """批量取关联：两条分组查询替代每个关键词各两条，避免 N+1。"""
    if not rows:
        return []
    keyword_ids = [row.id for row in rows]
    project_id = rows[0].project_id

    question_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for keyword_id, question_id in db.execute(
        select(QuestionKeyword.keyword_id, QuestionKeyword.question_id)
        .where(
            QuestionKeyword.project_id == project_id,
            QuestionKeyword.keyword_id.in_(keyword_ids),
        )
        .order_by(QuestionKeyword.question_id)
    ).all():
        question_map.setdefault(keyword_id, []).append(question_id)

    version_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for keyword_id, version_id in db.execute(
        select(ContentVersionKeyword.keyword_id, ContentVersionKeyword.version_id)
        .where(
            ContentVersionKeyword.project_id == project_id,
            ContentVersionKeyword.keyword_id.in_(keyword_ids),
        )
        .order_by(ContentVersionKeyword.version_id)
    ).all():
        version_map.setdefault(keyword_id, []).append(version_id)

    return [
        keyword_payload(row, question_map.get(row.id, []), version_map.get(row.id, []))
        for row in rows
    ]


def keyword_data(db: Session, row: Keyword) -> dict[str, Any]:
    """单条响应用批量实现的退化形态，避免两条口径再次分叉。"""
    return keywords_data(db, [row])[0]


def validate_links(
    db: Session,
    project_id: uuid.UUID,
    question_ids: list[uuid.UUID],
    content_version_ids: list[uuid.UUID],
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """去重并校验题目/内容版本都属于本项目；返回去重后的列表。"""
    unique_question_ids = list(dict.fromkeys(question_ids))
    unique_version_ids = list(dict.fromkeys(content_version_ids))
    if unique_question_ids:
        found_questions = set(
            db.scalars(
                select(Question.id).where(
                    Question.project_id == project_id,
                    Question.id.in_(unique_question_ids),
                )
            ).all()
        )
        if len(found_questions) != len(unique_question_ids):
            raise AppError("题目不存在或不属于当前项目", code="question_project_mismatch")
    if unique_version_ids:
        found_versions = set(
            db.scalars(
                select(ContentVersion.id).where(
                    ContentVersion.project_id == project_id,
                    ContentVersion.id.in_(unique_version_ids),
                )
            ).all()
        )
        if len(found_versions) != len(unique_version_ids):
            raise AppError(
                "内容版本不存在或不属于当前项目",
                code="content_version_project_mismatch",
            )
    return unique_question_ids, unique_version_ids


def add_links(
    db: Session,
    project_id: uuid.UUID,
    keyword_id: uuid.UUID,
    question_ids: list[uuid.UUID],
    content_version_ids: list[uuid.UUID],
) -> None:
    for question_id in question_ids:
        db.add(
            QuestionKeyword(
                project_id=project_id,
                question_id=question_id,
                keyword_id=keyword_id,
            )
        )
    for version_id in content_version_ids:
        db.add(
            ContentVersionKeyword(
                project_id=project_id,
                version_id=version_id,
                keyword_id=keyword_id,
            )
        )
