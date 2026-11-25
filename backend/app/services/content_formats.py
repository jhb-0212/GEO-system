"""内容形式覆盖率：只统计生产侧标注，不替代引用页分类。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.content import ContentItem, ContentVersionCitation
from app.models.enums import ContentFormat, ContentKind


FORMAT_LABELS = {
    ContentFormat.DEFINITION: "定义",
    ContentFormat.TUTORIAL: "教程",
    ContentFormat.COMPARISON: "对比",
    ContentFormat.LISTICLE: "清单",
    ContentFormat.FAQ: "FAQ",
    ContentFormat.CASE_STUDY: "案例",
}


def content_format_report(db: Session, project_id: uuid.UUID) -> dict:
    """按母稿形式统计数量与“已关联引用证据”的覆盖率。

    覆盖率分子是当前母稿版本至少关联一条引用证据。它表示内容有可追溯来源，
    不代表 AI 答案实际引用了这条内容。
    """
    rows = db.execute(
        select(
            ContentItem.id,
            ContentItem.kind,
            ContentItem.content_type,
            ContentItem.current_version_id,
        ).where(ContentItem.project_id == project_id)
    ).all()
    version_ids = [row.current_version_id for row in rows if row.current_version_id]
    cited_versions: set[uuid.UUID] = set()
    if version_ids:
        cited_versions = {
            version_id
            for (version_id,) in db.execute(
                select(ContentVersionCitation.version_id)
                .where(
                    ContentVersionCitation.project_id == project_id,
                    ContentVersionCitation.version_id.in_(version_ids),
                )
                .group_by(ContentVersionCitation.version_id)
            ).all()
        }

    stats: dict[str, dict] = {}
    for fmt in ContentFormat:
        stats[fmt.value] = {
            "content_type": fmt.value,
            "label": FORMAT_LABELS[fmt],
            "master_items": 0,
            "channel_items": 0,
            "current_versions": 0,
            "citation_linked_items": 0,
            "citation_coverage": None,
        }
    unclassified = {
        "content_type": None,
        "label": "未标注",
        "master_items": 0,
        "channel_items": 0,
        "current_versions": 0,
        "citation_linked_items": 0,
        "citation_coverage": None,
    }

    for row in rows:
        target = stats.get(row.content_type.value) if row.content_type else unclassified
        if target is None:
            target = unclassified
        if row.kind == ContentKind.MASTER:
            target["master_items"] += 1
        elif row.kind == ContentKind.CHANNEL:
            target["channel_items"] += 1
        if row.kind == ContentKind.MASTER and row.current_version_id:
            target["current_versions"] += 1
            if row.current_version_id in cited_versions:
                target["citation_linked_items"] += 1

    for item in [*stats.values(), unclassified]:
        if item["current_versions"]:
            item["citation_coverage"] = round(
                item["citation_linked_items"] / item["current_versions"], 4
            )

    formats = list(stats.values())
    master_total = sum(item["master_items"] for item in formats) + unclassified["master_items"]
    master_with_format = sum(item["master_items"] for item in formats)
    current_total = sum(item["current_versions"] for item in formats) + unclassified["current_versions"]
    linked_total = sum(item["citation_linked_items"] for item in formats) + unclassified["citation_linked_items"]

    return {
        "summary": {
            "master_items": master_total,
            "master_with_format": master_with_format,
            "master_without_format": unclassified["master_items"],
            "channel_items": sum(item["channel_items"] for item in formats) + unclassified["channel_items"],
            "current_versions": current_total,
            "citation_linked_items": linked_total,
            "citation_coverage": round(linked_total / current_total, 4) if current_total else None,
        },
        "formats": [*formats, unclassified],
        "notes": [
            "内容形式在创建母稿时人工标注，历史内容未回填，未标注单独一行。",
            "渠道稿继承母稿形式，不单独计数。",
            "引用覆盖率指当前母稿版本已关联引用证据，不代表 AI 答案实际引用。",
        ],
    }
