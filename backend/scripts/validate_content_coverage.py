"""内容覆盖巡检：只读检查“题目 → 内容 → 发布 → 引用 → 线索”是否能闭合。

检查范围：
1. active 题目是否有当前版本、已审批内容版本、已发布任务及回执；
2. 内容版本是否挂了题目；
3. 已发布任务是否有回执 URL；
4. 引用是否归到渠道；
5. 线索是否带题目/渠道归因。

退出码：
0 = 无阻断项；1 = 有阻断项；2 = 项目不存在。

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe scripts\\validate_content_coverage.py --project-code gz-base
    .venv\\Scripts\\python.exe scripts\\validate_content_coverage.py --project-code edge-validation --json
    .venv\\Scripts\\python.exe scripts\\validate_content_coverage.py --project-code gz-base --output ..\\docs\\内容覆盖巡检.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import and_, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Channel,
    ContentVersion,
    ContentVersionQuestion,
    Lead,
    MonitoringCitation,
    MonitoringSample,
    MonitoringTask,
    Project,
    PublishReceipt,
    PublishTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (  # noqa: E402
    ContentStatus,
    PublishTaskStatus,
    QuestionStatus,
)


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    count: int | None = None,
    samples: list[str] | None = None,
) -> dict:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "count": count,
        "samples": samples or [],
    }


def _question_coverage(session: Session, project: Project) -> dict:
    active = session.scalars(
        select(Question)
        .where(
            Question.project_id == project.id,
            Question.status == QuestionStatus.ACTIVE,
        )
        .order_by(Question.code)
    ).all()
    drafts = session.scalar(
        select(func.count())
        .select_from(Question)
        .where(
            Question.project_id == project.id,
            Question.status == QuestionStatus.DRAFT,
        )
    ) or 0

    current_version_ids: dict = {}
    for question, version in session.execute(
        select(Question, QuestionVersion)
        .join(
            QuestionVersion,
            and_(
                QuestionVersion.question_id == Question.id,
                QuestionVersion.version_no == Question.current_version_no,
            ),
        )
        .where(Question.project_id == project.id)
    ).all():
        current_version_ids[question.id] = version.id

    approved_content: dict = {}
    for question_id, version_id in session.execute(
        select(ContentVersionQuestion.question_id, ContentVersion.id)
        .join(ContentVersion, ContentVersionQuestion.version_id == ContentVersion.id)
        .where(
            ContentVersionQuestion.project_id == project.id,
            ContentVersion.project_id == project.id,
            ContentVersion.status.in_([ContentStatus.APPROVED, ContentStatus.PUBLISHED]),
        )
    ).all():
        approved_content.setdefault(question_id, set()).add(version_id)

    published_tasks: dict = {}
    for question_id, task_id in session.execute(
        select(ContentVersionQuestion.question_id, PublishTask.id)
        .join(ContentVersion, ContentVersionQuestion.version_id == ContentVersion.id)
        .join(PublishTask, PublishTask.version_id == ContentVersion.id)
        .where(
            ContentVersionQuestion.project_id == project.id,
            ContentVersion.project_id == project.id,
            PublishTask.project_id == project.id,
            PublishTask.status == PublishTaskStatus.PUBLISHED,
        )
    ).all():
        published_tasks.setdefault(question_id, set()).add(task_id)

    citations: dict = {}
    for question_id, citation_id in session.execute(
        select(QuestionVersion.question_id, MonitoringCitation.id)
        .join(MonitoringTask, MonitoringTask.question_version_id == QuestionVersion.id)
        .join(MonitoringSample, MonitoringSample.task_id == MonitoringTask.id)
        .join(MonitoringCitation, MonitoringCitation.sample_id == MonitoringSample.id)
        .where(
            QuestionVersion.project_id == project.id,
            MonitoringTask.project_id == project.id,
            MonitoringSample.project_id == project.id,
            MonitoringCitation.project_id == project.id,
        )
    ).all():
        citations.setdefault(question_id, set()).add(citation_id)

    leads: dict = {}
    for question_id, lead_count in session.execute(
        select(Lead.source_question_id, func.count())
        .where(
            Lead.project_id == project.id,
            Lead.source_question_id.is_not(None),
        )
        .group_by(Lead.source_question_id)
    ).all():
        leads[question_id] = lead_count

    rows = []
    blockers = []
    warnings = []
    for question in active:
        row = {
            "code": question.code,
            "title": question.title,
            "question_id": str(question.id),
            "has_current_version": question.id in current_version_ids,
            "approved_content_count": len(approved_content.get(question.id, set())),
            "published_task_count": len(published_tasks.get(question.id, set())),
            "citation_count": len(citations.get(question.id, set())),
            "attributed_lead_count": leads.get(question.id, 0),
        }
        if not row["has_current_version"]:
            blockers.append(
                _issue(
                    "blocker",
                    "active_question_no_version",
                    "active 题目没有当前版本，无法生成监测任务",
                    samples=[f"{question.code}:{question.id}"],
                )
            )
        if row["approved_content_count"] == 0:
            blockers.append(
                _issue(
                    "blocker",
                    "active_question_no_content",
                    "active 题目没有已审批内容版本",
                    samples=[f"{question.code}:{question.id}"],
                )
            )
        if row["published_task_count"] == 0:
            blockers.append(
                _issue(
                    "blocker",
                    "active_question_no_publish",
                    "active 题目没有已发布任务及回执",
                    samples=[f"{question.code}:{question.id}"],
                )
            )
        if row["citation_count"] == 0:
            warnings.append(
                _issue(
                    "warning",
                    "active_question_no_citation",
                    "active 题目尚未监测到引用",
                    samples=[f"{question.code}:{question.id}"],
                )
            )
        rows.append(row)

    return {
        "active_count": len(active),
        "draft_count": drafts,
        "questions": rows,
        "blockers": blockers,
        "warnings": warnings,
    }


def analyze(session: Session, project: Project) -> dict:
    coverage = _question_coverage(session, project)
    issues = list(coverage["blockers"]) + list(coverage["warnings"])

    if coverage["active_count"] == 0:
        issues.append(
            _issue(
                "warning",
                "no_active_questions",
                "项目没有 active 题目，内容/发布/引用/线索无法形成闭环",
                count=coverage["draft_count"],
            )
        )

    orphan_content = session.scalars(
        select(ContentVersion.id)
        .outerjoin(
            ContentVersionQuestion,
            ContentVersionQuestion.version_id == ContentVersion.id,
        )
        .where(
            ContentVersion.project_id == project.id,
            ContentVersionQuestion.id.is_(None),
        )
    ).all()
    if orphan_content:
        issues.append(
            _issue(
                "warning",
                "content_version_without_question",
                "内容版本未挂任何题目，无法反查内容覆盖",
                count=len(orphan_content),
                samples=[str(row) for row in orphan_content[:10]],
            )
        )

    published_without_receipt = session.execute(
        select(PublishTask.id, PublishTask.version_id)
        .outerjoin(PublishReceipt, PublishReceipt.task_id == PublishTask.id)
        .where(
            PublishTask.project_id == project.id,
            PublishTask.status == PublishTaskStatus.PUBLISHED,
            PublishReceipt.id.is_(None),
        )
    ).all()
    if published_without_receipt:
        issues.append(
            _issue(
                "blocker",
                "published_task_without_receipt",
                "已发布任务缺少回执 URL，不能作为结案凭证",
                count=len(published_without_receipt),
                samples=[str(task_id) for task_id, _ in published_without_receipt[:10]],
            )
        )

    citations_without_channel = session.scalar(
        select(func.count())
        .select_from(MonitoringCitation)
        .where(
            MonitoringCitation.project_id == project.id,
            MonitoringCitation.channel_id.is_(None),
        )
    ) or 0
    if citations_without_channel:
        issues.append(
            _issue(
                "warning",
                "citation_without_channel",
                "引用未归到渠道，渠道贡献无法统计",
                count=citations_without_channel,
            )
        )

    leads_without_question = session.scalar(
        select(func.count())
        .select_from(Lead)
        .where(
            Lead.project_id == project.id,
            Lead.source_question_id.is_(None),
        )
    ) or 0
    if leads_without_question:
        issues.append(
            _issue(
                "warning",
                "lead_without_question",
                "线索未归因到题目，无法判断哪条内容带来留资",
                count=leads_without_question,
            )
        )

    leads_without_channel = session.scalar(
        select(func.count())
        .select_from(Lead)
        .where(
            Lead.project_id == project.id,
            Lead.source_channel_id.is_(None),
        )
    ) or 0
    if leads_without_channel:
        issues.append(
            _issue(
                "warning",
                "lead_without_channel",
                "线索未归因到渠道，无法判断哪个渠道带来留资",
                count=leads_without_channel,
            )
        )

    # 渠道字典只用于报告，不作为阻断项：项目不必收录所有渠道。
    channel_count = session.scalar(
        select(func.count())
        .select_from(Channel)
        .where(Channel.project_id == project.id)
    ) or 0

    blockers = [item for item in issues if item["severity"] == "blocker"]
    warnings = [item for item in issues if item["severity"] == "warning"]
    return {
        "project": {"code": project.code, "id": str(project.id), "name": project.name},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "active_questions": coverage["active_count"],
            "draft_questions": coverage["draft_count"],
            "channels": channel_count,
            "blockers": len(blockers),
            "warnings": len(warnings),
        },
        "questions": coverage["questions"],
        "issues": issues,
        "exit_code": 1 if blockers else 0,
    }


def _markdown(report: dict) -> str:
    lines = [
        "# 内容覆盖巡检报告",
        "",
        f"- 项目：`{report['project']['code']}` / {report['project']['name']}",
        f"- 生成时间：{report['generated_at']}",
        f"- 结论：{'不通过，存在阻断项' if report['summary']['blockers'] else '通过，有警告项需跟进'}",
        "",
        "## 汇总",
        "",
        "| 指标 | 数量 |",
        "| --- | ---: |",
        f"| active 题目 | {report['summary']['active_questions']} |",
        f"| draft 题目 | {report['summary']['draft_questions']} |",
        f"| 渠道 | {report['summary']['channels']} |",
        f"| 阻断项 | {report['summary']['blockers']} |",
        f"| 警告项 | {report['summary']['warnings']} |",
        "",
        "## 题目覆盖",
        "",
        "| 题目 | 当前版本 | 已审批内容 | 已发布任务 | 引用 | 归因线索 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in report["questions"]:
        lines.append(
            f"| `{row['code']}` {row['title']} | "
            f"{'有' if row['has_current_version'] else '缺'} | "
            f"{row['approved_content_count']} | "
            f"{row['published_task_count']} | "
            f"{row['citation_count']} | "
            f"{row['attributed_lead_count']} |"
        )
    if not report["questions"]:
        lines.append("| 无 active 题目 | - | - | - | - | - |")
    lines += ["", "## 问题清单", ""]
    if not report["issues"]:
        lines.append("无。")
    else:
        lines += ["| 级别 | 代码 | 说明 | 数量 | 样本 |", "| --- | --- | --- | ---: | --- |"]
        for item in report["issues"]:
            samples = "、".join(item["samples"]) if item["samples"] else "-"
            lines.append(
                f"| {item['severity']} | `{item['code']}` | {item['message']} | "
                f"{item['count'] if item['count'] is not None else '-'} | {samples} |"
            )
    lines += [
        "",
        "## 口径说明",
        "",
        "- 只把 `active` 题目纳入闭环检查；`draft` 只计数，不要求内容/发布/引用。",
        "- 内容闭环要求：当前版本 + 已审批内容版本 + 已发布任务 + 回执 URL。",
        "- 线索归因要求：`source_question_id` 与 `source_channel_id` 至少能回答“哪条内容、哪个渠道带来留资”。",
        "- 本脚本只读，不修改任何数据。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="检查题目-内容-发布-引用-线索覆盖")
    parser.add_argument("--project-code", required=True)
    parser.add_argument("--json", action="store_true", help="输出 JSON 而不是 Markdown")
    parser.add_argument("--output", type=Path, help="写入文件；默认打印到 stdout")
    args = parser.parse_args()

    with SessionLocal() as session:
        project = session.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            message = f"项目不存在：{args.project_code}"
            if args.json:
                print(json.dumps({"error": message}, ensure_ascii=False, indent=2))
            else:
                print(message)
            return 2
        report = analyze(session, project)

    text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json
        else _markdown(report)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text)
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
