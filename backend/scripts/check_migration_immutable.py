"""迁移不可变检查：已合并迁移只允许保留，不允许修改、删除、重命名。

比较 base 分支与 HEAD 的 `migrations/versions` 变更：
- `A`（新增迁移文件）允许；
- `M`、`D`、`R`、`C` 等一律失败，要求改为新增迁移或走书面例外评审。

历史例外（`j0b1c2d3e4f5`、`q9a0b1c2d3e4`）已在合并前发生，本脚本只约束
当前 PR 新引入的改动，不追溯改写历史。

用法（仓库根目录）：
    python backend/scripts/check_migration_immutable.py
    python backend/scripts/check_migration_immutable.py --base origin/main
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = "migrations/versions"


def find_git() -> str:
    candidate = os.environ.get("GIT_EXECUTABLE") or shutil.which("git")
    if candidate:
        return candidate
    for path in (
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        "/usr/bin/git",
        "/usr/local/bin/git",
    ):
        if Path(path).is_file():
            return path
    return "git"


def git(*args: str) -> str:
    result = subprocess.run(
        [find_git(), *args],
        cwd=ROOT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"git {' '.join(args)} 失败：{detail}")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="检查已合并 Alembic 迁移是否被改动")
    parser.add_argument(
        "--base",
        default=os.environ.get("MIGRATION_BASE_REF", "origin/main"),
        help="比较的 base ref，默认 origin/main；CI 可传 origin/${{ github.base_ref }}",
    )
    args = parser.parse_args()

    try:
        git("rev-parse", "--verify", args.base)
    except RuntimeError as exc:
        print(f"FAIL 迁移不可变检查：无法解析 base `{args.base}`")
        print(f"  {exc}")
        print("  CI 请先 git fetch --unshallow 或 fetch-depth: 0；本地先 git fetch origin")
        return 1

    try:
        merge_base = git("merge-base", args.base, "HEAD")
        diff = git(
            "diff",
            "--name-status",
            "--find-renames",
            merge_base,
            "HEAD",
            "--",
            MIGRATIONS_DIR,
        )
    except RuntimeError as exc:
        print(f"FAIL 迁移不可变检查：{exc}")
        return 1

    failures: list[str] = []
    additions = 0
    for line in diff.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        path = parts[-1]
        if status == "A":
            additions += 1
            continue
        failures.append(f"{status}\t{path}")

    if failures:
        print("FAIL 迁移不可变检查：已合并迁移被修改/删除/重命名")
        for item in failures:
            print(f"  - {item}")
        print("  规则：已合并迁移只能保留；结构变更请新增迁移文件，历史例外走书面评审。")
        return 1

    print(
        f"OK 迁移不可变检查：{MIGRATIONS_DIR} 相对 `{args.base}` "
        f"仅有新增 {additions} 个文件，无修改/删除/重命名"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
