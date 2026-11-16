"""把一次回答落成结构化维度：品牌提及、引用 used/cited、竞品提及。

边界：
- 这里只做“从适配器返回的结构化结果/原始响应到库字段”的映射，不负责发请求；
- 原始文本解析是兜底，能拿到结构化 citations / competitor_mentions 时应优先用结构化结果；
- 品牌名匹配是项目名/项目 code 的简单包含判断，人工复核仍可覆盖 brand_mentioned；
- 引用 used/cited 由适配器或调用方显式给出，未给出时只按“明确 URL”记 cited，不猜测 used。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Competitor,
    MonitoringCitation,
    MonitoringCompetitorMention,
    MonitoringSample,
)
from app.models.enums import CitationUsage


@dataclass
class CitationInput:
    url: str
    usage: CitationUsage = CitationUsage.CITED
    competitor_name: str | None = None
    is_brand_related: bool | None = None


@dataclass
class CompetitorMentionInput:
    name: str
    position: int | None = None
    evidence_text: str | None = None


@dataclass
class AnswerPayload:
    """适配器返回的标准答案；字段缺失时由调用方按任务/入口元数据兜底。"""

    text: str = ""
    raw_response: dict[str, Any] | None = None
    brand_mentioned: bool | None = None
    engine_model: str | None = None
    model_version: str | None = None
    country_code: str | None = None
    language: str | None = None
    citations: list[CitationInput] = field(default_factory=list)
    competitor_mentions: list[CompetitorMentionInput] = field(default_factory=list)
    # 引擎网关留痕：不存 Authorization；只存请求体、耗时、token 与可选估算费用。
    trace_id: str | None = None
    request_payload: dict[str, Any] | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_cny: Decimal | None = None
    gateway_version: str | None = None


def normalize_url(raw_url: str) -> tuple[str, str | None]:
    """返回 (保留原样的 URL, 归一化域名)；域名去掉 www. 并转小写。"""
    value = raw_url.strip()
    if not value:
        return value, None
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return value, host or None


def _as_usage(value: object) -> CitationUsage:
    raw = getattr(value, "value", value)
    try:
        return CitationUsage(str(raw))
    except ValueError:
        return CitationUsage.CITED


def _citation_from_item(item: object) -> CitationInput | None:
    if isinstance(item, str):
        url = item.strip()
        return CitationInput(url=url) if url else None
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or item.get("raw_url") or item.get("link") or item.get("source") or "").strip()
    if not url:
        return None
    return CitationInput(
        url=url,
        usage=_as_usage(item.get("usage") or item.get("citation_usage")),
        competitor_name=(
            str(item.get("competitor_name")).strip()
            if item.get("competitor_name")
            else None
        ),
        is_brand_related=(
            bool(item.get("is_brand_related"))
            if item.get("is_brand_related") is not None
            else None
        ),
    )


def _mention_from_item(item: object) -> CompetitorMentionInput | None:
    if isinstance(item, str):
        return CompetitorMentionInput(name=item.strip()) if item.strip() else None
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or item.get("competitor_name") or "").strip()
    if not name:
        return None
    position = item.get("position")
    return CompetitorMentionInput(
        name=name,
        position=int(position) if isinstance(position, (int, float)) else None,
        evidence_text=str(item.get("evidence_text") or item.get("evidence") or "").strip() or None,
    )


def parse_raw_response(
    raw_response: dict[str, Any] | None,
    *,
    text: str | None = None,
) -> AnswerPayload:
    """把常见适配器响应形状归一成 AnswerPayload；不认识的形状不猜字段。"""
    payload = AnswerPayload(text=text or "", raw_response=raw_response)
    if not isinstance(raw_response, dict):
        return payload

    payload.text = payload.text or str(
        raw_response.get("answer")
        or raw_response.get("text")
        or raw_response.get("content")
        or raw_response.get("output_text")
        or ""
    )
    payload.brand_mentioned = (
        bool(raw_response["brand_mentioned"])
        if "brand_mentioned" in raw_response
        else None
    )
    for key in ("engine_model", "model_version", "country_code", "language"):
        value = raw_response.get(key)
        if value:
            setattr(payload, key, str(value))

    raw_citations = raw_response.get("citations") or raw_response.get("sources") or []
    if isinstance(raw_citations, list):
        payload.citations = [
            citation
            for item in raw_citations
            if (citation := _citation_from_item(item)) is not None
        ]

    raw_mentions = raw_response.get("competitor_mentions") or raw_response.get("competitors") or []
    if isinstance(raw_mentions, list):
        payload.competitor_mentions = [
            mention
            for item in raw_mentions
            if (mention := _mention_from_item(item)) is not None
        ]
    return payload


def detect_brand_mention(text: str | None, brand_terms: Iterable[str] | None) -> bool:
    if not text or not brand_terms:
        return False
    folded = text.casefold()
    return any(term.strip().casefold() in folded for term in brand_terms if term and term.strip())


def get_or_create_competitor(
    db: Session,
    *,
    project_id: uuid.UUID,
    name: str,
    domain: str | None = None,
) -> Competitor:
    clean = name.strip()
    if not clean:
        raise ValueError("competitor name is required")
    row = db.scalar(
        select(Competitor).where(
            Competitor.project_id == project_id,
            Competitor.name == clean,
        )
    )
    if row is None:
        row = Competitor(project_id=project_id, name=clean, domain=domain, is_active=True)
        db.add(row)
        db.flush()
    elif domain and not row.domain:
        row.domain = domain
    return row


def apply_answer_payload(
    db: Session,
    sample: MonitoringSample,
    payload: AnswerPayload,
    *,
    brand_terms: Iterable[str] | None = None,
    brand_domains: Iterable[str] | None = None,
) -> dict[str, Any]:
    """把标准答案写进 sample 及其引用/竞品提及，返回落库计数。"""
    if payload.text:
        sample.raw_answer = payload.text
    if payload.raw_response is not None:
        sample.raw_response = payload.raw_response
    if payload.trace_id:
        sample.trace_id = payload.trace_id
    if payload.request_payload is not None:
        sample.request_payload = payload.request_payload
    for key in (
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_cost_cny",
        "gateway_version",
    ):
        value = getattr(payload, key)
        if value is not None:
            setattr(sample, key, value)

    for key in ("engine_model", "model_version", "country_code", "language"):
        value = getattr(payload, key)
        if value:
            setattr(sample, key, value)

    brand_domain_set = {d.strip().lower().removeprefix("www.") for d in (brand_domains or []) if d}
    brand_mentioned = (
        payload.brand_mentioned
        if payload.brand_mentioned is not None
        else detect_brand_mention(payload.text, brand_terms)
    )
    sample.brand_mentioned = bool(brand_mentioned)

    citation_count = 0
    for item in payload.citations:
        raw_url, domain = normalize_url(item.url)
        if not raw_url:
            continue
        existing = db.scalar(
            select(MonitoringCitation).where(
                MonitoringCitation.project_id == sample.project_id,
                MonitoringCitation.sample_id == sample.id,
                MonitoringCitation.raw_url == raw_url,
            )
        )
        competitor = None
        if item.competitor_name:
            competitor = get_or_create_competitor(
                db,
                project_id=sample.project_id,
                name=item.competitor_name,
                domain=domain,
            )
        if existing is None:
            existing = MonitoringCitation(
                project_id=sample.project_id,
                sample_id=sample.id,
                trace_id=sample.trace_id,
                raw_url=raw_url,
                normalized_url=raw_url,
                domain=domain,
                citation_usage=item.usage,
                competitor_id=competitor.id if competitor else None,
            )
            db.add(existing)
        else:
            existing.trace_id = existing.trace_id or sample.trace_id
            existing.normalized_url = existing.normalized_url or raw_url
            existing.domain = existing.domain or domain
            existing.citation_usage = item.usage
            if competitor is not None:
                existing.competitor_id = competitor.id
        if item.is_brand_related is not None:
            existing.is_brand_related = item.is_brand_related
        elif existing.is_brand_related is None:
            existing.is_brand_related = bool(domain and domain in brand_domain_set)
        citation_count += 1

    mention_count = 0
    for index, item in enumerate(payload.competitor_mentions, start=1):
        competitor = get_or_create_competitor(
            db,
            project_id=sample.project_id,
            name=item.name,
        )
        existing_mention = db.scalar(
            select(MonitoringCompetitorMention).where(
                MonitoringCompetitorMention.project_id == sample.project_id,
                MonitoringCompetitorMention.sample_id == sample.id,
                MonitoringCompetitorMention.competitor_id == competitor.id,
            )
        )
        if existing_mention is None:
            existing_mention = MonitoringCompetitorMention(
                project_id=sample.project_id,
                sample_id=sample.id,
                competitor_id=competitor.id,
                position=item.position if item.position is not None else index,
                evidence_text=item.evidence_text,
            )
            db.add(existing_mention)
        else:
            existing_mention.position = (
                item.position if item.position is not None else existing_mention.position
            )
            existing_mention.evidence_text = item.evidence_text or existing_mention.evidence_text
        mention_count += 1

    db.flush()
    return {
        "brand_mentioned": bool(brand_mentioned),
        "citation_count": citation_count,
        "competitor_mention_count": mention_count,
    }
