"""分发侧洞察：渠道 × 引擎的实测矩阵，以及「这条内容该发哪」的候选排序。

口径红线：
- **不合成总分**。排序只用一个明示的比较器（先比被复核引用条数，再比成功回执数），
  每行把两个事实并排给出，让人自己判断；
- 引擎是「期望/观察」，投喂目标永远是渠道；
- 没有实测数据的渠道只列出「0 引用」，不给推荐理由，不靠类别相似度外推。
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AiEngine,
    AiEngineEntry,
    Channel,
    MonitoringCitation,
    MonitoringSample,
    MonitoringTask,
    PublishReceipt,
    PublishTask,
)
from app.models.enums import (
    ChannelApprovalStatus,
    CitationReviewStatus,
    PublishTaskStatus,
)
from app.models.engine_target import EngineTarget


def _engine_of_sample(db: Session, project_id: uuid.UUID) -> dict[uuid.UUID, uuid.UUID]:
    """sample_id → engine_id。任务里记的是入口，入口再挂引擎。"""
    entries = {
        row.id: row.engine_id
        for row in db.scalars(select(AiEngineEntry))
    }
    samples: dict[uuid.UUID, uuid.UUID] = {}
    for sample in db.scalars(
        select(MonitoringSample).where(MonitoringSample.project_id == project_id)
    ):
        task = db.get(MonitoringTask, sample.task_id)
        if task and task.engine_entry_id in entries:
            samples[sample.id] = entries[task.engine_entry_id]
    return samples


def engine_target_matrix(db: Session, project_id: uuid.UUID, *, limit: int = 40) -> dict:
    engines = {row.id: row for row in db.scalars(select(AiEngine))}
    channels = {row.id: row for row in db.scalars(select(Channel).where(Channel.project_id == project_id))}
    sample_engine = _engine_of_sample(db, project_id)

    counts: dict[tuple[uuid.UUID, uuid.UUID], int] = defaultdict(int)
    channel_totals: dict[uuid.UUID, int] = defaultdict(int)
    for row in db.scalars(
        select(MonitoringCitation).where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.review_status == CitationReviewStatus.MANUAL_CONFIRMED,
        )
    ):
        if not row.channel_id or row.sample_id not in sample_engine:
            continue
        counts[(row.channel_id, sample_engine[row.sample_id])] += 1
        channel_totals[row.channel_id] += 1

    confirmed = {
        (row.channel_id, row.engine_id): row
        for row in db.scalars(select(EngineTarget).where(EngineTarget.project_id == project_id))
    }

    rows: list[dict] = []
    for (channel_id, engine_id), cited in counts.items():
        channel = channels.get(channel_id)
        engine = engines.get(engine_id)
        target = confirmed.get((channel_id, engine_id))
        rows.append(
            {
                "channel_id": str(channel_id),
                "channel": channel.name if channel else None,
                "channel_status": channel.status.value if channel and channel.status else None,
                "engine_code": engine.code if engine else None,
                "engine_name": engine.name if engine else None,
                "cited": cited,
                "share_of_channel": round(cited / channel_totals[channel_id], 4) if channel_totals[channel_id] else None,
                "confirmed_priority": target.priority if target else None,
                "confirmed_note": target.note if target else None,
            }
        )
    rows.sort(key=lambda item: (item["channel"] or "", -item["cited"]))
    return {
        "rows": rows[:limit],
        "summary": {
            "channels_with_citations": len(channel_totals),
            "channel_engine_pairs": len(counts),
            "confirmed_pairs": len(confirmed),
        },
        "notes": [
            "cited = 该渠道内容在该引擎下被人工复核的引用条数，是唯一的排序事实。",
            "share_of_channel 只在该渠道内部算，不做跨渠道比较。",
            "confirmed_priority 是人工确认过的期望顺序；未确认留空，不自动推。",
        ],
    }


def confirm_engine_targets(
    db: Session,
    project_id: uuid.UUID,
    decisions: list[dict],
    *,
    actor_id: uuid.UUID | None = None,
    apply: bool = True,
) -> dict:
    """人工确认渠道 × 引擎的期望优先级；一引擎一条。"""
    channels = {str(row.code): row for row in db.scalars(select(Channel).where(Channel.project_id == project_id))}
    engines = {row.code: row for row in db.scalars(select(AiEngine))}
    existing = {
        (row.channel_id, row.engine_id): row
        for row in db.scalars(select(EngineTarget).where(EngineTarget.project_id == project_id))
    }

    applied: list[dict] = []
    for decision in decisions:
        channel = channels.get(decision.get("channel_code") or "")
        engine = engines.get(decision.get("engine_code") or "")
        if not channel or not engine:
            applied.append({"decision": decision, "status": "invalid", "detail": "渠道或引擎不存在"})
            continue
        priority = int(decision.get("priority") or 1)
        note = decision.get("note")
        if apply:
            row = existing.get((channel.id, engine.id))
            if row is None:
                row = EngineTarget(
                    project_id=project_id, channel_id=channel.id, engine_id=engine.id,
                    priority=priority, note=note, source="manual", created_by=actor_id,
                )
                db.add(row)
                existing[(channel.id, engine.id)] = row
            else:
                row.priority = priority
                row.note = note
                row.source = "manual"
        applied.append({"channel_code": channel.code, "engine_code": engine.code, "priority": priority, "status": "applied"})
    if apply:
        db.commit()
    return {"apply": apply, "decisions": applied, "changed": sum(1 for d in applied if d["status"] == "applied")}


def channel_candidates(db: Session, project_id: uuid.UUID, *, limit: int = 10) -> dict:
    """分发候选：按实测事实排序渠道，不做综合评分。"""
    channels = list(db.scalars(select(Channel).where(Channel.project_id == project_id)))
    sample_engine = _engine_of_sample(db, project_id)

    cited: dict[uuid.UUID, int] = defaultdict(int)
    engines_hit: dict[uuid.UUID, set[str]] = defaultdict(set)
    engines = {row.id: row.code for row in db.scalars(select(AiEngine))}
    for row in db.scalars(
        select(MonitoringCitation).where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.review_status == CitationReviewStatus.MANUAL_CONFIRMED,
        )
    ):
        if not row.channel_id:
            continue
        cited[row.channel_id] += 1
        engine_id = sample_engine.get(row.sample_id)
        if engine_id and engine_id in engines:
            engines_hit[row.channel_id].add(engines[engine_id])

    receipts: dict[uuid.UUID, int] = defaultdict(int)
    task_channel = {
        row.id: row.channel_id
        for row in db.scalars(select(PublishTask).where(PublishTask.project_id == project_id))
    }
    for receipt in db.scalars(select(PublishReceipt).where(PublishReceipt.project_id == project_id)):
        channel_id = task_channel.get(receipt.task_id)
        if channel_id:
            receipts[channel_id] += 1

    rows = [
        {
            "channel_id": str(channel.id),
            "channel": channel.name,
            "code": channel.code,
            "status": channel.status.value if channel.status else None,
            "approval_status": channel.approval_status.value if channel.approval_status else None,
            "cited": cited.get(channel.id, 0),
            "receipts": receipts.get(channel.id, 0),
            "engines": sorted(engines_hit.get(channel.id, set())),
        }
        for channel in channels
    ]
    # 排序器：先被引条数，再成功回执数，最后按渠道名稳定排序——单一维度可比，不是加权总分
    rows.sort(key=lambda item: (-item["cited"], -item["receipts"], item["channel"]))
    eligible = [row for row in rows if row["approval_status"] == ChannelApprovalStatus.APPROVED.value]
    return {
        "candidates": eligible[:limit],
        "others": [row for row in rows if row["approval_status"] != ChannelApprovalStatus.APPROVED.value][:limit],
        "summary": {
            "channels": len(rows),
            "approved": len(eligible),
            "with_citations": sum(1 for row in rows if row["cited"] > 0),
            "with_receipts": sum(1 for row in rows if row["receipts"] > 0),
        },
        "notes": [
            "排序器 = 被复核引用条数 → 成功回执数 → 渠道名，单一维度比较，没有加权总分。",
            "只列 approved 渠道进候选；pending_review 的渠道单独列出，不混进推荐。",
            "0 引用的渠道照样列出，不给推荐理由——没有实测就不外推。",
        ],
    }
