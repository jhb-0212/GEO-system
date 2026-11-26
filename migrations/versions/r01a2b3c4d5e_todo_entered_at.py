"""R-01：待办周期起始时间 entered_todo_at

Revision ID: r01a2b3c4d5e
Revises: 1b433a0b8b7a
Create Date: 2026-11-26

语义见 app/services/todo_clock.py 模块文档（ADR-01）：
entered_todo_at 记录对象"本次进入当前待办集合"的起始时刻；集合内部迁移与普通
字段更新不刷新，退出集合置 NULL，再次进入重新写入。

本迁移只做两件事：加列、按可回溯证据分级回填。不改业务逻辑、不改接口。
回填原则：证据不足一律留 NULL，禁止用 updated_at 或创建时间猜测。
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "r01a2b3c4d5e"
down_revision = "1b433a0b8b7a"
branch_labels = None
depends_on = None

_NEW_COLUMNS = (
    "publish_tasks",
    "monitoring_tasks",
    "facts",
    "knowledge_documents",
    "knowledge_candidate_facts",
)

_FACT_TODO_SQL = (
    "approval_status IN ('draft', 'pending_review') "
    "OR coalesce(nullif(source_document, ''), nullif(source_url, '')) IS NULL"
)


def _fact_membership(snapshot: Any) -> bool | None:
    """按快照判成员资格；快照缺键则返回 None（不可判定）。"""
    if not isinstance(snapshot, dict):
        return None
    if not {"approval_status", "source_document", "source_url"}.issubset(snapshot):
        return None
    status = snapshot.get("approval_status")
    has_source = bool(snapshot.get("source_document")) or bool(snapshot.get("source_url"))
    return status in {"draft", "pending_review"} or not has_source


def _backfill_facts(bind) -> tuple[int, int, int]:
    """按 FactVersion 顺序重放，取最后一次 false→true 的时间。

    同时执行四项校验，任一失败即降级 NULL：
    1. 快照完整（三键齐全）
    2. version_no 从 1 起严格递增、无缺口
    3. created_at 不早于前一版本
    4. CREATED 行无 previous_snapshot 属设计如此，创建前按"不属于集合"处理
    """
    rows = bind.execute(
        sa.text(
            "SELECT fact_id, version_no, snapshot, created_at "
            "FROM fact_versions ORDER BY fact_id, version_no"
        )
    ).mappings().all()

    replay: dict[uuid.UUID, Any] = {}
    cur_fact = None
    expected_no = 1
    prev_ts = None
    prev_in = False
    last_entry = None
    unreliable = False

    def flush() -> None:
        nonlocal cur_fact, expected_no, prev_ts, prev_in, last_entry, unreliable
        if cur_fact is not None:
            replay[cur_fact] = None if unreliable else last_entry
        cur_fact = None
        expected_no = 1
        prev_ts = None
        prev_in = False
        last_entry = None
        unreliable = False

    for row in rows:
        if row["fact_id"] != cur_fact:
            flush()
            cur_fact = row["fact_id"]
        if unreliable:
            continue
        if row["version_no"] != expected_no:
            unreliable = True
            continue
        expected_no += 1
        membership = _fact_membership(row["snapshot"])
        if membership is None:
            unreliable = True
            continue
        ts = row["created_at"]
        if prev_ts is not None and ts < prev_ts:
            unreliable = True
            continue
        prev_ts = ts
        if not prev_in and membership:
            last_entry = ts
        elif prev_in and not membership:
            last_entry = None
        prev_in = membership
    flush()

    targets = bind.execute(
        sa.text(f"SELECT id FROM facts WHERE {_FACT_TODO_SQL}")
    ).scalars().all()
    filled = 0
    for fact_id in targets:
        ts = replay.get(fact_id)
        if ts is None:
            continue
        bind.execute(
            sa.text("UPDATE facts SET entered_todo_at = :ts WHERE id = :id"),
            {"ts": ts, "id": fact_id},
        )
        filled += 1
    return len(targets), filled, len(targets) - filled


def _stat(bind, table: str, in_set_sql: str) -> tuple[int, int, int]:
    total, filled = bind.execute(
        sa.text(
            f"SELECT count(*), count(entered_todo_at) FROM {table} WHERE {in_set_sql}"
        )
    ).one()
    return int(total), int(filled), int(total) - int(filled)


_EXPECTED_COLUMN = sa.DateTime(timezone=True)


def _assert_column_matches(column: dict, table: str) -> None:
    """已存在列必须与 R-01 定义完全一致，否则立即失败。

    幂等加列只允许"跳过重复创建"，不允许"静默接受结构漂移"：
    类型（含时区）、可空性、默认值任一不符都必须中断迁移。
    """
    column_type = column.get("type")
    problems: list[str] = []
    if not isinstance(column_type, sa.DateTime):
        problems.append(f"类型应为 DateTime，实际 {column_type!r}")
    elif column_type.timezone is not True:
        problems.append("类型必须为 timestamptz（timezone=True），实际无时区")
    if column.get("nullable") is not True:
        problems.append(f"必须可空，实际 nullable={column.get('nullable')}")
    if column.get("default") is not None:
        problems.append(f"不允许默认值，实际 default={column.get('default')!r}")
    if problems:
        raise RuntimeError(
            f"[R-01] {table}.entered_todo_at 已存在但定义与期望不符，拒绝继续迁移："
            + "；".join(problems)
        )


def _assert_table_exists(inspector, table: str) -> None:
    """目标表必须存在；缺失即失败关闭，不允许把表缺失当成"无需加列"。"""
    if table not in set(inspector.get_table_names()):
        raise RuntimeError(f"[R-01] 目标表 {table} 不存在，拒绝继续迁移")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in _NEW_COLUMNS:
        _assert_table_exists(inspector, table)
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        existing = columns.get("entered_todo_at")
        if existing is not None:
            # q3d4e5f6a7b8 用 Base.metadata 建表：干净库重放时这两张表已带该列，
            # 这里必须幂等，且严格校验已有列定义，避免把结构漂移当成"已就绪"。
            _assert_column_matches(existing, table)
            print(f"[R-01] {table}.entered_todo_at 已存在且定义一致（元数据建表所致），跳过 ADD")
            continue
        op.add_column(table, sa.Column("entered_todo_at", _EXPECTED_COLUMN, nullable=True))

    # 发布队列：以审计中的"进入动作"为准；无匹配留空
    bind.execute(
        sa.text(
            """
            UPDATE publish_tasks pt
            SET entered_todo_at = sub.ts
            FROM (
                SELECT al.target_id AS tid, max(al.created_at) AS ts
                FROM audit_logs al
                WHERE al.target_type = 'publish_task'
                  AND (
                        al.action = 'publish.task_create'
                        OR (al.action = 'publish.verify'
                            AND al.payload->>'task_status' IN ('pending', 'needs_review'))
                      )
                GROUP BY al.target_id
            ) sub
            WHERE pt.id = sub.tid
              AND pt.status IN ('pending', 'needs_review')
            """
        )
    )

    # 采集失败：现有审计只记录"领取执行"，不能证明失败发生时刻；一律留空
    # 知识文档：无 ready 历史的，继承素材创建时间（无文档分支此前已属待办）
    bind.execute(
        sa.text(
            """
            UPDATE knowledge_documents d
            SET entered_todo_at = m.created_at
            FROM materials m
            WHERE d.material_id = m.id
              AND d.parse_status <> 'ready'
              AND NOT EXISTS (
                  SELECT 1 FROM audit_logs al
                  WHERE al.target_type = 'material'
                    AND al.target_id = m.id
                    AND al.action = 'knowledge.parse'
                    AND al.payload->>'status' = 'ready'
              )
            """
        )
    )

    # 知识候选：未被处理过的按创建时间；处理过的留空
    bind.execute(
        sa.text(
            """
            UPDATE knowledge_candidate_facts c
            SET entered_todo_at = c.created_at
            WHERE c.status = 'suggested'
              AND NOT EXISTS (
                  SELECT 1 FROM audit_logs al
                  WHERE al.target_type = 'knowledge_candidate_fact'
                    AND al.target_id = c.id
              )
            """
        )
    )

    fact_total, fact_filled, fact_null = _backfill_facts(bind)

    print("[R-01 backfill] facts: in_set=%d filled=%d null=%d" % (fact_total, fact_filled, fact_null))
    for table, sql in (
        ("publish_tasks", "status IN ('pending','needs_review')"),
        ("monitoring_tasks", "status IN ('failed','uncertain')"),
        ("knowledge_documents", "parse_status IN ('pending','parsing','failed','unsupported')"),
        ("knowledge_candidate_facts", "status = 'suggested'"),
    ):
        total, filled, null = _stat(bind, table, sql)
        print("[R-01 backfill] %s: in_set=%d filled=%d null=%d" % (table, total, filled, null))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in _NEW_COLUMNS:
        existing = {column["name"] for column in inspector.get_columns(table)}
        if "entered_todo_at" in existing:
            op.drop_column(table, "entered_todo_at")
