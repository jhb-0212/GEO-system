"""G1/G2 生成批次服务。

候选来源只有两类，且都必须带证据：

- `opportunity`：机会中心里未关闭的缺口（竞品被引用、自己没被引用）。
  批次项会记住 `opportunity_id`，导出与审稿页都能回溯到原始样本与引用；
- `question`：被监测过、但在窗口内一次都没提及品牌的问题。
  这条走 samples → question_versions → question 的链路，不看「有没有人填过正文」。

出稿是**确定性模板合成**：把品牌档案、企业档案、已批准事实、已发布 FAQ、
当前被引用最多的域名拼成一篇文章骨架。同一份输入永远得到同一份草稿，
便于对比「人改了什么」。不调用任何付费模型；要调模型必须先把
`MODEL_GENERATION_ENABLED` 打开并单独评审，见 `_ensure_mode_supported`。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    BrandProfile,
    CompanyProfile,
    Fact,
    Faq,
    GenerationBatch,
    GenerationItem,
    MonitoringCitation,
    MonitoringSample,
    MonitoringTask,
    Opportunity,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    FactStatus,
    FaqStatus,
    GenerationBatchStatus,
    GenerationItemStatus,
    GenerationMode,
    GenerationSource,
    OpportunityStatus,
)

# 模型出稿开关：默认关。打开它意味着每篇稿子都会产生真实调用成本，
# 必须由运营显式决定，不能因为「接口支持」就默认开。
MODEL_GENERATION_ENABLED = False

WINDOW_DAYS = 90
MAX_ITEMS = 50


def _ensure_mode_supported(engine_code: str | None) -> None:
    if engine_code and not MODEL_GENERATION_ENABLED:
        raise AppError(
            "模型出稿当前未开启：本轮只支持模板合成。要接模型需先评审成本与合规，再打开开关",
            code="model_generation_disabled",
        )


def _top_sources(db: Session, project_id: uuid.UUID, limit: int = 5) -> list[dict]:
    rows = db.execute(
        select(MonitoringCitation.domain, func.count())
        .where(MonitoringCitation.project_id == project_id, MonitoringCitation.domain.is_not(None))
        .group_by(MonitoringCitation.domain)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    return [{"domain": domain, "citations": int(count)} for domain, count in rows]


def _facts(db: Session, project_id: uuid.UUID, limit: int = 5) -> list[dict]:
    rows = db.scalars(
        select(Fact)
        .where(Fact.project_id == project_id, Fact.approval_status == FactStatus.APPROVED)
        .order_by(Fact.updated_at.desc())
        .limit(limit)
    ).all()
    return [{"key": fact.fact_key, "value": fact.fact_value} for fact in rows]


def _faqs(db: Session, project_id: uuid.UUID, limit: int = 5) -> list[dict]:
    rows = db.scalars(
        select(Faq)
        .where(
            Faq.project_id == project_id,
            Faq.status == FaqStatus.PUBLISHED,
            Faq.deleted_at.is_(None),
        )
        .order_by(Faq.sort_order)
        .limit(limit)
    ).all()
    return [{"question": faq.question, "answer": faq.answer} for faq in rows]


def _opportunity_candidates(db: Session, project_id: uuid.UUID, limit: int) -> list[dict]:
    rows = db.scalars(
        select(Opportunity)
        .where(
            Opportunity.project_id == project_id,
            Opportunity.status.in_((OpportunityStatus.OPEN, OpportunityStatus.IN_PROGRESS)),
        )
        .order_by(Opportunity.priority_score.desc())
        .limit(limit)
    ).all()
    return [
        {
            "opportunity_id": row.id,
            "question_id": row.question_id,
            "title": row.title,
            "gap_type": row.gap_type.value,
            "evidence_refs": row.evidence_refs,
            "priority_score": float(row.priority_score),
        }
        for row in rows
    ]


def _question_candidates(db: Session, project_id: uuid.UUID, limit: int) -> list[dict]:
    since = datetime.now(UTC) - timedelta(days=WINDOW_DAYS)
    total_expr = func.count(MonitoringSample.id)
    mentioned_expr = func.count(MonitoringSample.id).filter(
        MonitoringSample.brand_mentioned.is_(True)
    )
    rows = db.execute(
        select(Question, total_expr, mentioned_expr)
        .join(QuestionVersion, QuestionVersion.question_id == Question.id)
        .join(MonitoringTask, MonitoringTask.question_version_id == QuestionVersion.id)
        .join(MonitoringSample, MonitoringSample.task_id == MonitoringTask.id)
        .where(
            Question.project_id == project_id,
            MonitoringSample.project_id == project_id,
            MonitoringSample.sampled_at >= since,
        )
        .group_by(Question.id)
        .order_by(total_expr.desc())
    ).all()
    # 只挑「测过但一次都没被提及」的：这类问题才有补内容的必要；
    # 已被提及的问题再写一篇属于锦上添花，不该占用批次名额。
    picked = [
        {"question_id": question.id, "title": question.title, "samples": int(total), "mentions": int(mentioned)}
        for question, total, mentioned in rows
        if int(total) > 0 and int(mentioned) == 0
    ]
    return picked[:limit]


def candidates(db: Session, project_id: uuid.UUID, source: str, limit: int) -> list[dict]:
    if source == GenerationSource.OPPORTUNITY:
        return _opportunity_candidates(db, project_id, limit)
    return _question_candidates(db, project_id, limit)


def _build_brief(db: Session, project_id: uuid.UUID, candidate: dict, source: str) -> dict:
    brand = db.scalar(
        select(BrandProfile).where(
            BrandProfile.project_id == project_id, BrandProfile.is_active.is_(True)
        )
    )
    profile = db.scalar(
        select(CompanyProfile).where(
            CompanyProfile.project_id == project_id, CompanyProfile.is_active.is_(True)
        )
    )
    return {
        "source": source,
        "question": candidate.get("title"),
        "gap_type": candidate.get("gap_type"),
        "opportunity_id": str(candidate["opportunity_id"]) if candidate.get("opportunity_id") else None,
        "question_id": str(candidate["question_id"]) if candidate.get("question_id") else None,
        "samples": candidate.get("samples"),
        "mentions": candidate.get("mentions"),
        "evidence_refs": candidate.get("evidence_refs") or [],
        "brand": brand.canonical_name if brand else None,
        "official_urls": (profile.official_urls if profile else None) or [],
        "facts": _facts(db, project_id),
        "faqs": _faqs(db, project_id),
        "sources": _top_sources(db, project_id),
        # 写作指引给的是结构，不给结论：结论必须由审稿人写，机器不替品牌表态
        "guidance": (
            "首段直接回答问题并给出可核验的一句话结论；"
            "正文只使用已批准事实与已发布 FAQ，不新增数字与承诺；"
            "结尾列出可被引用的来源，优先本批列出的高引用域名。"
        ),
    }


def create_batch(
    db: Session,
    project_id: uuid.UUID,
    *,
    name: str,
    source: str,
    limit: int = 10,
    engine_code: str | None = None,
    note: str | None = None,
    created_by: uuid.UUID | None = None,
) -> dict:
    _ensure_mode_supported(engine_code)
    if source not in (GenerationSource.OPPORTUNITY, GenerationSource.QUESTION):
        raise AppError("批次来源只能是机会缺口或未提及问题", code="generation_source_invalid")
    if not 1 <= limit <= MAX_ITEMS:
        raise AppError(f"单批最多 {MAX_ITEMS} 条", code="generation_limit_invalid")

    picked = candidates(db, project_id, source, limit)
    if not picked:
        raise AppError(
            "没有可生成的候选：先攒机会缺口或跑一轮监测", code="no_generation_candidates"
        )

    batch = GenerationBatch(
        project_id=project_id,
        name=name,
        source=source,
        engine_code=engine_code,
        total_items=len(picked),
        note=note,
        created_by=created_by,
    )
    db.add(batch)
    db.flush()
    for index, candidate in enumerate(picked):
        db.add(
            GenerationItem(
                project_id=project_id,
                batch_id=batch.id,
                question_id=candidate.get("question_id"),
                opportunity_id=candidate.get("opportunity_id"),
                title=candidate["title"],
                brief=_build_brief(db, project_id, candidate, source),
                sort_order=index,
            )
        )
    db.commit()
    return batch_snapshot(db, batch)


def _draft(brief: dict, title: str) -> str:
    brand = brief.get("brand") or "本品牌"
    urls = brief.get("official_urls") or []
    facts = brief.get("facts") or []
    faqs = brief.get("faqs") or []
    sources = brief.get("sources") or []

    lines = [f"# {title}", "", f"> 生成方式：模板合成（未调用模型）｜品牌：{brand}", ""]
    lines += ["## 一句话回答", ""]
    if urls:
        lines += [f"{brand} 的官方信息以 {urls[0]} 为准，下面逐项列出可核验内容。", ""]
    else:
        lines += [f"{brand} 的对外信息仍在整理，以下内容待补齐官网地址后发布。", ""]

    if facts:
        lines += ["## 可核验事实", ""]
        lines += [f"- {fact['value']}（来源字段：{fact['key']}）" for fact in facts]
        lines.append("")
    else:
        lines += ["## 可核验事实", "", "- （暂无已批准事实，发布前须补）", ""]

    if faqs:
        lines += ["## 常见问题", ""]
        for faq in faqs:
            lines += [f"**{faq['question']}**", "", faq["answer"], ""]

    if sources:
        lines += ["## 可被引用的来源线索", ""]
        lines += [f"- {item['domain']}（已被引用 {item['citations']} 次）" for item in sources]
        lines.append("")

    lines += ["> 审稿提示：" + str(brief.get("guidance") or ""), ""]
    return "\n".join(lines)


def run_batch(db: Session, project_id: uuid.UUID, batch_id: uuid.UUID) -> dict:
    batch = db.scalar(
        select(GenerationBatch).where(
            GenerationBatch.project_id == project_id, GenerationBatch.id == batch_id
        )
    )
    if batch is None:
        raise AppError("批次不存在或不属于当前项目", code="generation_batch_not_found")
    if batch.engine_code:
        _ensure_mode_supported(batch.engine_code)

    batch.status = GenerationBatchStatus.RUNNING
    db.flush()
    pending = db.scalars(
        select(GenerationItem)
        .where(
            GenerationItem.batch_id == batch.id,
            GenerationItem.status == GenerationItemStatus.PENDING,
        )
        .order_by(GenerationItem.sort_order)
    ).all()
    drafted = failed = 0
    for item in pending:
        try:
            item.draft_body = _draft(item.brief or {}, item.title)
            item.generation_mode = GenerationMode.TEMPLATE
            item.status = GenerationItemStatus.DRAFTED
            drafted += 1
        except Exception as exc:  # noqa: BLE001 - 单条失败不能拖垮整批，原因要留痕
            item.status = GenerationItemStatus.FAILED
            item.failure_reason = str(exc)[:500]
            failed += 1

    batch.drafted_items = batch.drafted_items + drafted
    batch.failed_items = batch.failed_items + failed
    batch.status = GenerationBatchStatus.COMPLETED
    db.commit()
    return batch_snapshot(db, batch)


def review_item(
    db: Session, project_id: uuid.UUID, batch_id: uuid.UUID, item_id: uuid.UUID, *, reviewed: bool
) -> dict:
    item = db.scalar(
        select(GenerationItem).where(
            GenerationItem.project_id == project_id,
            GenerationItem.batch_id == batch_id,
            GenerationItem.id == item_id,
        )
    )
    if item is None:
        raise AppError("生成项不存在或不属于当前批次", code="generation_item_not_found")
    item.reviewed = reviewed
    db.commit()
    return item


def batch_snapshot(db: Session, batch: GenerationBatch) -> dict:
    items = db.scalars(
        select(GenerationItem)
        .where(GenerationItem.batch_id == batch.id)
        .order_by(GenerationItem.sort_order)
    ).all()
    return {
        "batch_id": batch.id,
        "name": batch.name,
        "source": batch.source,
        "status": batch.status.value,
        "engine_code": batch.engine_code,
        "note": batch.note,
        "created_at": batch.created_at,
        "totals": {
            "total": batch.total_items,
            "drafted": batch.drafted_items,
            "failed": batch.failed_items,
            "pending": sum(1 for item in items if item.status == GenerationItemStatus.PENDING),
            "reviewed": sum(1 for item in items if item.reviewed),
        },
        "items": [
            {
                "item_id": item.id,
                "title": item.title,
                "status": item.status.value,
                "generation_mode": item.generation_mode.value,
                "question_id": item.question_id,
                "opportunity_id": item.opportunity_id,
                "brief": item.brief,
                "draft_body": item.draft_body,
                "failure_reason": item.failure_reason,
                "reviewed": item.reviewed,
            }
            for item in items
        ],
        "disclaimer": "批次只产出草稿并进审稿队列，不会自动发布；模型出稿默认关闭。",
    }


def list_batches(db: Session, project_id: uuid.UUID, *, limit: int = 20) -> list[dict]:
    batches = db.scalars(
        select(GenerationBatch)
        .where(GenerationBatch.project_id == project_id)
        .order_by(GenerationBatch.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "batch_id": batch.id,
            "name": batch.name,
            "source": batch.source,
            "status": batch.status.value,
            "engine_code": batch.engine_code,
            "created_at": batch.created_at,
            "totals": {
                "total": batch.total_items,
                "drafted": batch.drafted_items,
                "failed": batch.failed_items,
            },
        }
        for batch in batches
    ]


def export_rows(db: Session, batch: GenerationBatch) -> list[dict]:
    items = db.scalars(
        select(GenerationItem)
        .where(GenerationItem.batch_id == batch.id)
        .order_by(GenerationItem.sort_order)
    ).all()
    return [
        {
            "批次": batch.name,
            "标题": item.title,
            "状态": item.status.value,
            "来源": (item.brief or {}).get("source"),
            "缺口类型": (item.brief or {}).get("gap_type") or "",
            "问题": (item.brief or {}).get("question") or "",
            "已审": "是" if item.reviewed else "否",
            "正文": item.draft_body or "",
        }
        for item in items
    ]
