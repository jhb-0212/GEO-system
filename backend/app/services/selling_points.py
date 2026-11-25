"""卖点清单与内容核对：只做确定性提示，不替代人工判断卖点是否正确。"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContentItem, ContentVersion, SellingPoint
from app.models.enums import ContentKind, ContentStatus

# 草稿不进入对外内容覆盖率；与内容一致性扫描保持同一批状态
SCAN_STATUSES = (
    ContentStatus.PENDING_REVIEW,
    ContentStatus.APPROVED,
    ContentStatus.SCHEDULED,
    ContentStatus.PENDING_PUBLISH,
    ContentStatus.PUBLISHED,
    ContentStatus.NEEDS_ATTENTION,
)
STATUS_LABELS = {
    "covered": "已说清",
    "mentioned": "提到但未说清",
    "missing": "未提到",
}
PUNCTUATION = re.compile(r"[\s，。；：、！？,.;:!?（）()【】\[\]“”\"'·—\-]+")


def _compact(value: str | None) -> str:
    return PUNCTUATION.sub("", (value or "").lower())


def list_selling_points(db: Session, project_id: uuid.UUID, *, include_inactive: bool = False) -> list[SellingPoint]:
    stmt = select(SellingPoint).where(SellingPoint.project_id == project_id)
    if not include_inactive:
        stmt = stmt.where(SellingPoint.is_active.is_(True))
    return list(db.scalars(stmt.order_by(SellingPoint.required.desc(), SellingPoint.created_at, SellingPoint.label)))


def _check_one(point: SellingPoint, body: str) -> dict:
    compact_body = _compact(body)
    value = _compact(point.value_text)
    aliases = [_compact(item) for item in (point.aliases or []) if _compact(item)]
    if value and value in compact_body:
        status = "covered"
    elif any(alias in compact_body for alias in aliases):
        status = "covered" if not value else "mentioned"
    else:
        status = "missing"
    return {
        "id": str(point.id),
        "label": point.label,
        "value_text": point.value_text,
        "required": point.required,
        "status": status,
        "status_label": STATUS_LABELS[status],
    }


def selling_point_check(db: Session, project_id: uuid.UUID, body: str) -> dict:
    rows = [_check_one(point, body) for point in list_selling_points(db, project_id)]
    if not rows:
        return {
            "status": "no_points",
            "status_label": "未配置卖点",
            "points_total": 0,
            "covered": 0,
            "mentioned": 0,
            "missing": 0,
            "required_total": 0,
            "required_covered": 0,
            "required_coverage": None,
            "points": [],
            "notes": ["还没有卖点清单；先维护卖点后，内容评分才会逐条核对。"],
        }
    covered = sum(1 for row in rows if row["status"] == "covered")
    mentioned = sum(1 for row in rows if row["status"] == "mentioned")
    missing = sum(1 for row in rows if row["status"] == "missing")
    required = [row for row in rows if row["required"]]
    required_covered = sum(1 for row in required if row["status"] == "covered")
    if missing and covered:
        status = "partial"
        label = "部分说清"
    elif missing and mentioned:
        status = "partial"
        label = "部分说清"
    elif covered == len(rows):
        status = "ok"
        label = "全部说清"
    elif mentioned or covered:
        status = "partial"
        label = "部分说清"
    else:
        status = "missing"
        label = "未回应卖点"
    return {
        "status": status,
        "status_label": label,
        "points_total": len(rows),
        "covered": covered,
        "mentioned": mentioned,
        "missing": missing,
        "required_total": len(required),
        "required_covered": required_covered,
        "required_coverage": round(required_covered / len(required), 4) if required else None,
        "points": rows,
        "notes": ["只检查正文是否出现卖点关键词或具体口径；不判断卖点是否真实、是否合规。"],
    }


def selling_point_summary(db: Session, project_id: uuid.UUID) -> dict:
    """项目级：每个卖点在当前版本中的覆盖情况。"""
    points = list_selling_points(db, project_id)
    rows = db.execute(
        select(ContentItem.current_version_id)
        .join(ContentVersion, ContentVersion.id == ContentItem.current_version_id)
        .where(
            ContentItem.project_id == project_id,
            ContentItem.kind == ContentKind.MASTER,
            ContentItem.current_version_id.is_not(None),
            ContentVersion.status.in_(SCAN_STATUSES),
        )
    ).all()
    version_ids = [row[0] for row in rows]
    contents = list(db.scalars(select(ContentVersion).where(ContentVersion.id.in_(version_ids)))) if version_ids else []
    summary_rows = []
    for point in points:
        covered = mentioned = missing = 0
        for version in contents:
            status = _check_one(point, version.body)["status"]
            if status == "covered":
                covered += 1
            elif status == "mentioned":
                mentioned += 1
            else:
                missing += 1
        total = len(contents)
        summary_rows.append({
            "id": str(point.id),
            "label": point.label,
            "value_text": point.value_text,
            "required": point.required,
            "is_active": point.is_active,
            "content_total": total,
            "covered": covered,
            "mentioned": mentioned,
            "missing": missing,
            "coverage": round(covered / total, 4) if total else None,
        })
    required_rows = [row for row in summary_rows if row["required"]]
    required_coverage = (
        round(sum(row["covered"] for row in required_rows) / (len(required_rows) * len(contents)), 4)
        if required_rows and contents else None
    )
    return {
        "summary": {
            "points_total": len(summary_rows),
            "contents_total": len(contents),
            "required_points": len(required_rows),
            "required_coverage": required_coverage,
        },
        "points": summary_rows,
        "notes": [
            "只统计有当前版本且处于审核中/已批准/待发布/已发布等状态母稿，草稿不纳入。",
            "覆盖率 = 该卖点被说清的内容数 / 当前母稿数；提到但未给出具体口径不算说清。",
        ],
    }
