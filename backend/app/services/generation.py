"""G1/G2 生成批次服务。

候选来源只有三类，且都必须带证据：

- `opportunity`：机会中心里未关闭的缺口（竞品被引用、自己没被引用）。
  批次项会记住 `opportunity_id`，导出与审稿页都能回溯到原始样本与引用；
- `question`：被监测过、但在窗口内一次都没提及品牌的问题。
  这条走 samples → question_versions → question 的链路，不看「有没有人填过正文」；
- `remediation`：**人工**判为负面的一条引用 → 一篇纠正稿。
  系统不自动判定舆情，只有当人给某条引用打了 negative 标注，才允许拿它当证据建批。

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
from app.services.state_machine import ensure_generation_batch_transition, ensure_generation_item_transition
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
    SentimentLabel,
)
from app.models.enums import (
    CitationReviewStatus,
    FactStatus,
    FaqStatus,
    GenerationBatchStatus,
    GenerationItemStatus,
    GenerationMode,
    GenerationSource,
    OpportunityStatus,
    SentimentPolarity,
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


def _latest_negative_labels(db: Session, project_id: uuid.UUID) -> dict[uuid.UUID, SentimentLabel]:
    """每条引用取一条「最近」的负面标注（双人标注时，两个人都判负面才算数）。"""
    rows = db.scalars(
        select(SentimentLabel)
        .where(
            SentimentLabel.project_id == project_id,
            SentimentLabel.polarity == SentimentPolarity.NEGATIVE,
        )
        .order_by(SentimentLabel.labeled_at.desc())
    ).all()
    newest: dict[uuid.UUID, SentimentLabel] = {}
    for row in rows:
        newest.setdefault(row.citation_id, row)
    return newest


def _confirmed_citation(db: Session, project_id: uuid.UUID, citation_id: uuid.UUID) -> MonitoringCitation:
    citation = db.scalar(
        select(MonitoringCitation).where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.id == citation_id,
        )
    )
    if citation is None:
        raise AppError("引文不存在或不属于当前项目", code="citation_not_found")
    if citation.review_status != CitationReviewStatus.MANUAL_CONFIRMED:
        raise AppError("只能给人工复核通过的引用建纠正批次", code="citation_not_confirmed")
    return citation


def _remediation_candidates(db: Session, project_id: uuid.UUID, limit: int) -> list[dict]:
    newest = _latest_negative_labels(db, project_id)
    if not newest:
        return []
    citations = db.scalars(
        select(MonitoringCitation)
        .where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.id.in_(list(newest.keys())),
            MonitoringCitation.review_status == CitationReviewStatus.MANUAL_CONFIRMED,
        )
    ).all()
    picked: list[dict] = []
    for citation in sorted(
        citations,
        key=lambda row: newest[row.id].labeled_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    ):
        label = newest[citation.id]
        picked.append(
            {
                "citation_id": citation.id,
                "title": (f"纠正：{citation.title}" if citation.title else f"纠正 {citation.domain or '外部引用'} 上的负面说法")[:255],
                "gap_type": "negative_citation",
                "evidence_refs": [
                    {
                        "type": "monitoring_citation",
                        "id": str(citation.id),
                        "domain": citation.domain,
                        "url": citation.normalized_url or citation.raw_url,
                        "site_name": citation.site_name,
                        "label_note": label.note,
                        "labeled_at": label.labeled_at.isoformat() if label.labeled_at else None,
                    }
                ],
                "negative_domain": citation.domain,
                "negative_quote": citation.snippet,
                "label_note": label.note,
            }
        )
        if len(picked) >= limit:
            break
    return picked


def candidates(db: Session, project_id: uuid.UUID, source: str, limit: int) -> list[dict]:
    if source == GenerationSource.OPPORTUNITY:
        return _opportunity_candidates(db, project_id, limit)
    if source == GenerationSource.REMEDIATION:
        return _remediation_candidates(db, project_id, limit)
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
    guidance = (
        "首段直接回答问题并给出可核验的一句话结论；"
        "正文只使用已批准事实与已发布 FAQ，不新增数字与承诺；"
        "结尾列出可被引用的来源，优先本批列出的高引用域名。"
    )
    if source == GenerationSource.REMEDIATION:
        # 纠正稿的写法与常规稿不同：只补事实、不复述负面原文，避免二次传播
        guidance = (
            "只做事实补充与澄清：先给可核验的官方结论，再逐条对应已批准事实；"
            "不在正文复述、引用或放大负面原文（原文只留在证据条目里供审稿人查看）；"
            "不评价同行、不使用比较级形容词、不承诺无法证明的效果；"
            "结尾列出官方来源，供读者自行核验。"
        )
    return {
        "source": source,
        "question": candidate.get("title"),
        "gap_type": candidate.get("gap_type"),
        "opportunity_id": str(candidate["opportunity_id"]) if candidate.get("opportunity_id") else None,
        "question_id": str(candidate["question_id"]) if candidate.get("question_id") else None,
        "citation_id": str(candidate["citation_id"]) if candidate.get("citation_id") else None,
        "negative_domain": candidate.get("negative_domain"),
        "label_note": candidate.get("label_note"),
        "samples": candidate.get("samples"),
        "mentions": candidate.get("mentions"),
        "evidence_refs": candidate.get("evidence_refs") or [],
        "brand": brand.canonical_name if brand else None,
        "official_urls": (profile.official_urls if profile else None) or [],
        "facts": _facts(db, project_id),
        "faqs": _faqs(db, project_id),
        "sources": _top_sources(db, project_id),
        # 写作指引给的是结构，不给结论：结论必须由审稿人写，机器不替品牌表态
        "guidance": guidance,
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
    if source == GenerationSource.REMEDIATION:
        # 纠正稿必须挂在一条具体引用上，走 create_remediation_batch，不接受批量挑选
        raise AppError(
            "纠正批次请走情绪原文页的「生成纠正稿」入口", code="generation_source_invalid"
        )
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


def create_remediation_batch(
    db: Session,
    project_id: uuid.UUID,
    citation_id: uuid.UUID,
    *,
    name: str | None = None,
    note: str | None = None,
    created_by: uuid.UUID | None = None,
) -> dict:
    """一条「人工判为负面」的引用 → 一个单条纠正批次。

    幂等口径：同一引用若已有纠正批次，直接返回那一条（`reused=True`），
    不重复建批；重复建批会让审稿队列里堆出同一件事的多份草稿。
    """
    citation = _confirmed_citation(db, project_id, citation_id)
    label = _latest_negative_labels(db, project_id).get(citation_id)
    if label is None:
        raise AppError(
            "这条引用还没有「负面」的人工标注，不能建纠正批次", code="citation_not_negative"
        )

    # 幂等：同一引用已有纠正批次就复用。用 Python 侧比对 brief，避免依赖 JSON 索引的方言差异
    existing = None
    for batch in db.scalars(
        select(GenerationBatch)
        .where(
            GenerationBatch.project_id == project_id,
            GenerationBatch.source == GenerationSource.REMEDIATION,
        )
        .order_by(GenerationBatch.created_at.desc())
    ).all():
        for item in db.scalars(
            select(GenerationItem).where(GenerationItem.batch_id == batch.id)
        ).all():
            if (item.brief or {}).get("citation_id") == str(citation_id):
                existing = batch
                break
        if existing is not None:
            break
    if existing is not None:
        snapshot = batch_snapshot(db, existing)
        snapshot["reused"] = True
        return snapshot

    candidate = {
        "citation_id": citation.id,
        "title": (f"纠正：{citation.title}" if citation.title else f"纠正 {citation.domain or '外部引用'} 上的负面说法")[:255],
        "gap_type": "negative_citation",
        "evidence_refs": [
            {
                "type": "monitoring_citation",
                "id": str(citation.id),
                "domain": citation.domain,
                "url": citation.normalized_url or citation.raw_url,
                "site_name": citation.site_name,
                "label_note": label.note,
                "labeled_at": label.labeled_at.isoformat() if label.labeled_at else None,
            }
        ],
        "negative_domain": citation.domain,
        "negative_quote": citation.snippet,
        "label_note": label.note,
    }
    batch = GenerationBatch(
        project_id=project_id,
        name=(name or candidate["title"])[:120],
        source=GenerationSource.REMEDIATION,
        total_items=1,
        note=note,
        created_by=created_by,
    )
    db.add(batch)
    db.flush()
    db.add(
        GenerationItem(
            project_id=project_id,
            batch_id=batch.id,
            title=candidate["title"],
            brief=_build_brief(db, project_id, candidate, GenerationSource.REMEDIATION),
            sort_order=0,
        )
    )
    db.commit()
    snapshot = batch_snapshot(db, batch)
    snapshot["reused"] = False
    return snapshot


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

    if brief.get("negative_domain"):
        # 刻意不写入原文：草稿会流出到审稿、导出、发布各环节，复述即二次传播
        lines += [
            "## 待澄清的说法",
            "",
            f"- 证据：{brief['negative_domain']} 上有一条人工判定为负面的说法（原文见证据条目，此处不复述）。",
            "- 澄清方式：只补可核验事实与官方口径，不逐句反驳、不引用对方表述。",
            "",
        ]

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


def run_batch(
    db: Session, project_id: uuid.UUID, batch_id: uuid.UUID, *, enforce_gate: bool = True
) -> dict:
    batch = db.scalar(
        select(GenerationBatch).where(
            GenerationBatch.project_id == project_id, GenerationBatch.id == batch_id
        )
    )
    if batch is None:
        raise AppError("批次不存在或不属于当前项目", code="generation_batch_not_found")
    if batch.engine_code:
        _ensure_mode_supported(batch.engine_code)
    if enforce_gate:
        # 局部导入：generation_gate 依赖本模块的出稿函数，顶层互引会成环
        from app.services.generation_gate import ensure_gate_satisfied

        ensure_gate_satisfied(db, batch)

    batch.status = ensure_generation_batch_transition(
        batch.status, GenerationBatchStatus.RUNNING
    )
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
            item.status = ensure_generation_item_transition(
                item.status, GenerationItemStatus.DRAFTED
            )
            drafted += 1
        except Exception as exc:  # noqa: BLE001 - 单条失败不能拖垮整批，原因要留痕
            item.status = ensure_generation_item_transition(
                item.status, GenerationItemStatus.FAILED
            )
            item.failure_reason = str(exc)[:500]
            failed += 1

    batch.drafted_items = batch.drafted_items + drafted
    batch.failed_items = batch.failed_items + failed
    batch.status = ensure_generation_batch_transition(
        batch.status, GenerationBatchStatus.COMPLETED
    )
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
