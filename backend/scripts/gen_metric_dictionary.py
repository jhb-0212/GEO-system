"""把 `metric_definitions` 表的当前口径渲染成文档段落（自动生成，不手改）。

为什么要这个脚本：`docs/metric-dictionary.md` 是手写的口径叙述，代码里的口径
在 `metric_definitions`（每项目一份、带 rule_version）。两边各写一份必然分叉。
这里的做法是：叙述仍然手写，但「指标定义表」这段由表生成，写进
`<!-- BEGIN:metric-definitions -->` / `<!-- END:metric-definitions -->` 之间。

用法（仓库根目录）：

    backend\\.venv\\Scripts\\python.exe backend\\scripts\\gen_metric_dictionary.py --project-code <code>
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\gen_metric_dictionary.py --check   # 只检查是否有漂移

`--check` 不写文件，发现漂移返回退出码 1，可以直接挂到 CI/提交前检查里。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DOC_PATH = REPO_ROOT / "docs" / "metric-dictionary.md"

BEGIN_MARK = "<!-- BEGIN:metric-definitions（自动生成，勿手改） -->"
END_MARK = "<!-- END:metric-definitions -->"

HEADER = """### 指标定义表（由 `metric_definitions` 表生成）

> 本节由 `backend/scripts/gen_metric_dictionary.py` 生成，**不要手改**；
> 口径叙述在上文各节，改口径先改表（或改种子），再重跑本脚本。
"""


def _fmt(value) -> str:
    if value is None:
        return "—"
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return str(value)


def render(definitions: list[dict]) -> str:
    """把定义列表渲染成 markdown 表格（纯函数，便于测试与 `--check` 对比）。"""
    if not definitions:
        return HEADER + "\n（当前项目没有生效中的指标定义。）\n"
    lines = [
        HEADER,
        "| code | 名称 | 规则版本 | 计算公式 | 生效自 | 状态 |",
        "|---|---|---|---|---|---|",
    ]
    for row in sorted(definitions, key=lambda item: (item["code"], item.get("rule_version", 0))):
        lines.append(
            "| {code} | {name} | v{version} | {formula} | {from_} | {status} |".format(
                code=row["code"],
                name=row["name"],
                version=row.get("rule_version", 1),
                formula=(row.get("formula") or "").replace("|", "\\|"),
                from_=_fmt(row.get("effective_from")),
                status=row.get("status") or "—",
            )
        )
    return "\n".join(lines) + "\n"


def splice(document: str, section: str) -> str:
    """把关卡段替换进文档；缺标记则原样追加到末尾（并给出提示）。"""
    if BEGIN_MARK in document and END_MARK in document:
        head = document.split(BEGIN_MARK, 1)[0]
        tail = document.split(END_MARK, 1)[1]
        return f"{head}{BEGIN_MARK}\n{section}{END_MARK}{tail}"
    return f"{document.rstrip()}\n\n{BEGIN_MARK}\n{section}{END_MARK}\n"


def _load_definitions(project_code: str | None) -> list[dict]:
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import MetricDefinition, Project  # noqa: F401  (模型注册)
    from app.models.enums import MetricStatus, ProjectStatus

    with SessionLocal() as session:
        if project_code:
            code = session.scalar(
                select(Project.code).where(
                    Project.code == project_code, Project.status == ProjectStatus.ACTIVE
                )
            )
            if code is None:
                raise SystemExit(f"项目 {project_code} 不存在或未启用")
        else:
            code = session.scalar(
                select(Project.code)
                .where(Project.status == ProjectStatus.ACTIVE)
                .order_by(Project.created_at)
                .limit(1)
            )
            if code is None:
                raise SystemExit("没有可用项目：先建项目或指定 --project-code")
        rows = session.scalars(
            select(MetricDefinition)
            .join(Project, Project.id == MetricDefinition.project_id)
            .where(
                Project.code == code,
                MetricDefinition.status == MetricStatus.ACTIVE,
            )
            .order_by(MetricDefinition.code, MetricDefinition.rule_version)
        ).all()
        return [
            {
                "code": row.code,
                "name": row.name,
                "rule_version": row.rule_version,
                "formula": row.formula,
                "effective_from": row.effective_from,
                "status": row.status.value,
            }
            for row in rows
        ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成指标定义表段落")
    parser.add_argument("--project-code", default=None, help="项目编码，默认取最早创建的项目")
    parser.add_argument("--check", action="store_true", help="只检查，不写文件")
    args = parser.parse_args(argv)

    section = render(_load_definitions(args.project_code))
    document = DOC_PATH.read_text(encoding="utf-8")
    updated = splice(document, section)

    if args.check:
        if updated != document:
            print("指标定义表与代码不一致：重跑 gen_metric_dictionary.py 后再提交", file=sys.stderr)
            return 1
        print("指标定义表与代码一致")
        return 0

    DOC_PATH.write_text(updated, encoding="utf-8", newline="\n")
    print(f"已写入 {DOC_PATH}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(BACKEND_ROOT))
    raise SystemExit(main())
