"""两条合法迁移路径的 PostgreSQL 端到端对账（R-01 遗留项收口）。

默认跳过；CI 与本地验证用 `GEO_E2E_MIGRATION_PATHS=1` 打开，避免日常
`pytest -q` 每次都跑两遍完整迁移链。

路径 A（空库正常升级，也是 CI 建库方式）：
    空库 → `alembic upgrade head`。`q3d4e5f6a7b8` 会按模型元数据补齐一批表，
    因此 `entered_todo_at` 在 R-01 之前就已存在（列位置按模型顺序），
    R-01 走「已存在且定义一致，跳过 ADD」分支。

路径 B（旧脚本建表的历史库）：
    空库 → `alembic upgrade u5f6a7b8c9d0`
        → 删掉 `entered_todo_at`，还原「旧脚本建表、尚无该列」的历史状态
        → `alembic upgrade head`，R-01 走 ADD COLUMN 分支（列追加到末尾，
          与路径 A 的列物理位置不同）。

断言：
1. 两条路径最终 alembic 版本一致；
2. 表、列（按列名，不比物理顺序）、类型、可空、默认值、主键/外键/唯一/
   检查约束、索引全部等价；
3. 非法结构（`entered_todo_at` 缺时区或类型不符）必须让 R-01 报错，不能被
   静默接受。

不在本文件覆盖的部分：与 `docs/数据库DDL.sql` 的整库对账仍由 CI 的
`check_schema_ddl.py --target` 负责（路径 A 等价于 CI 建库方式）。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import settings

RUN_E2E = os.environ.get("GEO_E2E_MIGRATION_PATHS") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_E2E,
    reason="需要真实 PostgreSQL 与可建库权限；设置 GEO_E2E_MIGRATION_PATHS=1 后运行",
)

ROOT_DIR = Path(__file__).resolve().parents[2]
PRE_R01_REVISION = "u5f6a7b8c9d0"
METADATA_BUILT_TABLES = ("knowledge_documents", "knowledge_candidate_facts")


def _alembic_config() -> Config:
    cfg = Config(str(ROOT_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT_DIR / "migrations"))
    return cfg


def _upgrade(database_url: str, revision: str) -> None:
    """在指定库上执行迁移；`migrations/env.py` 通过 settings 取连接串。"""
    original = settings.database_url
    settings.database_url = database_url
    try:
        command.upgrade(_alembic_config(), revision)
    finally:
        settings.database_url = original


@contextmanager
def _fresh_database(prefix: str) -> Iterator[str]:
    """从 template0 建空库，退出时强制删除。"""
    base = make_url(settings.database_url)
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    target = base.set(database=name)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE template0'))
        try:
            # 注意：`str(URL)` 会把密码渲染成 `***`，直接拿去连库会得到
            # “password authentication failed”；必须用 hide_password=False。
            yield target.render_as_string(hide_password=False)
        finally:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


def _current_revision(database_url: str) -> str:
    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()


def _reset_entered_todo_at(
    database_url: str, tables: tuple[str, ...], ddl_type: str | None
) -> None:
    """把两张表还原成「旧脚本建表、无该列」的历史状态，再按需重建列。

    `q3d4e5f6a7b8` 会从模型元数据补齐这两张表，所以 `u5f6a7b8c9d0` 时列已存在；
    旧脚本建库路径下没有该列。`ddl_type=None` 表示删掉不重建（模拟合法历史库），
    否则按给定 DDL 类型重建（用于非法定义用例）。
    """
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            for table in tables:
                conn.execute(text(f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS entered_todo_at'))
                if ddl_type is not None:
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN entered_todo_at {ddl_type}'))
    finally:
        engine.dispose()


def _schema_snapshot(database_url: str) -> dict[str, dict]:
    """按名索引的结构快照：列物理顺序不参与比较。"""
    engine = create_engine(database_url)
    inspector = inspect(engine)
    snapshot: dict[str, dict] = {}
    try:
        for table in sorted(inspector.get_table_names(schema="public")):
            columns = {
                column["name"]: (
                    str(column["type"]),
                    bool(column["nullable"]),
                    None if column["default"] is None else str(column["default"]),
                )
                for column in inspector.get_columns(table, schema="public")
            }
            pk = inspector.get_pk_constraint(table, schema="public")
            snapshot[table] = {
                "columns": columns,
                "primary_key": (pk.get("name"), tuple(pk.get("constrained_columns") or ())),
                "foreign_keys": sorted(
                    (
                        fk["name"],
                        tuple(fk["constrained_columns"]),
                        fk["referred_table"],
                        tuple(fk["referred_columns"]),
                        (fk.get("options") or {}).get("ondelete"),
                    )
                    for fk in inspector.get_foreign_keys(table, schema="public")
                ),
                "unique_constraints": sorted(
                    (uq["name"], tuple(uq["column_names"]))
                    for uq in inspector.get_unique_constraints(table, schema="public")
                ),
                "check_constraints": sorted(
                    (ck["name"], " ".join(ck["sqltext"].split()))
                    for ck in inspector.get_check_constraints(table, schema="public")
                ),
                "indexes": sorted(
                    (idx["name"], tuple(idx["column_names"]), bool(idx["unique"]))
                    for idx in inspector.get_indexes(table, schema="public")
                ),
            }
    finally:
        engine.dispose()
    return snapshot


def _column_order(database_url: str) -> dict[str, tuple[str, ...]]:
    """列物理顺序（表 → 列名序列），用于证明两条路径确实落在不同位置。"""
    engine = create_engine(database_url)
    inspector = inspect(engine)
    try:
        return {
            table: tuple(column["name"] for column in inspector.get_columns(table, schema="public"))
            for table in inspector.get_table_names(schema="public")
        }
    finally:
        engine.dispose()


def _build_path_a() -> tuple[dict[str, dict], dict[str, tuple[str, ...]]]:
    """路径 A：空库直接 upgrade head，返回结构快照与列物理顺序（库在退出时删除）。"""
    with _fresh_database("geo_e2e_path_a") as url:
        _upgrade(url, "head")
        assert _current_revision(url) == "r01a2b3c4d5e"
        return _schema_snapshot(url), _column_order(url)


def test_path_a_lands_on_head_and_carries_entered_todo_at() -> None:
    snapshot, _ = _build_path_a()
    for table in METADATA_BUILT_TABLES:
        column = snapshot[table]["columns"]["entered_todo_at"]
        assert column[1] is True, f"{table}.entered_todo_at 应为可空"
        assert "TIME" in column[0].upper()


def test_two_legal_paths_are_structurally_equivalent() -> None:
    """路径 A（元数据建表 → 跳过 ADD）与路径 B（旧脚本建表 → ADD COLUMN）必须结构等价。

    路径 A 的最终版本在 `_build_path_a()` 内已断言为 head；这里再断言 B 也落到
    同一版本、且两库结构快照逐表逐项相等（列物理顺序不参与比较）。
    """
    snapshot_a, order_a = _build_path_a()

    with _fresh_database("geo_e2e_path_b") as url_b:
        _upgrade(url_b, PRE_R01_REVISION)
        _reset_entered_todo_at(url_b, METADATA_BUILT_TABLES, None)
        _upgrade(url_b, "head")

        assert _current_revision(url_b) == "r01a2b3c4d5e"
        snapshot_b = _schema_snapshot(url_b)
        order_b = _column_order(url_b)

        # 先证明两条路径确实走了不同分支：列名集合相同，物理位置不同
        # （A 由元数据建表放在模型位置，B 由 R-01 ADD COLUMN 追加到末尾）。
        for table in METADATA_BUILT_TABLES:
            assert set(order_a[table]) == set(order_b[table])
            assert order_a[table] != order_b[table], f"{table} 两条路径列顺序应不同"
            assert order_b[table][-1] == "entered_todo_at", "路径 B 的列应由 R-01 追加到末尾"

        # 结构对账按列名比较，必须判定等价
        assert snapshot_b == snapshot_a



@pytest.mark.parametrize(
    ("ddl_type", "reason"),
    [
        ("TIMESTAMP", "缺时区"),
        ("VARCHAR(64)", "类型不符"),
    ],
)
def test_r01_rejects_illegal_existing_column(ddl_type: str, reason: str) -> None:
    """历史库里的同名列定义不符时，R-01 必须报错而不是静默跳过。"""
    with _fresh_database("geo_e2e_path_bad") as url:
        _upgrade(url, PRE_R01_REVISION)
        _reset_entered_todo_at(url, METADATA_BUILT_TABLES, ddl_type)
        with pytest.raises(Exception, match="entered_todo_at"):
            _upgrade(url, "head")
        # 失败后版本必须停在 R-01 之前，不能留下半迁移状态
        assert _current_revision(url) == PRE_R01_REVISION
