"""迁移不可变检查：已合并迁移只允许保留，不允许修改、删除、重命名。

两种显式比较语义：

- `merge-base`：PR 使用，比较目标分支与 HEAD 的共同祖先到 HEAD 的差异。
- `direct`：Push 使用，直接比较事件中的 before 与 after 两棵树，不计算 merge-base。

GitHub Actions 应分别传参：
    PR:
        python backend/scripts/check_migration_immutable.py \
            --event pull_request --comparison merge-base \
            --base "$BASE_SHA"
    Push:
        python backend/scripts/check_migration_immutable.py \
            --event push --comparison direct \
            --base "$BEFORE_SHA" --head "$AFTER_SHA"

规则：
- `A`（新增迁移文件）允许；
- `M`、`D`、`R`、`C` 等一律失败，要求改为新增迁移或走书面例外评审。

任何基准缺失、零 SHA、对象非法、HEAD 与事件 after 不一致、未知事件或比较
模式不匹配，都失败关闭；不回退到 `main`、HEAD 父提交或空字符串。

历史例外（`j0b1c2d3e4f5`、`q9a0b1c2d3e4`）已在合并前发生，本脚本只约束
当前 PR / Push 新引入的改动，不追溯改写历史。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = "migrations/versions"
ZERO_SHA = re.compile(r"^0{40}$")


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


def resolve_commit(label: str, ref: str) -> str:
    if not ref:
        raise RuntimeError(f"{label} 为空；拒绝回退到默认分支")
    if ZERO_SHA.fullmatch(ref):
        raise RuntimeError(
            f"{label}={ref} 是全零 SHA；缺少可比较的历史基准，"
            "需要人工确认初始化基线"
        )
    try:
        commit = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    except RuntimeError as exc:
        raise RuntimeError(f"无法解析 {label} `{ref}`：{exc}") from exc
    object_type = git("cat-file", "-t", commit)
    if object_type != "commit":
        raise RuntimeError(f"{label} `{ref}` 不是 commit，而是 {object_type}")
    return commit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查已合并 Alembic 迁移是否被改动")
    parser.add_argument(
        "--event",
        choices=("pull_request", "push", "local"),
        default="local",
        help="触发事件；PR 使用 merge-base，Push 使用 direct",
    )
    parser.add_argument(
        "--comparison",
        choices=("merge-base", "direct"),
        default="merge-base",
        help="Git 比较语义；PR 必须 merge-base，Push 必须 direct",
    )
    parser.add_argument("--base", required=True, help="比较基准；Push 传 event.before")
    parser.add_argument("--head", default="HEAD", help="比较目标；Push 传 event.after")
    args = parser.parse_args(argv)

    if args.event == "pull_request" and args.comparison != "merge-base":
        print("FAIL 迁移不可变检查：PR 事件必须使用 merge-base 比较")
        return 1
    if args.event == "push" and args.comparison != "direct":
        print("FAIL 迁移不可变检查：Push 事件必须使用 direct 比较")
        return 1

    try:
        base_commit = resolve_commit("--base", args.base.strip())
        head_commit = resolve_commit("--head", args.head.strip())
        checkout_head = git("rev-parse", "HEAD")
    except RuntimeError as exc:
        print(f"FAIL 迁移不可变检查：{exc}")
        return 1

    if head_commit != checkout_head:
        print(
            "FAIL 迁移不可变检查：--head 与当前 checkout HEAD 不一致\n"
            f"  --head={head_commit}\n"
            f"  checkout HEAD={checkout_head}\n"
            "  请确认事件参数与 checkout ref，禁止用错误 SHA 继续比较。"
        )
        return 1

    try:
        if args.comparison == "merge-base":
            diff_base = git("merge-base", base_commit, head_commit)
            if not diff_base:
                raise RuntimeError("merge-base 为空")
        else:
            diff_base = base_commit

        diff = git(
            "diff",
            "--name-status",
            "--find-renames",
            diff_base,
            head_commit,
            "--",
            MIGRATIONS_DIR,
        )
    except RuntimeError as exc:
        print(f"FAIL 迁移不可变检查：{exc}")
        print(
            f"  event={args.event} comparison={args.comparison} "
            f"base={base_commit} head={head_commit}"
        )
        return 1

    failures: list[str] = []
    additions = 0
    for line in diff.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("A") and len(parts) == 2:
            additions += 1
            continue
        failures.append(line)

    if failures:
        print("FAIL 迁移不可变检查：检测到非新增变更（修改/删除/重命名/复制）")
        print(
            f"  event={args.event} comparison={args.comparison} "
            f"base={base_commit} head={head_commit}"
        )
        for item in failures:
            print(f"  - {item}")
        print(
            "  规则：已合并迁移只能保留；结构变更请新增迁移文件，"
            "历史例外走书面评审。"
        )
        return 1

    print(
        f"OK 迁移不可变检查：event={args.event} comparison={args.comparison} "
        f"base={base_commit} head={head_commit}"
    )
    print(
        f"  {MIGRATIONS_DIR} 相对 {diff_base} 仅新增 {additions} 个文件，"
        "无修改/删除/重命名"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
