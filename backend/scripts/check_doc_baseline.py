"""只读扫描当前有效文档，阻止旧基线数字重新变成“当前值”。

规则：
- `README.md`、`docs/数据库结构说明.md` 是当前事实入口，命中旧数字的行必须显式标注
  “历史 / 当时 / 快照”，否则失败。
- 其余当前文档若整体含有历史章节，允许在文首 20 行内声明“历史快照”；但
  `docs/测试报告.md` 的当前基线块（前 8 行）不允许再出现旧数字。
- 脚本只读，不修改任何文件。

用法（仓库根目录或 backend 目录均可）：
    python backend/scripts/check_doc_baseline.py
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]

CURRENT_DOCS = [
    "README.md",
    "docs/数据库结构说明.md",
    "docs/测试报告.md",
    "docs/交付验收对照表.md",
    "docs/生产部署执行清单.md",
    "docs/DEV_ENV.md",
    "docs/交付包清单.md",
    "docs/API契约.md",
    "docs/提交纪律-OpenAPI基线.md",
    "docs/业务链路验收用例.md",
    "docs/P0缺口工单.md",
    "docs/部署交付清单.md",
    "docs/链路能力矩阵与E2E回归-2026-11-16.md",
]

# 这两个文件是“当前事实入口”，按行判断，不允许把旧数字当成当前值。
STRICT_LINE_DOCS = {"README.md", "docs/数据库结构说明.md"}
# 这些文件的当前基线块不允许出现旧数字（历史章节在后面另行判断）。
TOP_BLOCK_LIMITS = {"docs/测试报告.md": 8}

HISTORY_MARKERS = ("历史", "historical", "history", "快照", "当时", "已过期")

STALE_PATTERNS = (
    "44 张",
    "44 表",
    "45 张",
    "45 表",
    "63 张",
    "63 表",
    "141 索引",
    "143 索引",
    "110 外键",
    "114 外键",
    "41 条表级",
    "49 条表级",
    "103 路径",
    "129 操作",
    "302 schema",
    "65 路径",
    "81 操作",
    "196 schema",
    "65/81/196",
    "103/129/302",
    "167/203/439",
    "d1e2f3a4b5c6",
    "m4f5a6b7c8d9",
    "a9b0c1d2e3f4",
)


def has_history_marker(line: str) -> bool:
    return any(marker in line for marker in HISTORY_MARKERS)


def scan() -> list[str]:
    errors: list[str] = []
    allowed = 0

    for rel in CURRENT_DOCS:
        path = ROOT_DIR / rel
        if not path.is_file():
            errors.append(f"{rel}: 文件不存在")
            continue

        lines = path.read_text(encoding="utf-8").splitlines()
        header_marked = any(has_history_marker(line) for line in lines[:20])
        top_limit = TOP_BLOCK_LIMITS.get(rel)

        for lineno, line in enumerate(lines, 1):
            hit = next((pattern for pattern in STALE_PATTERNS if pattern in line), None)
            if hit is None:
                continue

            if has_history_marker(line):
                allowed += 1
                continue

            if rel in STRICT_LINE_DOCS:
                errors.append(f"{rel}:{lineno}: 当前事实入口出现旧口径 `{hit}`")
                continue

            if top_limit is not None and lineno <= top_limit:
                errors.append(f"{rel}:{lineno}: 当前基线块出现旧口径 `{hit}`")
                continue

            if not header_marked:
                errors.append(
                    f"{rel}:{lineno}: 出现旧口径 `{hit}`，且文首 20 行没有历史快照声明"
                )
            else:
                allowed += 1

    if errors:
        print("FAIL 文档基线检查：")
        for error in errors:
            print(f"  - {error}")
        return errors

    print(f"OK 文档基线检查：{len(CURRENT_DOCS)} 个当前文档，{allowed} 处旧口径已标历史")
    return []


def main() -> int:
    return 1 if scan() else 0


if __name__ == "__main__":
    sys.exit(main())
