"""在正式 release tag 上生成 release manifest。

产物不提交主分支：由 release 流程写入 `deploy/releases/<tag>.json`，作为 GitHub
Release asset 附加；部署前用 `verify_release.py` 校验 manifest 与容器 label。

用法（仓库根目录，tag 已创建并推送后）：
    python deploy/scripts/create_release_manifest.py --tag v0.1.0
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT_DIR / "deploy" / "releases"


def find_git() -> str:
    candidate = os.environ.get("GIT_EXECUTABLE") or shutil.which("git")
    if candidate:
        return candidate
    for path in (
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
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
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 release manifest")
    parser.add_argument("--tag", required=True, help="已存在的 release tag，例如 v0.1.0")
    parser.add_argument("--output", type=Path, help="输出路径；默认 deploy/releases/<tag>.json")
    args = parser.parse_args()

    try:
        commit = git("rev-list", "-n1", f"refs/tags/{args.tag}")
        tag_object = git("cat-file", "-t", f"refs/tags/{args.tag}")
        previous_main = git("rev-parse", "origin/main")
    except RuntimeError as exc:
        print(f"FAIL 生成 release manifest：{exc}")
        print("  请先创建并推送正式 tag，且确保 origin/main 可解析；禁止用分支 HEAD 生成发布清单。")
        return 1

    output = args.output or DEFAULT_OUTPUT_DIR / f"{args.tag}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "tag": args.tag,
        "tag_object_type": tag_object,
        "commit": commit,
        "commit_short": commit[:12],
        "previous_main": previous_main,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "required_ci_jobs": [
            "backend-ci / backend-test",
            "backend-ci / frontend-check",
            "backend-ci / frontend-e2e-mock",
        ],
        "deploy_variables": {
            "CURRENT_MAIN": "origin/main at release review time",
            "RELEASE_COMMIT": commit,
            "DEPLOYED_COMMIT": "read from container OCI revision label",
        },
        "images": {
            "backend": "geo backend image; label org.opencontainers.image.revision",
            "frontend": "geo frontend image; label org.opencontainers.image.revision",
        },
    }
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK release manifest 已写入：{output}")
    print(f"  tag={args.tag} commit={commit} previous_main={previous_main}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
