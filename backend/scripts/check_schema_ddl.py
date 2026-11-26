"""完整目标库结构对账：目标库 `pg_dump` 与 `docs/数据库DDL.sql` 做「结构语义」比较。

不是逐行文本 diff。列在 `CREATE TABLE` 里的物理顺序（`attnum`）会因建表路径不同而不同：

- 模型元数据建表（`create_all`）：列按模型定义顺序；
- 历史迁移 `ADD COLUMN`：新列追加在末尾。

R-01 已确认这两条路径都合法，**物理列顺序差异不代表结构不一致**。此前用
`difflib.unified_diff` 直接比较 SQL 文本，把顺序差异判成结构差异，CI 因此误报；
本脚本改为按列名索引比较，同一事实只有一套判据。

比较内容（任一不同即失败）：
- 表集合；每张表的列名集合、每列完整定义（类型、默认值、可空性、精度等）
- 每张表的约束集合与定义（主键 / 外键 / 唯一 / 检查 / 排他）
- 建表之外的语句（索引、`ALTER TABLE`、类型、扩展等）集合

不比较：
- 列的物理顺序（默认忽略；`--strict-column-order` 可显式打开，用于确认差异是否仅为顺序）
- dump 头、注释、会话级 `SET`、pg_dump 随机 token

用法（backend 目录）：
    python scripts/check_schema_ddl.py
    python scripts/check_schema_ddl.py --dump-file path/to/dump.sql
    python scripts/check_schema_ddl.py --target postgresql://... --pg-dump /usr/lib/postgresql/16/bin/pg_dump

CI 使用 PostgreSQL 16 client（pg_dump 16），目标库是 backend-ci 经 `alembic upgrade head`
建出的 PostgreSQL 16 service。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import settings  # noqa: E402

DDL_PATH = ROOT_DIR / "docs" / "数据库DDL.sql"
MAX_REPORTED_DIFFS = 200
SHORTEN_LIMIT = 300
_RESTRICT_RE = re.compile(r"^\\(?:restrict|unrestrict)\b")
_SETTING_RE = re.compile(r"^(?:SET\s|SELECT pg_catalog\.set_config\()")
# pg_dump 16.16 起会带 pg_attver 属性版本标记，属于客户端版本噪声而非结构差异
_ATTVER_RE = re.compile(r"SET \(pg_attver=")
_DOLLAR_QUOTE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")
_WS_RE = re.compile(r"\s+")
_CREATE_TABLE_RE = re.compile(
    r"^CREATE\s+(?:UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.\"]+)\s*\(",
    re.IGNORECASE,
)
_CONSTRAINT_NAME_RE = re.compile(r"^CONSTRAINT\s+([A-Za-z0-9_\"]+)\s+", re.IGNORECASE)
_CONSTRAINT_KEYWORDS = ("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK", "EXCLUDE")


def normalize_dump(text: str) -> str:
    """去掉 dump header、注释、pg_dump 随机 token、会话级 SET 和空行，保留可比较 SQL 主体。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    result: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("--"):
            continue
        if _RESTRICT_RE.match(line) or _SETTING_RE.match(line) or _ATTVER_RE.search(line):
            continue
        result.append(line)
    return "\n".join(result).strip() + "\n"


def run_pg_dump(database_url: str, pg_dump: str) -> str:
    url = make_url(database_url)
    if not url.database:
        raise RuntimeError("DATABASE_URL 缺少数据库名")
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    command = [
        pg_dump,
        "--schema-only",
        "--no-owner",
        "--no-privileges",
        "--no-comments",
        "--format=plain",
        "--dbname",
        url.database,
    ]
    if url.host:
        command += ["--host", url.host]
    if url.port:
        command += ["--port", str(url.port)]
    if url.username:
        command += ["--username", url.username]
    result = subprocess.run(
        command,
        cwd=ROOT_DIR,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"pg_dump 失败：{detail}")
    return result.stdout


@dataclass
class TableModel:
    columns: dict[str, str] = field(default_factory=dict)
    column_order: list[str] = field(default_factory=list)
    constraints: dict[str, str] = field(default_factory=dict)


@dataclass
class SchemaModel:
    tables: dict[str, TableModel] = field(default_factory=dict)
    others: dict[str, str] = field(default_factory=dict)


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", text.strip())


