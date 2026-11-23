"""完整目标库结构对账：目标库 `pg_dump` 规范化后与 `docs/数据库DDL.sql` 逐行 diff。

不是只比表名或计数：`audit_schema.py --check` 负责核对表/索引/约束的生成物；
本脚本负责把目标库的完整 `pg_dump --schema-only --no-owner --no-privileges`
输出与仓库 DDL 基线比较，列、类型、默认值、约束、索引任何差异都会失败。

用法（backend 目录）：
    python scripts/check_schema_ddl.py
    python scripts/check_schema_ddl.py --target postgresql://... --pg-dump /usr/lib/postgresql/16/bin/pg_dump

CI 使用 PostgreSQL 16 client（pg_dump 16），目标库是 backend-ci 的 PostgreSQL 16 service。
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import settings  # noqa: E402

DDL_PATH = ROOT_DIR / "docs" / "数据库DDL.sql"
MAX_DIFF_LINES = 200
_RESTRICT_RE = re.compile(r"^\\(?:restrict|unrestrict)\b")
_SETTING_RE = re.compile(r"^(?:SET\s|SELECT pg_catalog\.set_config\()")


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
        if _RESTRICT_RE.match(line) or _SETTING_RE.match(line):
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


def main() -> int:
    parser = argparse.ArgumentParser(description="目标库完整 DDL 与 docs/数据库DDL.sql 对账")
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

    expected = normalize_dump(DDL_PATH.read_text(encoding="utf-8"))
    actual = normalize_dump(actual_text)
    if actual == expected:
        print(f"OK 结构对账：目标库 schema 与 {DDL_PATH.name} 规范化后完全一致")
        return 0

    diff = list(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=str(DDL_PATH),
            tofile="target-db-schema",
            n=3,
        )
    )
    print("FAIL 结构对账：目标库 schema 与 DDL 基线不一致")
    for line in diff[:MAX_DIFF_LINES]:
        print(line, end="" if line.endswith("\n") else "\n")
    if len(diff) > MAX_DIFF_LINES:
        print(f"... diff 截断，共 {len(diff)} 行；请查看完整 pg_dump 输出")
    return 1


if __name__ == "__main__":
    sys.exit(main())
