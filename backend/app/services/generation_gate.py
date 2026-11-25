"""批次级生成闸门：先体检、再出小样、最后人工签核，签过才允许全量跑。

三条口径（改代码前先看）：

1. **闸门只管「要不要全量跑」，不管「稿子能不能发」**：通过闸门只代表这一批值得
   批量出稿，发布仍走内容审核 → 发布任务，两层不合并。
2. **小批次免闸门**：`total_items < GATE_MIN_ITEMS` 的批次直接跑。现实里没人愿意
   为 3 篇稿子先跑三道审批，闸门只拦「一开就是几十篇」的批量复制。
3. **小样是真出稿，不是抽样打分**：取样项会真的生成正文并落到 `drafted`，分数来自
   `score_content_geo` 的六项分项（各 100 分取平均），不合成总分、不预测收录。
   失败原因要写清（哪几项低、哪条事实缺），不能只留一个「不通过」。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.models import GenerationBatch, GenerationGateResult, GenerationItem, Project
from app.models.enums import (
    GateType,
    GenerationBatchStatus,
    GenerationItemStatus,
    GenerationMode,
)
from app.services.content_geo_score import _brand_terms, _company_context, score_content_geo
from app.services.generation import _draft, _ensure_mode_supported
from app.services.state_machine import ensure_generation_item_transition

# 达到这个规模的批次必须先过闸门；低于它的批次直接跑
GATE_MIN_ITEMS = 20
DEFAULT_SAMPLE_SIZE = 3
MAX_SAMPLE_SIZE = 10
# 六项分项各 100 分，均分低于 60 视为「这一批的写法还不值得全量复制」
DEFAULT_THRESHOLD = 60
# 只作提示计数，不作阻塞项：模板合成的正文天然短，用字数卡等于模板批次永远过不了闸门
SOFT_MIN_WORDS = 200


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _items(db: Session, batch: GenerationBatch) -> list[GenerationItem]:
    return list(
        db.scalars(
            select(GenerationItem)
            .where(GenerationItem.batch_id == batch.id)
            .order_by(GenerationItem.sort_order)
        )
    )


def _blocker(code: str, message: str, item_id: uuid.UUID | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if item_id is not None:
        payload["item_id"] = str(item_id)
    return payload


def gate_payload(row: GenerationGateResult) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "batch_id": str(row.batch_id),
        "gate_type": row.gate_type.value,
        "passed": row.passed,
        "score": row.score,
        "threshold": row.threshold,
        "sample_size": row.sample_size,
        "blockers": row.blockers,
        "metrics": row.metrics,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _require_gateable(batch: GenerationBatch) -> None:
    if batch.status != GenerationBatchStatus.QUEUED:
        raise ConflictError(
            "批次已经开跑或已结束，闸门只在待跑状态可用",
            code="generation_batch_not_gateable",
        )


def precheck(
    db: Session, *, project_id: uuid.UUID, batch: GenerationBatch, actor_id: uuid.UUID | None
) -> GenerationGateResult:
    """结构体检：只读，不改任何生成项。"""
    _require_gateable(batch)
    items = _items(db, batch)
    blockers: list[dict[str, Any]] = []

    if not items:
        blockers.append(_blocker("no_items", "批次没有任何生成项，跑起来也只会空转"))
    if batch.engine_code:
        try:
            _ensure_mode_supported(batch.engine_code)
        except Exception as exc:  # noqa: BLE001 - 模式不可用要作为阻塞项写进记录
            blockers.append(_blocker("engine_unsupported", f"指定引擎不可用：{exc}"))

    with_facts = with_brand = 0
    for item in items:
        brief = item.brief or {}
        if not (item.title or "").strip():
            blockers.append(_blocker("item_title_missing", "生成项没有标题", item.id))
        if not brief:
            blockers.append(_blocker("item_brief_missing", "生成项没有写作简报，出稿会变成空话", item.id))
            continue
        if brief.get("facts"):
            with_facts += 1
        if (brief.get("brand") or "").strip():
            with_brand += 1
        # 来源必须可回溯：批次声明的来源要和生成项上的回溯边对得上
        if batch.source == "opportunity" and item.opportunity_id is None:
            blockers.append(_blocker("source_untraceable", "机会来源的生成项缺少 opportunity_id", item.id))
        if batch.source == "question" and item.question_id is None:
            blockers.append(_blocker("source_untraceable", "问题来源的生成项缺少 question_id", item.id))
        if batch.source == "remediation" and not brief.get("citation_id"):
            blockers.append(_blocker("remediation_evidence_missing", "纠正稿缺少负面引用证据", item.id))

    if items and with_facts == 0:
        blockers.append(_blocker("facts_missing", "整批没有任何已批准事实可引用，模板稿会退化为泛泛而谈"))
    if items and with_brand == 0:
        blockers.append(_blocker("brand_missing", "写作简报里没有品牌名，实体指向会含糊"))

    row = GenerationGateResult(
        project_id=project_id,
        batch_id=batch.id,
        gate_type=GateType.PRECHECK,
        passed=not blockers,
        blockers=blockers,
        metrics={
            "items": len(items),
            "with_facts": with_facts,
            "with_brand": with_brand,
            "source": batch.source,
            "min_items_for_gate": GATE_MIN_ITEMS,
        },
        created_by=actor_id,
    )
    db.add(row)
    db.flush()
    return row


def _score_item(db: Session, project: Project, item: GenerationItem, body: str) -> dict[str, Any]:
    brief = item.brief or {}
    context = _company_context(db, project.id)
    result = score_content_geo(
        title=item.title,
        body=body,
        question_texts=[],
        keyword_names=[],
        citation_count=1 if brief.get("citation_id") else 0,
        fact_links=[{"key": f.get("key"), "value": f.get("value"), "stale": False} for f in brief.get("facts") or []],
        brand_terms=_brand_terms(db, project),
        product_terms=context["products"],
        context_terms=context["context_terms"],
        identifier_terms=context["identifiers"],
        owned_domains=context["owned_domains"],
    )
    average = round(sum(d["score"] for d in result["dimensions"]) / len(result["dimensions"]), 1)
    return {
        "average": average,
        "word_count": result["body_metrics"]["word_count"],
        "low_dimensions": [d["key"] for d in result["dimensions"] if d["low"]],
        "dimensions": [{"key": d["key"], "label": d["label"], "score": d["score"]} for d in result["dimensions"]],
    }


def sample_review(
    db: Session,
    *,
    project_id: uuid.UUID,
    batch: GenerationBatch,
    actor_id: uuid.UUID | None,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    threshold: int = DEFAULT_THRESHOLD,
) -> GenerationGateResult:
    """取前 N 个待生成项真出稿并打分；样本项状态转为 drafted，全量跑不会重复生成它们。"""
    _require_gateable(batch)
    size = max(1, min(sample_size, MAX_SAMPLE_SIZE))
    if not 0 <= threshold <= 100:
        raise ConflictError("阈值必须在 0–100 之间", code="gate_threshold_invalid")
    project = db.get(Project, project_id)
    if project is None:
        raise ConflictError("项目不存在", code="project_missing")

    pending = [
        item for item in _items(db, batch) if item.status == GenerationItemStatus.PENDING
    ][:size]
    if not pending:
        raise ConflictError("没有待生成项可取样，闸门无法判断这批写法", code="gate_no_sample")

    entries: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for item in pending:
        body = _draft(item.brief or {}, item.title)
        item.draft_body = body
        item.generation_mode = GenerationMode.TEMPLATE
        item.status = ensure_generation_item_transition(item.status, GenerationItemStatus.DRAFTED)
        scored = _score_item(db, project, item, body)
        entry = {
            "item_id": str(item.id),
            "title": item.title,
            "average": scored["average"],
            "word_count": scored["word_count"],
            "low_dimensions": scored["low_dimensions"],
            "dimensions": scored["dimensions"],
        }
        entries.append(entry)
        if scored["average"] < threshold:
            blockers.append(
                _blocker(
                    "sample_below_threshold",
                    f"样本 {item.title} 六项均分 {scored['average']} 低于阈值 {threshold}；"
                    f"低分项：{', '.join(scored['low_dimensions']) or '无'}",
                    item.id,
                )
            )

    batch.drafted_items = batch.drafted_items + len(entries)
    average = round(sum(entry["average"] for entry in entries) / len(entries), 1)
    row = GenerationGateResult(
        project_id=project_id,
        batch_id=batch.id,
        gate_type=GateType.SAMPLE_REVIEW,
        passed=not blockers,
        score=int(round(average)),
        threshold=threshold,
        sample_size=len(entries),
        blockers=blockers,
        metrics={
            "items": entries,
            "average": average,
            # 字数只记数：短稿提示“模板写法偏薄”，但放行与否只看六项均分
            "short_samples": [entry["item_id"] for entry in entries if entry["word_count"] < SOFT_MIN_WORDS],
            "soft_min_words": SOFT_MIN_WORDS,
        },
        created_by=actor_id,
    )
    db.add(row)
    db.flush()
    return row


def approve(
    db: Session,
    *,
    project_id: uuid.UUID,
    batch: GenerationBatch,
    actor_id: uuid.UUID | None,
    note: str | None = None,
) -> GenerationGateResult:
    """人工签核：只有小样已通过才允许签，签核不可替代小样打分。"""
    _require_gateable(batch)
    latest_review = db.scalar(
        select(GenerationGateResult)
        .where(
            GenerationGateResult.batch_id == batch.id,
            GenerationGateResult.gate_type == GateType.SAMPLE_REVIEW,
        )
        .order_by(GenerationGateResult.created_at.desc())
        .limit(1)
    )
    if latest_review is None:
        raise ConflictError("还没有小样评测结果，先跑 sample-review", code="gate_sample_missing")
    if not latest_review.passed:
        raise ConflictError("小样未达标，不能签核放行", code="gate_sample_failed")

    existing = db.scalar(
        select(GenerationGateResult).where(
            GenerationGateResult.batch_id == batch.id,
            GenerationGateResult.gate_type == GateType.APPROVAL,
            GenerationGateResult.passed.is_(True),
        )
    )
    if existing is not None:
        return existing

    row = GenerationGateResult(
        project_id=project_id,
        batch_id=batch.id,
        gate_type=GateType.APPROVAL,
        passed=True,
        score=latest_review.score,
        threshold=latest_review.threshold,
        sample_size=latest_review.sample_size,
        metrics={"sample_review_id": str(latest_review.id), "average": latest_review.score},
        note=note,
        created_by=actor_id,
    )
    db.add(row)
    db.flush()
    return row


def ensure_gate_satisfied(db: Session, batch: GenerationBatch) -> None:
    """全量跑的前置检查：规模达线的批次必须有「小样通过 + 人工签核」。"""
    if batch.total_items < GATE_MIN_ITEMS:
        return
    approval = db.scalar(
        select(GenerationGateResult).where(
            GenerationGateResult.batch_id == batch.id,
            GenerationGateResult.gate_type == GateType.APPROVAL,
            GenerationGateResult.passed.is_(True),
        )
    )
    if approval is None:
        raise ConflictError(
            f"批次共 {batch.total_items} 篇，达到 {GATE_MIN_ITEMS} 篇闸门线："
            "先跑 sample-review 再由审核人签核，才能全量出稿",
            code="generation_gate_required",
        )


def page_gates(db: Session, batch: GenerationBatch) -> list[GenerationGateResult]:
    return list(
        db.scalars(
            select(GenerationGateResult)
            .where(GenerationGateResult.batch_id == batch.id)
            .order_by(GenerationGateResult.created_at.desc())
        )
    )