def _shorten(text: str, limit: int = SHORTEN_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _split_statements(text: str) -> list[str]:
    """按顶层 `;` 切语句；引号、$tag$ 与括号内的分号不切。"""
    statements: list[str] = []
    buffer: list[str] = []
    depth = 0
    in_single = False
    in_double = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if in_single:
            buffer.append(char)
            if char == "'":
                if index + 1 < length and text[index + 1] == "'":
                    buffer.append(text[index + 1])
                    index += 2
                    continue
                in_single = False
            index += 1
            continue
        if in_double:
            buffer.append(char)
            if char == '"':
                if index + 1 < length and text[index + 1] == '"':
                    buffer.append(text[index + 1])
                    index += 2
                    continue
                in_double = False
            index += 1
            continue
        if char == "'":
            in_single = True
            buffer.append(char)
            index += 1
            continue
        if char == '"':
            in_double = True
            buffer.append(char)
            index += 1
            continue
        if char == "$":
            match = _DOLLAR_QUOTE_RE.match(text, index)
            if match:
                tag = match.group(0)
                end = text.find(tag, match.end())
                if end == -1:
                    buffer.append(text[index:])
                    index = length
                    continue
                buffer.append(text[index : end + len(tag)])
                index = end + len(tag)
                continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _split_items(body: str) -> list[str]:
    """按顶层 `,` 切表体条目；括号内的逗号（如 CHECK 里的 ARRAY[...]）不切。"""
    items: list[str] = []
    buffer: list[str] = []
    depth = 0
    in_single = False
    in_double = False
    index = 0
    length = len(body)
    while index < length:
        char = body[index]
        if in_single:
            buffer.append(char)
            if char == "'":
                if index + 1 < length and body[index + 1] == "'":
                    buffer.append(body[index + 1])
                    index += 2
                    continue
                in_single = False
            index += 1
            continue
        if in_double:
            buffer.append(char)
            if char == '"':
                if index + 1 < length and body[index + 1] == '"':
                    buffer.append(body[index + 1])
                    index += 2
                    continue
                in_double = False
            index += 1
            continue
        if char == "'":
            in_single = True
        elif char == '"':
            in_double = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            item = "".join(buffer).strip()
            if item:
                items.append(item)
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    tail = "".join(buffer).strip()
    if tail:
        items.append(tail)
    return items


def _matching_paren(text: str, open_index: int) -> int:
    """返回与 `open_index` 处 `(` 匹配的 `)` 下标；找不到时返回 -1。"""
    depth = 0
    in_single = False
    in_double = False
    index = open_index
    length = len(text)
    while index < length:
        char = text[index]
        if in_single:
            if char == "'":
                if index + 1 < length and text[index + 1] == "'":
                    index += 2
                    continue
                in_single = False
            index += 1
            continue
        if in_double:
            if char == '"':
                if index + 1 < length and text[index + 1] == '"':
                    index += 2
                    continue
                in_double = False
            index += 1
            continue
        if char == "'":
            in_single = True
        elif char == '"':
            in_double = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _parse_create_table(statement: str) -> tuple[str, TableModel] | None:
    match = _CREATE_TABLE_RE.match(statement)
    if not match:
        return None
    name = match.group(1).strip('"')
    open_index = statement.index("(", match.end() - 1)
    close_index = _matching_paren(statement, open_index)
    if close_index == -1:
        raise ValueError(f"CREATE TABLE {name} 括号不匹配")
    body = statement[open_index + 1 : close_index]

    table = TableModel()
    for raw_item in _split_items(body):
        item = _norm(raw_item)
        if not item:
            continue
        named = _CONSTRAINT_NAME_RE.match(item)
        if named:
            table.constraints[named.group(1).strip('"')] = item
            continue
        if item.upper().startswith(_CONSTRAINT_KEYWORDS):
            # 未命名约束：以规范化文本为键，避免把顺序当成身份
            table.constraints[item] = item
            continue
        parts = item.split(None, 1)
        column = parts[0].strip('"')
        definition = parts[1] if len(parts) > 1 else ""
        if column in table.columns:
            raise ValueError(f"CREATE TABLE {name} 列 {column} 重复定义")
        table.columns[column] = definition
        table.column_order.append(column)
    return name, table


def build_model(text: str) -> SchemaModel:
    """把 dump 文本解析成按名字索引的结构模型。"""
    model = SchemaModel()
    for statement in _split_statements(normalize_dump(text)):
        parsed = _parse_create_table(statement)
        if parsed:
            name, table = parsed
            if name in model.tables:
                raise ValueError(f"CREATE TABLE {name} 重复出现")
            model.tables[name] = table
        else:
            normalized = _norm(statement)
            model.others[normalized] = normalized
    return model


def compare_models(
    expected: SchemaModel, actual: SchemaModel, *, strict_column_order: bool = False
) -> tuple[list[str], dict[str, tuple[tuple[str, ...], tuple[str, ...]]]]:
    """返回 (差异列表, 仅列顺序不同的表)。差异为空即结构一致。"""
    diffs: list[str] = []
    order_only: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}

    for name in sorted(set(expected.tables) - set(actual.tables)):
        diffs.append(f"缺少表：{name}")
    for name in sorted(set(actual.tables) - set(expected.tables)):
        diffs.append(f"多余表：{name}")

    for name in sorted(set(expected.tables) & set(actual.tables)):
        left = expected.tables[name]
        right = actual.tables[name]

        if left.column_order != right.column_order:
            if strict_column_order:
                diffs.append(
                    f"{name}：列物理顺序不同（基线 {', '.join(left.column_order)} / 目标 {', '.join(right.column_order)}）"
                )
            else:
                order_only[name] = (tuple(left.column_order), tuple(right.column_order))

        for column in sorted(set(left.columns) - set(right.columns)):
            diffs.append(f"{name}：目标库缺少列 {column}")
        for column in sorted(set(right.columns) - set(left.columns)):
            diffs.append(f"{name}：目标库多出列 {column}")
        for column in sorted(set(left.columns) & set(right.columns)):
            if left.columns[column] != right.columns[column]:
                diffs.append(
                    f"{name}.{column}：列定义不同（基线 `{_shorten(left.columns[column])}` / 目标 `{_shorten(right.columns[column])}`）"
                )

        for key in sorted(set(left.constraints) - set(right.constraints)):
            diffs.append(f"{name}：目标库缺少约束 {_shorten(key)}")
        for key in sorted(set(right.constraints) - set(left.constraints)):
            diffs.append(f"{name}：目标库多出约束 {_shorten(key)}")
        for key in sorted(set(left.constraints) & set(right.constraints)):
            if left.constraints[key] != right.constraints[key]:
                diffs.append(
                    f"{name}：约束 {_shorten(key)} 定义不同（基线 `{_shorten(left.constraints[key])}` / 目标 `{_shorten(right.constraints[key])}`）"
                )

    for statement in sorted(set(expected.others) - set(actual.others)):
        diffs.append(f"目标库缺少语句：{_shorten(statement)}")
    for statement in sorted(set(actual.others) - set(expected.others)):
        diffs.append(f"目标库多出语句：{_shorten(statement)}")

    return diffs, order_only


