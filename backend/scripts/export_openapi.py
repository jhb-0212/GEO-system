"""导出 FastAPI OpenAPI 到 docs/openapi.json，并可校验是否与仓库版本一致。

用法（在 backend 目录）：
    .venv\\Scripts\\python.exe scripts\\export_openapi.py
    .venv\\Scripts\\python.exe scripts\\export_openapi.py --check

`--check` 不写文件；发现漂移时以非零退出，适合放进提交前检查。
"""

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402

DEFAULT_OUTPUT = ROOT_DIR / "docs" / "openapi.json"


def render() -> str:
    # 与既有生成器保持一致：UTF-8、两空格缩进、LF、文件末尾不写换行。
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出路径")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args()

    text = render()
    output = args.output.resolve()

    if args.check:
        if not output.is_file():
            print(f"MISSING {output}")
            return 1
        current = output.read_text(encoding="utf-8")
        if current != text:
            print(f"DRIFT {output}")
            return 1
        print(f"OK {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as file:
        file.write(text)
    print(f"WROTE {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
