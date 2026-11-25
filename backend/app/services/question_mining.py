"""问题候选池：从企业资料/关键词/竞品派生候选，外部问句可导入，人工确认后才入题库。

边界：
- 挖掘只做确定性模板，不调用外部 AI，不抓取平台；
- 所有候选先落 `pending`，不自动激活、不自动生成监测任务；
- 采纳时新建 `draft` 题目 + v1，正式启用仍走题库原有状态机；
- 用规范化文本指纹去重，避免空格/标点差异造成重复题。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ConflictError, ResourceMissingError
from app.services.state_machine import ensure_question_candidate_transition
from app.models import (
    BrandProfile,
    CompanyProfile,
    Competitor,
    Keyword,
    Question,
    QuestionCandidate,
    QuestionVersion,
)
from app.models.enums import (
    QuestionCandidateBucket,
    QuestionCandidateSource,
    QuestionCandidateStatus,
    QuestionStatus,
    QuestionType,
)
from app.services.audit import record_audit

MAX_CANDIDATES = 50
MAX_IMPORT_TEXTS = 100
MAX_TEXT_CHARS = 500

_BUCKET_PRIORITY = {
    QuestionCandidateBucket.CATEGORY: 50,
    QuestionCandidateBucket.PURCHASE: 70,
    QuestionCandidateBucket.REPUTATION: 90,
}
_BUCKET_INTENT = {
    QuestionCandidateBucket.CATEGORY: "品类认知",
    QuestionCandidateBucket.PURCHASE: "选购决策",
    QuestionCandidateBucket.REPUTATION: "口碑验证",
}
_BUCKET_LABEL = {
    QuestionCandidateBucket.CATEGORY: "品类",
    QuestionCandidateBucket.PURCHASE: "选购",
    QuestionCandidateBucket.REPUTATION: "口碑",
}


def normalize_question_text(text: str) -> str:
    """统一全半角、大小写与标点空白，用于判断两句话是否同一题。"""
    value = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\s\u3000。，、！？；：,.!?;:（）()\[\]【】“”\"'·-]+", "", value)


def question_fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_question_text(text).encode("utf-8")).hexdigest()


def _clean_text(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        raise BusinessValidationError("候选问句不能为空")
    if len(value) > MAX_TEXT_CHARS:
        raise BusinessValidationError(f"候选问句不能超过 {MAX_TEXT_CHARS} 字")
    return value


def _unique_strings(values: list[Any], limit: int) -> list[str]:
    result: list[str] = []
    for item in values:
        value = str(item or "").strip()
        if value and value not in result:
            result.append(value)
        if len(result) >= limit:
            break
    return result


def _product_names(products: list[dict] | None) -> list[str]:
    names: list[Any] = []
    for item in products or []:
        if isinstance(item, dict):
            names.append(
                item.get("name")
                or item.get("title")
                or item.get("product")
                or item.get("model")
            )
        elif isinstance(item, str):
            names.append(item)
    return _unique_strings(names, 3)


def _project_context(db: Session, project_id: uuid.UUID) -> dict[str, Any]:
    brand = db.scalar(
        select(BrandProfile).where(
            BrandProfile.project_id == project_id,
            BrandProfile.is_active.is_(True),
        )
    )
    company = db.scalar(
        select(CompanyProfile).where(
            CompanyProfile.project_id == project_id,
            CompanyProfile.is_active.is_(True),
        )
    )
    keywords = _unique_strings(
        db.scalars(
            select(Keyword.name)
            .where(Keyword.project_id == project_id, Keyword.is_active.is_(True))
            .order_by(Keyword.priority, Keyword.name)
        ).all(),
        5,
    )
    competitors = _unique_strings(
        db.scalars(
            select(Competitor.name)
            .where(Competitor.project_id == project_id, Competitor.is_active.is_(True))
            .order_by(Competitor.name)
        ).all(),
        3,
    )
    audiences = _unique_strings(
        db.scalars(
            select(Question.audience).where(
                Question.project_id == project_id,
                Question.audience.is_not(None),
            )
        ).all(),
        2,
    )
    return {
        "brand": (company.brand_name if company and company.brand_name else None)
        or (brand.canonical_name if brand else None),
        "industries": _unique_strings(list(company.industries or []) if company else [], 3),
        "products": _product_names(company.products if company else None),
        "regions": _unique_strings(
            list(company.regions or []) if company else [], 2
        ) or _unique_strings([company.province] if company and company.province else [], 2),
        "keywords": keywords,
        "competitors": competitors,
        "audience": audiences[0] if audiences else "采购决策人",
    }


def _candidate_templates(context: dict[str, Any]) -> list[dict[str, Any]]:
    """按三桶生成候选；每条都带来源字段，方便运营判断为什么出现。"""
    brand = context["brand"]
    industries = context["industries"]
    products = context["products"]
    regions = context["regions"]
    keywords = context["keywords"]
    competitors = context["competitors"]
    audience = context["audience"]
    rows: list[dict[str, Any]] = []

    def add(
        text: str,
        bucket: QuestionCandidateBucket,
        question_type: QuestionType,
        source_ref: str,
        rationale: str,
    ) -> None:
        rows.append(
            {
                "text": text,
                "bucket": bucket,
                "question_type": question_type,
                "source_ref": source_ref,
                "rationale": rationale,
            }
        )

    for industry in industries:
        add(
            f"{industry}行业怎么选？",
            QuestionCandidateBucket.CATEGORY,
            QuestionType.GENERAL,
            "company.industries",
            f"从企业所属行业「{industry}」派生品类认知题。",
        )
        add(
            f"{industry}有哪些主流品牌？",
            QuestionCandidateBucket.CATEGORY,
            QuestionType.GENERAL,
            "company.industries",
            f"从企业所属行业「{industry}」派生品类对比题。",
        )
        add(
            f"{industry}服务报价一般多少？",
            QuestionCandidateBucket.PURCHASE,
            QuestionType.GENERAL,
            "company.industries",
            f"从「{industry}」派生价格决策题。",
        )

    for product in products:
        add(
            f"{product}是什么？",
            QuestionCandidateBucket.CATEGORY,
            QuestionType.GENERAL,
            "company.products",
            f"从企业产品「{product}」派生实体定义题。",
        )
        add(
            f"{product}怎么选？",
            QuestionCandidateBucket.PURCHASE,
            QuestionType.GENERAL,
            "company.products",
            f"从企业产品「{product}」派生选购决策题。",
        )
        add(
            f"{product}和同类产品有什么区别？",
            QuestionCandidateBucket.PURCHASE,
            QuestionType.GENERAL,
            "company.products",
            f"从企业产品「{product}」派生差异化对比题。",
        )

    for region in regions:
        for industry in industries[:2]:
            add(
                f"{region}{industry}哪家好？",
                QuestionCandidateBucket.PURCHASE,
                QuestionType.GENERAL,
                "company.regions+industries",
                f"从区域「{region}」与行业「{industry}」派生本地选购题。",
            )

    for keyword in keywords:
        add(
            f"{keyword}怎么选？",
            QuestionCandidateBucket.PURCHASE,
            QuestionType.GENERAL,
            "keywords",
            f"从目标词「{keyword}」派生选购问句。",
        )

    if brand:
        add(
            f"{brand}怎么样？",
            QuestionCandidateBucket.REPUTATION,
            QuestionType.BRAND,
            "brand.canonical_name",
            "从品牌正式名派生口碑验证题。",
        )
        add(
            f"{brand}靠谱吗？",
            QuestionCandidateBucket.REPUTATION,
            QuestionType.BRAND,
            "brand.canonical_name",
            "从品牌正式名派生可信度题。",
        )
        add(
            f"{brand}的用户评价如何？",
            QuestionCandidateBucket.REPUTATION,
            QuestionType.BRAND,
            "brand.canonical_name",
            "从品牌正式名派生用户评价题。",
        )
        add(
            f"{brand}有什么缺点？",
            QuestionCandidateBucket.REPUTATION,
            QuestionType.BRAND,
            "brand.canonical_name",
            "从品牌正式名派生负面口碑题；不预设答案。",
        )
        add(
            f"{brand}售后服务怎么样？",
            QuestionCandidateBucket.REPUTATION,
            QuestionType.BRAND,
            "brand.canonical_name",
            "从品牌正式名派生售后服务题。",
        )
        for competitor in competitors:
            add(
                f"{brand}和{competitor}相比哪个好？",
                QuestionCandidateBucket.REPUTATION,
                QuestionType.BRAND,
                "brand+competitors",
                f"从品牌「{brand}」与竞品「{competitor}」派生对比题。",
            )

    # 统一补上人群/意图/优先级；模板本身不写人群，避免编造具体身份。
    for row in rows:
        row["audience"] = audience
        row["intent"] = _BUCKET_INTENT[row["bucket"]]
        row["priority"] = _BUCKET_PRIORITY[row["bucket"]]
    return rows


def _existing_fingerprints(db: Session, project_id: uuid.UUID) -> set[str]:
    question_texts = db.scalars(
        select(QuestionVersion.text).where(QuestionVersion.project_id == project_id)
    ).all()
    candidate_fingerprints = db.scalars(
        select(QuestionCandidate.fingerprint).where(QuestionCandidate.project_id == project_id)
    ).all()
    return {question_fingerprint(text) for text in question_texts} | set(candidate_fingerprints)


def _insert_candidates(
    db: Session,
    *,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    rows: list[dict[str, Any]],
    source: QuestionCandidateSource,
) -> dict[str, Any]:
    existing = _existing_fingerprints(db, project_id)
    created: list[QuestionCandidate] = []
    skipped = 0
    counts = {bucket.value: 0 for bucket in QuestionCandidateBucket}
    for row in rows:
        text = _clean_text(row["text"])
        fingerprint = question_fingerprint(text)
        if fingerprint in existing:
            skipped += 1
            continue
        candidate = QuestionCandidate(
            project_id=project_id,
            text=text,
            fingerprint=fingerprint,
            bucket=row["bucket"],
            question_type=row["question_type"],
            audience=row.get("audience"),
            intent=row.get("intent"),
            priority=row.get("priority", 100),
            source=source,
            source_ref=row.get("source_ref"),
            rationale=row.get("rationale"),
            status=QuestionCandidateStatus.PENDING,
            created_by=actor_id,
        )
        db.add(candidate)
        existing.add(fingerprint)
        created.append(candidate)
        counts[candidate.bucket.value] += 1
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("候选问句写入冲突，请重试", code="question_candidate_conflict") from exc
    return {"created": created, "skipped": skipped, "counts": counts}


def _interleave_buckets(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """三桶轮流出题，避免前 20 条被品类/选购占满、口碑一条都没有。"""
    groups: dict[QuestionCandidateBucket, list[dict[str, Any]]] = {
        bucket: [] for bucket in QuestionCandidateBucket
    }
    for row in rows:
        groups[row["bucket"]].append(row)
    ordered: list[dict[str, Any]] = []
    while len(ordered) < limit:
        added = False
        for bucket in QuestionCandidateBucket:
            if groups[bucket]:
                ordered.append(groups[bucket].pop(0))
                added = True
                if len(ordered) >= limit:
                    break
        if not added:
            break
    return ordered


def mine_candidates(
    db: Session,
    *,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    limit: int = 20,
    buckets: list[QuestionCandidateBucket] | None = None,
) -> dict[str, Any]:
    limit = max(1, min(MAX_CANDIDATES, int(limit)))
    context = _project_context(db, project_id)
    allowed_buckets = set(buckets or list(QuestionCandidateBucket))
    templates = [row for row in _candidate_templates(context) if row["bucket"] in allowed_buckets]
    selected = _interleave_buckets(templates, limit)
    result = _insert_candidates(
        db,
        project_id=project_id,
        actor_id=actor_id,
        rows=selected,
        source=QuestionCandidateSource.RULE,
    )
    missing_context = [
        label
        for key, label in (
            ("brand", "品牌正式名"),
            ("industries", "所属行业"),
            ("products", "产品"),
            ("regions", "区域"),
        )
        if not context[key]
    ]
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="question_candidate.mine",
        target_type="question_candidate",
        payload={
            "created": len(result["created"]),
            "skipped": result["skipped"],
            "limit": limit,
            "buckets": sorted(item.value for item in allowed_buckets),
            "missing_context": missing_context,
        },
    )
    return {
        "created": result["created"],
        "created_count": len(result["created"]),
        "skipped_count": result["skipped"],
        "counts": result["counts"],
        "missing_context": missing_context,
    }


def import_candidates(
    db: Session,
    *,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    texts: list[str],
    bucket: QuestionCandidateBucket,
    source_ref: str | None = None,
) -> dict[str, Any]:
    if not texts:
        raise BusinessValidationError("至少导入一条问句")
    if len(texts) > MAX_IMPORT_TEXTS:
        raise BusinessValidationError(f"单次最多导入 {MAX_IMPORT_TEXTS} 条")
    context = _project_context(db, project_id)
    brand_terms = [context["brand"]] if context["brand"] else []
    rows: list[dict[str, Any]] = []
    for text in texts:
        clean = _clean_text(text)
        question_type = (
            QuestionType.BRAND
            if any(term and term in clean for term in brand_terms)
            else QuestionType.GENERAL
        )
        rows.append(
            {
                "text": clean,
                "bucket": bucket,
                "question_type": question_type,
                "audience": context["audience"],
                "intent": _BUCKET_INTENT[bucket],
                "priority": _BUCKET_PRIORITY[bucket],
                "source_ref": source_ref or "运营导入",
                "rationale": f"运营从外部平台/人工调研导入，归入{_BUCKET_LABEL[bucket]}池。",
            }
        )
    result = _insert_candidates(
        db,
        project_id=project_id,
        actor_id=actor_id,
        rows=rows,
        source=QuestionCandidateSource.IMPORT,
    )
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="question_candidate.import",
        target_type="question_candidate",
        payload={
            "created": len(result["created"]),
            "skipped": result["skipped"],
            "bucket": bucket.value,
        },
    )
    return {
        "created": result["created"],
        "created_count": len(result["created"]),
        "skipped_count": result["skipped"],
        "counts": result["counts"],
    }


def _next_question_code(db: Session, project_id: uuid.UUID) -> str:
    existing = set(
        db.scalars(select(Question.code).where(Question.project_id == project_id)).all()
    )
    number = len(existing) + 1
    while True:
        code = f"Q{number:03d}"
        if code not in existing:
            return code
        number += 1


def accept_candidate(
    db: Session,
    *,
    project_id: uuid.UUID,
    candidate_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> dict[str, Any]:
    candidate = db.scalar(
        select(QuestionCandidate)
        .where(
            QuestionCandidate.project_id == project_id,
            QuestionCandidate.id == candidate_id,
        )
        .with_for_update()
    )
    if candidate is None:
        raise ResourceMissingError("候选问句不存在或不属于当前项目", code="question_candidate_missing")
    if candidate.status != QuestionCandidateStatus.PENDING:
        raise ConflictError("该候选已处理，不能重复采纳", code="question_candidate_not_pending")

    duplicate = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.project_id == project_id,
            QuestionVersion.text == candidate.text,
        )
    )
    if duplicate is None:
        question_fingerprints = {
            question_fingerprint(text)
            for text in db.scalars(
                select(QuestionVersion.text).where(
                    QuestionVersion.project_id == project_id
                )
            ).all()
        }
        duplicate = (
            candidate
            if candidate.fingerprint in question_fingerprints
            else None
        )
    if duplicate is not None:
        raise ConflictError("题库已有同题，请先驳回该候选", code="question_candidate_duplicate_question")

    question = Question(
        project_id=project_id,
        code=_next_question_code(db, project_id),
        title=candidate.text[:255],
        question_type=candidate.question_type,
        audience=candidate.audience,
        intent=candidate.intent,
        priority=candidate.priority,
        status=QuestionStatus.DRAFT,
        current_version_no=1,
    )
    db.add(question)
    db.flush()

    version = QuestionVersion(
        project_id=project_id,
        question_id=question.id,
        version_no=1,
        text=candidate.text,
        question_type=question.question_type,
        audience=question.audience,
        intent=question.intent,
        priority=question.priority,
        change_note="由问题候选池采纳生成",
        created_by=actor_id,
    )
    db.add(version)
    db.flush()

    candidate.status = ensure_question_candidate_transition(
        candidate.status, QuestionCandidateStatus.ACCEPTED
    )
    candidate.converted_question_id = question.id
    candidate.reviewed_by = actor_id
    candidate.reviewed_at = datetime.now(timezone.utc)
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="question_candidate.accept",
        target_type="question_candidate",
        target_id=candidate.id,
        payload={
            "question_id": str(question.id),
            "question_code": question.code,
            "bucket": candidate.bucket.value,
        },
    )
    return {
        "candidate_id": candidate.id,
        "question_id": question.id,
        "question_code": question.code,
        "version_no": 1,
    }


def reject_candidate(
    db: Session,
    *,
    project_id: uuid.UUID,
    candidate_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> QuestionCandidate:
    candidate = db.scalar(
        select(QuestionCandidate)
        .where(
            QuestionCandidate.project_id == project_id,
            QuestionCandidate.id == candidate_id,
        )
        .with_for_update()
    )
    if candidate is None:
        raise ResourceMissingError("候选问句不存在或不属于当前项目", code="question_candidate_missing")
    if candidate.status != QuestionCandidateStatus.PENDING:
        raise ConflictError("该候选已处理，不能重复驳回", code="question_candidate_not_pending")
    candidate.status = ensure_question_candidate_transition(
        candidate.status, QuestionCandidateStatus.REJECTED
    )
    candidate.reviewed_by = actor_id
    candidate.reviewed_at = datetime.now(timezone.utc)
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="question_candidate.reject",
        target_type="question_candidate",
        target_id=candidate.id,
        payload={"bucket": candidate.bucket.value},
    )
    return candidate


def candidate_payload(row: QuestionCandidate) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "text": row.text,
        "bucket": row.bucket.value,
        "question_type": row.question_type.value,
        "audience": row.audience,
        "intent": row.intent,
        "priority": row.priority,
        "source": row.source.value,
        "source_ref": row.source_ref,
        "rationale": row.rationale,
        "status": row.status.value,
        "converted_question_id": (
            str(row.converted_question_id) if row.converted_question_id else None
        ),
        "created_at": row.created_at,
        "reviewed_at": row.reviewed_at,
    }


def list_candidates(
    db: Session,
    *,
    project_id: uuid.UUID,
    status: QuestionCandidateStatus | None = None,
    bucket: QuestionCandidateBucket | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[QuestionCandidate], int]:
    """候选池分页查询；放在 service 层，保持 API 只做编排。"""
    filters = [QuestionCandidate.project_id == project_id]
    if status is not None:
        filters.append(QuestionCandidate.status == status)
    if bucket is not None:
        filters.append(QuestionCandidate.bucket == bucket)
    total = int(
        db.scalar(select(func.count()).select_from(QuestionCandidate).where(*filters))
        or 0
    )
    rows = list(
        db.scalars(
            select(QuestionCandidate)
            .where(*filters)
            .order_by(
                QuestionCandidate.priority,
                QuestionCandidate.created_at.desc(),
                QuestionCandidate.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return rows, total

