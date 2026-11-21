"""月度报告快照：把某个月的报告冻结成不可变副本，供复盘、对比和审计。

月报是跨任务/样本/发布回执的聚合结果；数据持续变化时，同一月份的历史口径会被
重算。这里在月末或复盘时显式冻结一份，列表只读快照，不再重新聚合。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.models import MonthlyReportSnapshot, Project
from app.services.citation_classification import CLASSIFIER_VERSION
from app.services.monitoring_extraction import MATCHER_VERSION
from app.services.reports import monthly_report

MONTHLY_REPORT_RULE_VERSION = "monthly-report-v1"


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _report_hash(report: dict[str, Any]) -> str:
    payload = json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_monthly_report_snapshot(
    db: Session,
    project: Project,
    *,
    month: str,
    actor_id: uuid.UUID | None,
    include_leads: bool,
) -> MonthlyReportSnapshot:
    existing = db.scalar(
        select(MonthlyReportSnapshot).where(
            MonthlyReportSnapshot.project_id == project.id,
            MonthlyReportSnapshot.month == month,
        )
    )
    if existing is not None:
        raise ConflictError(
            "该月份已冻结月报快照", code="monthly_report_snapshot_exists"
        )

    report = _jsonable(
        monthly_report(db, project, month=month, include_leads=include_leads)
    )
    digest = _report_hash(report)
    snapshot = MonthlyReportSnapshot(
        project_id=project.id,
        month=report["month"],
        period_start=datetime.fromisoformat(str(report["period_start"])),
        period_end=datetime.fromisoformat(str(report["period_end"])),
        captured_by=actor_id,
        captured_at=datetime.now(timezone.utc),
        report=report,
        definitions={
            "report": MONTHLY_REPORT_RULE_VERSION,
            "matcher": MATCHER_VERSION,
            "classifier": CLASSIFIER_VERSION,
            "leads_included": include_leads,
        },
        rule_version=MONTHLY_REPORT_RULE_VERSION,
        snapshot_hash=digest,
    )
    db.add(snapshot)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "该月份已冻结月报快照", code="monthly_report_snapshot_exists"
        ) from exc
    return snapshot


def monthly_summary_payload(
    row: MonthlyReportSnapshot,
    *,
    captured_by_name: str | None = None,
) -> dict[str, Any]:
    tasks = row.report.get("tasks", {})
    answers = row.report.get("answers", {})
    breakdown = row.report.get("answer_breakdown") or {}
    general = breakdown.get("general") or {}
    brand = breakdown.get("brand") or {}
    return {
        "snapshot_id": str(row.id),
        "month": row.month,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "captured_at": row.captured_at,
        "captured_by": str(row.captured_by) if row.captured_by else None,
        "captured_by_name": captured_by_name,
        "rule_version": row.rule_version,
        "snapshot_hash": row.snapshot_hash,
        "tasks_total": int(tasks.get("total", 0)),
        "valid_answers": int(answers.get("valid_answers", 0)),
        "brand_mention_rate": answers.get("brand_mention_rate"),
        "general_brand_mention_rate": general.get("brand_mention_rate"),
        "brand_brand_mention_rate": brand.get("brand_mention_rate"),
        "brand_identified_rate": answers.get("brand_identified_rate"),
        "citation_rate": answers.get("citation_rate"),
        "citation_observable_answers": answers.get("citation_observable_answers"),
        "citation_unobservable_answers": answers.get("citation_unobservable_answers"),
        "published_receipts": int(row.report.get("published_receipts", 0)),
    }


def monthly_snapshot_payload(
    row: MonthlyReportSnapshot,
    *,
    captured_by_name: str | None = None,
) -> dict[str, Any]:
    payload = monthly_summary_payload(row, captured_by_name=captured_by_name)
    payload["definitions"] = row.definitions
    payload["report"] = row.report
    return payload