def main() -> int:
    parser = argparse.ArgumentParser(description="目标库完整 DDL 与 docs/数据库DDL.sql 结构对账")
    parser.add_argument(
        "--target",
        default=settings.database_url,
        help="目标库 SQLAlchemy URL；默认取 settings.database_url（必须显式确认目标库）",
    )
    parser.add_argument(
        "--pg-dump",
        default=os.environ.get("PG_DUMP", "pg_dump"),
        help="pg_dump 可执行文件；CI 固定使用 PostgreSQL 16 client",
    )
    parser.add_argument(
        "--dump-file",
        type=Path,
        help="不连接库，直接比较已生成的 dump 文件（用于离线复核/自测）",
    )
    parser.add_argument(
        "--strict-column-order",
        action="store_true",
        help="连列物理顺序一起比较（默认不比；用于确认差异是否仅为顺序）",
    )
    args = parser.parse_args()

    if not DDL_PATH.is_file():
        print(f"FAIL 结构对账：DDL 不存在：{DDL_PATH}")
        return 1

    try:
        actual_text = (
            args.dump_file.read_text(encoding="utf-8")
            if args.dump_file
            else run_pg_dump(args.target, args.pg_dump)
        )
    except (OSError, RuntimeError) as exc:
        print(f"FAIL 结构对账：{exc}")
        print("  请安装 PostgreSQL client（pg_dump 版本不得低于目标库），并显式传入 --target；不要用开发库/生产库代替目标库。")
        return 1

    try:
        expected_model = build_model(DDL_PATH.read_text(encoding="utf-8"))
        actual_model = build_model(actual_text)
    except ValueError as exc:
        print(f"FAIL 结构对账：DDL 解析失败：{exc}")
        return 1

    diffs, order_only = compare_models(
        expected_model, actual_model, strict_column_order=args.strict_column_order
    )
    if not diffs:
        note = ""
        if order_only:
            note = (
                f"；{len(order_only)} 张表存在列物理顺序差异，按列名比较视为结构等价："
                + "、".join(sorted(order_only))
            )
        print(
            f"OK 结构对账：目标库 schema 与 {DDL_PATH.name} 结构一致"
            f"（{len(expected_model.tables)} 张表，{len(expected_model.others)} 条非建表语句）{note}"
        )
        return 0

    print("FAIL 结构对账：目标库 schema 与 DDL 基线不一致")
    for line in diffs[:MAX_REPORTED_DIFFS]:
        print(f"  - {line}")
    if len(diffs) > MAX_REPORTED_DIFFS:
        print(f"  ... 差异截断，共 {len(diffs)} 项；请查看完整 pg_dump 输出")
    return 1


if __name__ == "__main__":
    sys.exit(main())
