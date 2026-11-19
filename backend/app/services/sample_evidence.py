"""样本证据覆盖审计：每个样本是否至少有一个证据文件。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import EvidenceFile, MonitoringSample


def evidence_coverage(
    db: Session, project_id: uuid.UUID, *, missing_limit: int = 500
) -> dict:
    """返回项目样本证据覆盖；缺失样本最多列出 missing_limit 条。"""
    total = db.scalar(
        select(func.count()).select_from(MonitoringSample).where(
            MonitoringSample.project_id == project_id
        )
    ) or 0
    with_evidence = db.scalar(
        select(func.count(func.distinct(EvidenceFile.sample_id))).where(
            EvidenceFile.project_id == project_id
        )
    ) or 0
    missing_rows = db.scalars(
        select(MonitoringSample.id)
        .outerjoin(EvidenceFile, EvidenceFile.sample_id == MonitoringSample.id)
        .where(
            MonitoringSample.project_id == project_id,
            EvidenceFile.id.is_(None),
        )
        .order_by(MonitoringSample.created_at, MonitoringSample.id)
        .limit(missing_limit + 1)
    ).all()
    missing_truncated = len(missing_rows) > missing_limit
    missing_ids = [str(row) for row in missing_rows[:missing_limit]]
    return {
        "total_samples": total,
        "samples_with_evidence": with_evidence,
        "samples_missing_evidence": max(total - with_evidence, 0),
        "coverage_rate": round(with_evidence / total, 4) if total else None,
        "missing_sample_ids": missing_ids,
        "missing_truncated": missing_truncated,
    }
