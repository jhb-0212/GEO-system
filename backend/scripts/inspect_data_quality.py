"""只读数据质量巡检：不改库、不提交事务，输出可复核的 Markdown / JSON 报告。

检查范围：
1. 题库：有效题目画像（audience/intent/priority）、当前版本是否存在；
2. 监控覆盖：轮次/任务/样本数量、最近基线轮次的 6×4 覆盖度；
3. 样本：failed 是否带 failure_code、hit/miss 是否判定 brand_mentioned；
4. 引用：normalized_url / channel_id 缺失、待归类域名、复核状态分布；
5. 证据与审计：证据文件数量、导出审计是否记录 filters。

退出码：
0 = 无阻断项；1 = 有阻断项（需要修数据/补字段）；2 = 项目不存在。

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe scripts\\inspect_data_quality.py --project-code gz-base
    .venv\\Scripts\\python.exe scripts\\inspect_data_quality.py --project-code gz-base --json
    .venv\\Scripts\\python.exe scripts\\inspect_data_quality.py --project-code gz-base --output ..\\docs\\数据质量巡检报告.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AiEngine,
    AiEngineEntry,
    AuditLog,
    Channel,
    EvidenceFile,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
)
from app.models.enums import (  # noqa: E402
    SampleStatus,
    TaskStatus,
)
from app.services import stats  # noqa: E402


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


def _find_round(session, project):
    rounds = session.scalars(
        select(MonitoringRound)
        .where(MonitoringRound.project_id == project.id)
        .order_by(MonitoringRound.seq)
    ).all()
    if not rounds:
        return None, rounds
    baseline = next((row for row in rounds if row.is_baseline), None)
    return baseline or rounds[0], rounds


def _coverage(session, project, round_row) -> dict:
    if round_row is None:
        return {
            "round": None,
            "tasks": 0,
            "questions": 0,
            "engines": 0,
            "combinations": 0,
            "samples": 0,
        }
    rows = session.execute(
        select(
            MonitoringTask.id,
            QuestionVersion.question_id,
            AiEngineEntry.engine_id,
        )
        .select_from(MonitoringTask)
        .join(QuestionVersion, MonitoringTask.question_version_id == QuestionVersion.id)
        .join(AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .where(
            MonitoringTask.project_id == project.id,
            MonitoringTask.round_id == round_row.id,
        )
    ).all()
    combinations = {(question_id, engine_id) for _, question_id, engine_id in rows}
    actual_samples = session.execute(
        select(MonitoringSample.id)
        .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
        .where(
            MonitoringSample.project_id == project.id,
            MonitoringTask.project_id == project.id,
            MonitoringTask.round_id == round_row.id,
        )
    ).all()
    return {
        "round": {
            "id": str(round_row.id),
            "seq": round_row.seq,
            "name": round_row.name,
            "is_baseline": round_row.is_baseline,
            "status": str(round_row.status),
        },
        "tasks": len({row[0] for row in rows}),
        "questions": len({row[1] for row in rows}),
        "engines": len({row[2] for row in rows}),
        "combinations": len(combinations),
        "samples": len(actual_samples),
    }


def inspect(session, project) -> dict:
    issues: list[dict] = []
    generated_at = datetime.now(timezone.utc).isoformat()

    questions = session.scalars(
        select(Question)
        .where(Question.project_id == project.id)
        .order_by(Question.code)
    ).all()
    active_questions = [q for q in questions if str(q.status) == "active"]
    missing_profile = [
        q.code for q in questions if not (q.audience or "").strip()
    ]
    missing_intent = [
        q.code for q in questions if not (q.intent or "").strip()
    ]
    missing_priority = [q.code for q in questions if q.priority is None]
    if questions and not active_questions:
        issues.append(
            _issue(
                "warning",
                "no_active_questions",
                "题库没有 active 题目，24 格无法按有效题库生成；未激活题目 ID 见 samples",
                count=len(questions),
                samples=[f"{q.code}:{q.id}" for q in questions],
            )
        )
    if missing_profile:
        issues.append(
            _issue("blocking", "question_audience_missing", "题目缺 audience（人群）", samples=missing_profile)
        )
    if missing_intent:
        issues.append(
            _issue("blocking", "question_intent_missing", "题目缺 intent（意图）", samples=missing_intent)
        )
    if missing_priority:
        issues.append(
            _issue("blocking", "question_priority_missing", "题目缺 priority", samples=missing_priority)
        )

    version_pairs = {
        (row.question_id, row.version_no)
        for row in session.scalars(
            select(QuestionVersion).where(QuestionVersion.project_id == project.id)
        ).all()
    }
    missing_version = [
        q.code
        for q in questions
        if q.current_version_no is not None and (q.id, q.current_version_no) not in version_pairs
    ]
    if missing_version:
        issues.append(
            _issue("blocking", "question_version_missing", "题目 current_version_no 没有对应版本", samples=missing_version)
        )

    channels = session.scalars(
        select(Channel).where(Channel.project_id == project.id).order_by(Channel.code)
    ).all()
    channel_codes = [c.code for c in channels]
    duplicate_channels = [code for code, count in Counter(channel_codes).items() if count > 1]
    if duplicate_channels:
        issues.append(
            _issue("blocking", "channel_code_duplicate", "渠道 code 重复", samples=duplicate_channels)
        )

    citations = session.scalars(
        select(MonitoringCitation)
        .where(MonitoringCitation.project_id == project.id)
        .order_by(MonitoringCitation.created_at)
    ).all()
    citation_without_normalized = [str(c.id) for c in citations if not c.normalized_url]
    citation_without_channel = [c for c in citations if c.channel_id is None]
    citation_without_domain = [str(c.id) for c in citations if not c.domain]
    if citation_without_normalized:
        issues.append(
            _issue(
                "warning",
                "citation_normalized_url_missing",
                "引用缺 normalized_url，页面去重会漏计",
                count=len(citation_without_normalized),
                samples=citation_without_normalized[:10],
            )
        )
    if citation_without_domain:
        issues.append(
            _issue(
                "warning",
                "citation_domain_missing",
                "引用缺 domain，渠道归类会落空",
                count=len(citation_without_domain),
                samples=citation_without_domain[:10],
            )
        )
    if citation_without_channel:
        pending_domains = Counter((c.domain or "(空域名)") for c in citation_without_channel)
        issues.append(
            _issue(
                "warning",
                "citation_channel_pending",
                "引用未归类到 channel_id，进入待归类队列",
                count=len(citation_without_channel),
                samples=[f"{domain}:{count}" for domain, count in pending_domains.most_common(10)],
            )
        )

    samples = session.scalars(
        select(MonitoringSample)
        .where(MonitoringSample.project_id == project.id)
        .order_by(MonitoringSample.created_at)
    ).all()
    failed_without_code = [
        str(s.id) for s in samples if str(s.status) == str(SampleStatus.FAILED) and not s.failure_code
    ]
    hitmiss_without_brand = [
        str(s.id)
        for s in samples
        if str(s.status) in (str(SampleStatus.HIT), str(SampleStatus.MISS))
        and s.brand_mentioned is None
    ]
    if failed_without_code:
        issues.append(
            _issue(
                "blocking",
                "sample_failed_without_code",
                "failed 样本缺 failure_code，无法解释失败原因",
                count=len(failed_without_code),
                samples=failed_without_code[:10],
            )
        )
    if hitmiss_without_brand:
        issues.append(
            _issue(
                "blocking",
                "sample_brand_flag_missing",
                "hit/miss 样本未判定 brand_mentioned，品牌提及率无法计算",
                count=len(hitmiss_without_brand),
                samples=hitmiss_without_brand[:10],
            )
        )

    rounds = session.scalars(
        select(MonitoringRound)
        .where(MonitoringRound.project_id == project.id)
        .order_by(MonitoringRound.seq)
    ).all()
    tasks = session.scalars(
        select(MonitoringTask)
        .where(MonitoringTask.project_id == project.id)
        .order_by(MonitoringTask.created_at)
    ).all()
    task_sample_counts = Counter(sample.task_id for sample in samples)
    done_without_samples = [
        str(t.id)
        for t in tasks
        if str(t.status) == str(TaskStatus.DONE) and task_sample_counts.get(t.id, 0) == 0
    ]
    failed_task_without_failed_sample = []
    for task in tasks:
        task_samples = [s for s in samples if s.task_id == task.id]
        if str(task.status) == str(TaskStatus.FAILED) and not any(
            str(s.status) == str(SampleStatus.FAILED) and s.failure_code for s in task_samples
        ):
            failed_task_without_failed_sample.append(str(task.id))
    if done_without_samples:
        issues.append(
            _issue(
                "blocking",
                "task_done_without_sample",
                "done 任务没有样本，结果不可追溯",
                count=len(done_without_samples),
                samples=done_without_samples[:10],
            )
        )
    if failed_task_without_failed_sample:
        issues.append(
            _issue(
                "blocking",
                "task_failed_without_failed_sample",
                "failed 任务没有带 failure_code 的 failed 样本",
                count=len(failed_task_without_failed_sample),
                samples=failed_task_without_failed_sample[:10],
            )
        )

    latest_round, _ = _find_round(session, project)
    coverage = _coverage(session, project, latest_round)

    evidence = session.scalars(
        select(EvidenceFile).where(EvidenceFile.project_id == project.id)
    ).all()
    evidence_without_key = [str(e.id) for e in evidence if not (e.storage_key or "").strip()]
    if evidence_without_key:
        issues.append(
            _issue(
                "blocking",
                "evidence_storage_key_missing",
                "证据文件缺 storage_key，无法下载",
                count=len(evidence_without_key),
                samples=evidence_without_key[:10],
            )
        )

    exports = session.scalars(
        select(AuditLog)
        .where(AuditLog.project_id == project.id, AuditLog.action == "export")
        .order_by(AuditLog.created_at)
    ).all()
    export_without_filters = [
        str(row.id)
        for row in exports
        if not isinstance(row.payload, dict) or "filters" not in row.payload
    ]
    if export_without_filters:
        issues.append(
            _issue(
                "warning",
                "export_filters_missing",
                "导出审计没有 filters，无法按原条件复跑",
                count=len(export_without_filters),
                samples=export_without_filters[:10],
            )
        )

    metric = stats.overview(session, project.id)
    by_engine = stats.by_engine(session, project.id)
    by_question = stats.by_question(session, project.id)

    return {
        "generated_at": generated_at,
        "project": {
            "id": str(project.id),
            "code": project.code,
            "name": project.name,
            "timezone": project.timezone,
        },
        "summary": {
            "questions": len(questions),
            "active_questions": len(active_questions),
            "channels": len(channels),
            "rounds": len(rounds),
            "tasks": len(tasks),
            "samples": len(samples),
            "citations": len(citations),
            "evidence_files": len(evidence),
            "exports": len(exports),
            "blocking": sum(1 for item in issues if item["severity"] == "blocking"),
            "warnings": sum(1 for item in issues if item["severity"] == "warning"),
        },
        "question_status": Counter(str(q.status) for q in questions),
        "missing_profile": {
            "audience": missing_profile,
            "intent": missing_intent,
            "priority": missing_priority,
        },
        "coverage": coverage,
        "metrics": metric,
        "by_engine": by_engine,
        "by_question": by_question,
        "sample_status": Counter(str(s.status) for s in samples),
        "citation_review_status": Counter(str(c.review_status) for c in citations),
        "unclassified_domains": [
            {"domain": domain, "count": count}
            for domain, count in Counter(
                (c.domain or "(空域名)") for c in citation_without_channel
            ).most_common(10)
        ],
        "issues": issues,
    }


def _markdown(report: dict) -> str:
    summary = report["summary"]
    coverage = report["coverage"]
    lines = [
        f"# 数据质量巡检：{report['project']['code']}",
        "",
        f"- 生成时间：`{report['generated_at']}`",
        f"- 项目：{report['project']['name']}（{report['project']['code']}）",
        f"- 阻断项：**{summary['blocking']}**；警告：**{summary['warnings']}**",
        "",
        "## 一、资产统计",
        "",
        "| 项 | 数量 |",
        "| --- | --- |",
        f"| 题库 | {summary['questions']}（active {summary['active_questions']}） |",
        f"| 渠道 | {summary['channels']} |",
        f"| 轮次 | {summary['rounds']} |",
        f"| 监测任务 | {summary['tasks']} |",
        f"| 样本 | {summary['samples']} |",
        f"| 引用 | {summary['citations']} |",
        f"| 证据文件 | {summary['evidence_files']} |",
        f"| 导出审计 | {summary['exports']} |",
        "",
        "## 二、题库画像",
        "",
        f"- 缺 audience：{', '.join(report['missing_profile']['audience']) or '无'}",
        f"- 缺 intent：{', '.join(report['missing_profile']['intent']) or '无'}",
        f"- 缺 priority：{', '.join(report['missing_profile']['priority']) or '无'}",
        "",
        "## 三、24 格覆盖度",
        "",
    ]
    if coverage["round"]:
        lines += [
            f"- 轮次：seq={coverage['round']['seq']} / {coverage['round']['name']}（baseline={coverage['round']['is_baseline']}）",
            f"- 任务 {coverage['tasks']}；问题 {coverage['questions']}；引擎 {coverage['engines']}；唯一组合 {coverage['combinations']}；样本 {coverage['samples']}",
            f"- 判定：{'已具备 24 格数据' if coverage['combinations'] >= 24 else '未达到 24 格，需 A/B 生成轮次与任务'}",
        ]
    else:
        lines += [
            "- 当前项目没有任何监测轮次。",
            "- 判定：24 格未开始；需先由 A/B 的轮次/批量任务端点生成数据，再用 `validate_baseline.py` 验收。",
        ]

    lines += [
        "",
        "## 四、指标口径",
        "",
        f"- 有效回答：{report['metrics']['valid_answers']}",
        f"- 品牌提及回答：{report['metrics']['brand_mentioned_answers']}",
        f"- 引用有效回答：{report['metrics']['citation_answers']}",
        f"- 品牌提及率：{report['metrics']['brand_mention_rate']}",
        f"- 引用率：{report['metrics']['citation_rate']}",
        f"- 渠道数：{report['metrics']['channel_count']}；页面数：{report['metrics']['page_count']}",
        f"- 排除：{json.dumps(report['metrics']['excluded'], ensure_ascii=False)}",
        "",
        "## 五、问题清单",
        "",
    ]
    if not report["issues"]:
        lines.append("- 未发现阻断项或警告。")
    else:
        for item in report["issues"]:
            samples = f"；样例：{', '.join(item['samples'])}" if item["samples"] else ""
            count = f"（{item['count']} 条）" if item["count"] is not None else ""
            lines.append(f"- [{item['severity']}] `{item['code']}` {item['message']}{count}{samples}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="只读数据质量巡检")
    parser.add_argument("--project-code", default="gz-base")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    parser.add_argument("--output", type=Path, help="报告写入路径；.json 写 JSON，其余写 Markdown")
    args = parser.parse_args()

    with SessionLocal() as session:
        project = session.scalar(
            select(Project).where(Project.code == args.project_code)
        )
        if project is None:
            print(f"项目不存在：{args.project_code}", file=sys.stderr)
            return 2
        report = inspect(session, project)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.suffix.lower() == ".json":
            content = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        else:
            content = _markdown(report)
        args.output.write_text(content + "\n", encoding="utf-8", newline="\n")
        print(f"报告已写入：{args.output}")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    elif not args.output:
        print(_markdown(report))

    return 1 if report["summary"]["blocking"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
