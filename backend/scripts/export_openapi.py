"""导出 FastAPI OpenAPI 到 docs/openapi.json，并做逐字节一致性校验。

用法（在 backend 目录）：
    .venv\\Scripts\\python.exe scripts\\export_openapi.py
    .venv\\Scripts\\python.exe scripts\\export_openapi.py --check

`docs/openapi.json` 是唯一导出物；CI 不再维护第二组路径/操作/schema 数字，
`--check` 直接比较 `app.openapi()` 的确定性导出与仓库文件是否逐字节一致。
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402

DEFAULT_OUTPUT = ROOT_DIR / "docs" / "openapi.json"


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出路径")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args()

    text = render()
    triple = counts(json.loads(text))
    output = args.output.resolve()

    if args.check:
        if not output.is_file():
            print(f"MISSING {output}")
            return 1
        committed = output.read_text(encoding="utf-8")
        if committed != text:
            print(f"DRIFT {output}（实测 {triple[0]}/{triple[1]}/{triple[2]}）")
            return 1
        sha256 = hashlib.sha256(committed.encode("utf-8")).hexdigest().upper()
        print(
            f"OK {output}（{triple[0]}/{triple[1]}/{triple[2]}）"
            f" sha256={sha256}"
        )
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as file:
        file.write(text)
    print(f"WROTE {output}（{triple[0]}/{triple[1]}/{triple[2]}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
