"""导出 FastAPI OpenAPI 到 docs/openapi.json，并同步 CI 的计数三元组。

用法（在 backend 目录）：
    .venv\\Scripts\\python.exe scripts\\export_openapi.py
    .venv\\Scripts\\python.exe scripts\\export_openapi.py --check

写文件时会同时把 `.github/workflows/backend-ci.yml` 里的
`(paths, operations, schemas) != (a, b, c)` 与提示文案改成当前实测值——
防止「接口变了但基线没跟」导致中间提交的 CI 变红。

`--check` 不写任何文件；文件漂移或 CI 三元组与实测不符时以非零退出，
适合放进提交前检查或 CI 前置步骤。
"""

import argparse
import json
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402

DEFAULT_OUTPUT = ROOT_DIR / "docs" / "openapi.json"
CI_WORKFLOW = ROOT_DIR / ".github" / "workflows" / "backend-ci.yml"

_COUNT_RE = re.compile(r'!= \((\d+), (\d+), (\d+)\)')
_EXPECT_RE = re.compile(r"期望 (\d+)/(\d+)/(\d+)")


def counts(spec: dict) -> tuple[int, int, int]:
    paths = len(spec.get("paths", {}))
    operations = sum(
        len([m for m in item if m in ("get", "post", "put", "patch", "delete", "head", "options", "trace")])
        for item in spec.get("paths", {}).values()
    )
    schemas = len(spec.get("components", {}).get("schemas", {}))
    return paths, operations, schemas


def render() -> str:
    # 与仓库现有 openapi.json 保持一致：UTF-8、两空格缩进、LF、文件末尾一个换行。
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"


def sync_ci_counts(triple: tuple[int, int, int], *, write: bool) -> bool:
    """把 CI 期望三元组对齐到实测值；write=False 时只检查。返回是否已一致。"""
    if not CI_WORKFLOW.is_file():
        return True
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    want = "".join(str(value) for value in triple)
    found = _COUNT_RE.search(text)
    if found is None:
        return True
    in_sync = found.groups() == tuple(str(value) for value in triple)
    if write and not in_sync:
        text = _COUNT_RE.sub(f"!= ({triple[0]}, {triple[1]}, {triple[2]})", text, count=1)
        text = _EXPECT_RE.sub(f"期望 {triple[0]}/{triple[1]}/{triple[2]}", text, count=1)
        CI_WORKFLOW.write_text(text, encoding="utf-8", newline="\n")
    return in_sync


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出路径")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    parser.add_argument(
        "--no-ci-sync",
        action="store_true",
        help="写文件时不改 backend-ci.yml 的三元组（默认同步）",
    )
    args = parser.parse_args()

    text = render()
    triple = counts(json.loads(text))
    output = args.output.resolve()

    if args.check:
        if not output.is_file():
            print(f"MISSING {output}")
            return 1
        current = output.read_text(encoding="utf-8")
        if current != text:
            print(f"DRIFT {output}（实测 {triple[0]}/{triple[1]}/{triple[2]}）")
            return 1
        if not sync_ci_counts(triple, write=False):
            print(
                f"CI_COUNTS 不一致：backend-ci.yml 期望值与实测 "
                f"{triple[0]}/{triple[1]}/{triple[2]} 不符"
            )
            return 1
        print(f"OK {output}（{triple[0]}/{triple[1]}/{triple[2]}）")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as file:
        file.write(text)
    print(f"WROTE {output}")
    if not args.no_ci_sync:
        updated = sync_ci_counts(triple, write=True)
        print(
            f"CI_COUNTS {'已同步' if not updated else '本就一致'} "
            f"→ {triple[0]}/{triple[1]}/{triple[2]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
