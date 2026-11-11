"""从数据库实际结构生成核对表，避免文档与库脱节。

用法（在 backend 目录）：
    .venv\\Scripts\\python.exe scripts\\audit_schema.py
输出：
    docs/表结构核对表.md
"""

import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import engine  # noqa: E402

# 系统级表白名单：不带 project_id，跨项目共享（必须与 docs/数据库结构说明.md 第 2 条一致）
SYSTEM_LEVEL = {
    "users",
    "roles",
    "permissions",
    "role_permissions",
    "projects",
    "ai_engines",
    "ai_engine_entries",
}
# 迁移元数据表：既不是系统级业务表，也不是项目级业务表
MIGRATION_META = {"alembic_version"}


def query(sql: str) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql))]


def main() -> None:
    tables = [
        row[0]
        for row in query(
            "select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace "
            "where n.nspname='public' and c.relkind='r' order by c.relname"
        )
    ]

    project_cols = {
        name: nullable
        for name, nullable in query(
            "select table_name, is_nullable from information_schema.columns "
            "where table_schema='public' and column_name='project_id'"
        )
    }

    fk_rules = {
        table: rule
        for table, rule in query(
            """
            select c.conrelid::regclass::text, c.confdeltype
            from pg_constraint c
            join pg_class t on t.oid=c.conrelid
            join pg_namespace n on n.oid=t.relnamespace
            join pg_attribute a on a.attrelid=c.conrelid and a.attnum=c.conkey[1]
            where n.nspname='public' and c.contype='f' and a.attname='project_id'
            """
        )
    }
    fk_label = {"r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT", "a": "NO ACTION"}

    idx_count: dict[str, int] = defaultdict(int)
    for table, in query("select tablename from pg_indexes where schemaname='public'"):
        idx_count[table] += 1

    check_count: dict[str, int] = defaultdict(int)
    for table, in query(
        """
        select c.conrelid::regclass::text from pg_constraint c
        join pg_class t on t.oid=c.conrelid
        join pg_namespace n on n.oid=t.relnamespace
        where n.nspname='public' and c.contype='c'
        """
    ):
        check_count[table] += 1

    unique_names: dict[str, list[str]] = defaultdict(list)
    for table, name in query(
        """
        select c.conrelid::regclass::text, c.conname from pg_constraint c
        join pg_class t on t.oid=c.conrelid
        join pg_namespace n on n.oid=t.relnamespace
        where n.nspname='public' and c.contype='u'
        order by 1, 2
        """
    ):
        unique_names[table].append(name)

    total_tables = len(tables)
    lines = [
        "# 表结构核对表（由数据库实际结构生成）",
        "",
        "> 生成脚本：`backend/scripts/audit_schema.py`。本表以库内真实结构为准，与文档描述不一致时以本表为准。",
        "",
        "## 核对结论",
        "",
        f"- 表总数：{total_tables}",
        "",
        "口径定义（四种分类互斥，合计等于表总数）：",
        "",
        f"- 项目业务表（带 `project_id`）：{len(project_cols)} 张",
        f"- 系统级表（白名单，无 `project_id`）：{len([t for t in tables if t in SYSTEM_LEVEL])} 张 —— {sorted(t for t in tables if t in SYSTEM_LEVEL)}",
        f"- 迁移元数据表：{len([t for t in tables if t in MIGRATION_META])} 张 —— {sorted(t for t in tables if t in MIGRATION_META)}",
        f"- 未被以上三类覆盖的表（应为空，非空说明白名单漏项）：{sorted(set(tables) - set(project_cols) - SYSTEM_LEVEL - MIGRATION_META)}",
        "",
        f"- 带 `project_id` 的表：{len(project_cols)}",
        f"- 无 `project_id` 的表：{sorted(set(tables) - set(project_cols))}",
        "",
        "## 逐表核对",
        "",
        "| 表名 | project_id | 可空 | project_id 外键删除行为 | 索引数 | CHECK 约束 | 唯一约束 | 归属 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for table in tables:
        has = table in project_cols
        nullable = project_cols.get(table, "")
        rule = fk_label.get(fk_rules.get(table, ""), "-")
        if table == "alembic_version":
            scope = "迁移元数据"
        elif table in SYSTEM_LEVEL:
            scope = "系统级（白名单）"
        else:
            scope = "项目级"
        uniques = ", ".join(unique_names.get(table, [])) or "-"
        lines.append(
            f"| `{table}` | {'是' if has else '否'} | {nullable or '-'} | {rule} | "
            f"{idx_count.get(table, 0)} | {check_count.get(table, 0)} | {uniques} | {scope} |"
        )

    lines += [
        "",
        "## 系统级表白名单（7 张，新增必须评审）",
        "",
        "| 表 | 说明 |",
        "| --- | --- |",
        "| `users` | 账号，跨项目共享 |",
        "| `roles` | 角色字典，跨项目共享 |",
        "| `permissions` | 能力码字典，跨项目共享 |",
        "| `role_permissions` | 角色—能力映射，跨项目共享 |",
        "| `projects` | 项目注册表本身 |",
        "| `ai_engines` | AI 引擎目录，参考数据 |",
        "| `ai_engine_entries` | 引擎入口目录，参考数据 |",
        "",
        "`alembic_version` 不属于业务表，单独归为**迁移元数据**，不计入系统级白名单。",
        "",
        "除以上表外，所有业务表必须带 `project_id NOT NULL`，外键 `ON DELETE RESTRICT`。",
        "`audit_logs.project_id` 允许为空，仅用于记录系统级操作，项目内操作必须写入。",
        "",
    ]

    out_path = ROOT_DIR / "docs" / "表结构核对表.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成 {out_path}，共 {total_tables} 张表")


if __name__ == "__main__":
    main()
