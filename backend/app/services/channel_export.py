"""渠道导出：按引用联表聚合的「渠道 + 覆盖情况」与 CSV 序列化。

口径：一个渠道一行，`citation_count` 是引用条数，`page_count` 按
`normalized_url` 去重，引擎/题目集合去重后排序，首末采样时间取极值。
"""

import csv
import io
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
    MonitoringCitation,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import CitationReviewStatus
from app.services.csv_safety import safe_csv_row

FILTERED_CSV_COLUMNS = (
    "code",
    "name",
    "category",
    "status",
    "primary_domain",
    "owner_name",
    "owner_contact",
    "citation_count",
    "sample_count",
    "page_count",
    "engine_codes",
    "engine_names",
    "question_codes",
    "first_sampled_at",
    "last_sampled_at",
)


def filtered_statement(
    project_id: uuid.UUID,
    *,
    engine_id: uuid.UUID | None,
    question_id: uuid.UUID | None,
    start_at: datetime | None,
    end_at: datetime | None,
    review_status: CitationReviewStatus | None = None,
):
    """筛选导出的联表语句；复用给「先计数、再取数」的上限校验。"""
    stmt = (
        select(
            Channel,
            MonitoringCitation.id,
            MonitoringCitation.sample_id,
            MonitoringCitation.normalized_url,
            MonitoringSample.sampled_at,
            AiEngine.code,
            AiEngine.name,
            Question.code,
        )
        .select_from(Channel)
        .join(MonitoringCitation, MonitoringCitation.channel_id == Channel.id)
        .join(MonitoringSample, MonitoringCitation.sample_id == MonitoringSample.id)
        .join(MonitoringTask, MonitoringSample.task_id == MonitoringTask.id)
        .join(QuestionVersion, MonitoringTask.question_version_id == QuestionVersion.id)
        .join(Question, QuestionVersion.question_id == Question.id)
        .join(AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .join(AiEngine, AiEngineEntry.engine_id == AiEngine.id)
        .where(
            Channel.project_id == project_id,
            MonitoringCitation.project_id == project_id,
            MonitoringSample.project_id == project_id,
            MonitoringTask.project_id == project_id,
            Question.project_id == project_id,
        )
        .order_by(Channel.code, MonitoringSample.sampled_at)
    )
    if engine_id is not None:
        stmt = stmt.where(AiEngineEntry.engine_id == engine_id)
    if question_id is not None:
        stmt = stmt.where(Question.id == question_id)
    if start_at is not None:
        stmt = stmt.where(MonitoringSample.sampled_at >= start_at)
    if end_at is not None:
        # 左闭右开：end_at 为下一周期起点的 UTC 时刻，不包含端点。
        stmt = stmt.where(MonitoringSample.sampled_at < end_at)
    if review_status is not None:
        stmt = stmt.where(MonitoringCitation.review_status == review_status)
    return stmt


def filtered_rows(db: Session, statement) -> list[dict]:
    """按引用联表聚合渠道，一个 channel_id 一行；同渠道多次引用不重复出行。"""
    grouped: dict[uuid.UUID, dict] = {}
    for (
        channel,
        _citation_id,
        sample_id,
        normalized_url,
        sampled_at,
        engine_code,
        engine_name,
        question_code,
    ) in db.execute(statement).all():
        item = grouped.setdefault(
            channel.id,
            {
                "channel": channel,
                "citation_count": 0,
                "sample_ids": set(),
                "page_urls": set(),
                "engine_codes": set(),
                "engine_names": set(),
                "question_codes": set(),
                "first_sampled_at": None,
                "last_sampled_at": None,
            },
        )
        item["citation_count"] += 1
        item["sample_ids"].add(sample_id)
        if normalized_url:
            item["page_urls"].add(normalized_url)
        item["engine_codes"].add(engine_code)
        item["engine_names"].add(engine_name)
        item["question_codes"].add(question_code)
        if sampled_at is not None:
            if item["first_sampled_at"] is None or sampled_at < item["first_sampled_at"]:
                item["first_sampled_at"] = sampled_at
            if item["last_sampled_at"] is None or sampled_at > item["last_sampled_at"]:
                item["last_sampled_at"] = sampled_at

    rows = []
    for item in grouped.values():
        channel = item["channel"]
        rows.append(
            {
                "code": channel.code,
                "name": channel.name,
                "category": channel.category,
                "status": channel.status,
                "primary_domain": channel.primary_domain or "",
                "owner_name": channel.owner_name or "",
                "owner_contact": channel.owner_contact or "",
                "citation_count": item["citation_count"],
                "sample_count": len(item["sample_ids"]),
                "page_count": len(item["page_urls"]),
                "engine_codes": "|".join(sorted(item["engine_codes"])),
                "engine_names": "|".join(sorted(item["engine_names"])),
                "question_codes": "|".join(sorted(item["question_codes"])),
                "first_sampled_at": (
                    item["first_sampled_at"].isoformat() if item["first_sampled_at"] else ""
                ),
                "last_sampled_at": (
                    item["last_sampled_at"].isoformat() if item["last_sampled_at"] else ""
                ),
            }
        )
    return rows


def filtered_csv(rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(FILTERED_CSV_COLUMNS)
    for row in rows:
        writer.writerow(safe_csv_row([row[column] for column in FILTERED_CSV_COLUMNS]))
    return buffer.getvalue()
