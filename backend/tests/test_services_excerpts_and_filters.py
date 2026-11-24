"""口径小工具的单元测试：摘要截断与回执过滤条件。"""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement

from app.models import PublishReceipt, PublishTask
from app.services.excerpts import excerpt
from app.services.publish_listing import receipt_filters


def test_excerpt_collapses_whitespace_and_truncates_with_ellipsis() -> None:
    assert excerpt("  a\n\nb   c  ", 10) == "a b c"
    assert excerpt("x" * 30, 10) == "x" * 10 + "..."
    assert excerpt(None, 10) is None
    assert excerpt("   ", 10) is None


def test_excerpt_can_hard_truncate_without_ellipsis() -> None:
    """引用列表沿用旧行为：硬截断、不加省略号，避免改变既有响应。"""
    assert excerpt("x" * 30, 10, ellipsis=False) == "x" * 10
    assert excerpt("short", 10, ellipsis=False) == "short"


def test_receipt_filters_put_channel_on_task_and_rest_on_receipt() -> None:
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    task_id = uuid.uuid4()
    filters, task_filters = receipt_filters(
        project_id,
        channel_id=channel_id,
        task_id=task_id,
        has_budget=True,
        q="  example.com  ",
    )
    receipts_columns = {_column_name(item) for item in filters}
    assert receipts_columns == {"project_id", "task_id", "budget_approval_id", "published_url"}
    task_columns = {_column_name(item) for item in task_filters}
    assert task_columns == {"project_id", "channel_id"}


def test_receipt_filters_without_optional_args_only_scopes_project() -> None:
    project_id = uuid.uuid4()
    filters, task_filters = receipt_filters(project_id)
    assert {_column_name(item) for item in filters} == {"project_id"}
    assert {_column_name(item) for item in task_filters} == {"project_id"}


def _column_name(clause: ColumnElement) -> str:
    """从过滤条件里取出被比较的列名（`PublishReceipt.project_id == ...` 这种）。"""
    left = clause.left if hasattr(clause, "left") else None
    if left is None:
        raise AssertionError(f"not a binary comparison: {clause!r}")
    model_name = left.table.name
    assert model_name in {PublishReceipt.__tablename__, PublishTask.__tablename__}
    return left.key
