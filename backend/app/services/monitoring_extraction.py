"""把一次回答落成结构化维度：品牌提及、品牌可识别、引用 used/cited、竞品提及。

边界：
- 这里只做“从适配器返回的结构化结果/原始响应到库字段”的映射，不负责发请求；
- 原始文本解析是兜底，能拿到结构化 citations / competitor_mentions 时应优先用结构化结果；
- 品牌口径分两层，谁也不能覆盖谁：
  * `brand_mentioned` 只认品牌名/别名（严格，跨引擎可比）；
  * `brand_identified` 认地址/电话/公众号等唯一标识（宽松，衡量“可识别”），
    未配置标识词表时恒为 False，不会凭空放大命中；
- 引用 used/cited 由适配器或调用方显式给出，未给出时只按“明确 URL”记 cited，不猜测 used。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable
from urllib.parse import urlparse

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Channel,
    CitationSourceReview,
    Competitor,
    MonitoringCitation,
    MonitoringCompetitorMention,
    MonitoringSample,
)
from app.models.enums import (
    AnswerKind,
    ChannelStatus,
    CitationPageType,
    CitationUsage,
    ClassificationSource,
    CitationReviewStatus,
    SourceCategory,
    SourceReviewStatus,
)
from app.services.state_machine import ensure_channel_transition
from app.services.citation_attribution import canonical_url, url_key
from app.services.citation_attribution import build_published_index, resolve_published
from app.services.citation_attribution import build_domain_channel_index, resolve_channel_domain
from app.services.citation_classification import (
    CLASSIFIER_VERSION,
    classify_citation,
    known_domains,
    manual_category_map,
    normalize_domain,
)


@dataclass
class CitationInput:
    url: str
    usage: CitationUsage = CitationUsage.CITED
    competitor_name: str | None = None
    is_brand_related: bool | None = None
    title: str | None = None
    site_name: str | None = None
    snippet: str | None = None
    published_at: datetime | None = None
    position: int | None = None
    provider_fields: dict[str, Any] | None = None


@dataclass
class CompetitorMentionInput:
    name: str
    position: int | None = None
    evidence_text: str | None = None


# 匹配规则版本：证据落库时必须带版本，规则升级后可区分旧样本。
MATCHER_VERSION = "substring-regex-v1"


@dataclass(frozen=True)
class BrandMatch:
    """一次品牌匹配的完整证据：谁命中、命中在哪、原文长什么样。"""

    kind: str  # mention / identifier
    term: str
    offset: int
    evidence_text: str
    list_rank: int | None = None


def _list_rank(text: str, position: int) -> int | None:
    """仅当命中词落在有序列表项时返回位次；正文散文一律返回 None。

    AI 回答里的“推荐顺序”经常是 1. 2. 3. 列表，也可能用 - 项目符号。
    这里只做保守解析：命中行必须以数字编号或项目符号开头，才认为有列表位次。
    """
    line_start = text.rfind("\n", 0, position) + 1
    line_end = text.find("\n", position)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    marker = re.match(r"^\s*(?:(\d+)[.、)]|[-*])\s+", line)
    if marker is None:
        return None
    if marker.group(1):
        number = int(marker.group(1))
        return number if 1 <= number <= 50 else None
    # 项目符号没有显式编号：按它前面同类列表项的数量推算位次。
    prefix = text[:line_start]
    rank = len(re.findall(r"(?m)^\s*[-*]\s+", prefix)) + 1
    return rank if rank <= 50 else None


def locate_brand_match(
    text: str | None,
    terms: Iterable[str] | None,
    *,
    kind: str = "mention",
    context_chars: int = 24,
) -> BrandMatch | None:
    """在原文中定位最早出现的品牌词，返回匹配证据。

    匹配口径与旧 `detect_brand_mention` 保持一致：不区分大小写的子串匹配。
    多词同时命中时取出现位置最靠前者；同位置取更长词，保证证据稳定可复现。
    """
    if not text or not terms:
        return None
    candidates: list[tuple[int, int, str, int]] = []
    for raw in terms:
        term = str(raw).strip()
        if not term:
            continue
        match = re.search(re.escape(term), text, flags=re.IGNORECASE)
        if match is not None:
            candidates.append((match.start(), -len(term), term, match.end()))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    start, _negative_length, term, end = candidates[0]
    left = max(0, start - context_chars)
    right = min(len(text), end + context_chars)
    evidence = text[left:right].replace("\n", " ").strip()
    return BrandMatch(
        kind=kind,
        term=term,
        offset=start,
        evidence_text=evidence,
        list_rank=_list_rank(text, start) if kind == "mention" else None,
    )


@dataclass
class AnswerPayload:
    """适配器返回的标准答案；字段缺失时由调用方按任务/入口元数据兜底。"""

    text: str = ""
    raw_response: dict[str, Any] | None = None
    brand_mentioned: bool | None = None
    # 适配器若能直接判断“答案含品牌唯一标识”（如网页版带了结构化卡片），在此显式上报；
    # 留空则交给调用方按品牌标识词表判定。
    brand_identified: bool | None = None
    brand_recommendation: bool | None = None
    recommendation_reason: str | None = None
    entity_mention_count: int | None = None
    # 答案口径：answer / search_result。留空由调用方按 raw_response.answer_kind 兜底。
    answer_kind: AnswerKind | None = None
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
    gateway_attempts: int | None = None
    gateway_fallback_from: str | None = None


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


def _as_answer_kind(value: object) -> AnswerKind | None:
    """把 raw_response 里的 answer_kind 归一成枚举；非法值直接抛错，不静默降级。"""
    if value is None:
        return None
    raw = getattr(value, "value", value)
    if isinstance(raw, AnswerKind):
        return raw
    if isinstance(raw, str):
        try:
            return AnswerKind(raw)
        except ValueError:
            allowed = ", ".join(member.value for member in AnswerKind)
            raise ValueError(f"非法 answer_kind：{raw!r}（允许 {allowed}）") from None
    raise ValueError(f"非法 answer_kind 类型：{type(value).__name__}")


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _as_datetime(value: object) -> datetime | None:
    """把 provider 的发布时间/日期归一成 datetime；无法识别时保留空值。"""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y年%m月%d日",
        "%Y年%m月%d日 %H:%M",
        "%Y.%m.%d",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _citation_text(item: CitationInput) -> str:
    return "\n".join(part for part in (item.title, item.snippet) if part)


def citation_from_item(item: object) -> CitationInput | None:
    if isinstance(item, str):
        url = item.strip()
        return CitationInput(url=url) if url else None
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or item.get("raw_url") or item.get("link") or item.get("source") or "").strip()
    if not url:
        return None
    raw_position = item.get("position") or item.get("index") or item.get("rank")
    position = int(raw_position) if isinstance(raw_position, (int, float)) else None
    title = _clean_text(item.get("title") or item.get("name"))
    site_name = _clean_text(
        item.get("site_name")
        or item.get("sitename")
        or item.get("source_name")
        or item.get("website")
        or item.get("media")
    )
    snippet = _clean_text(
        item.get("snippet")
        or item.get("summary")
        or item.get("content")
        or item.get("passage")
    )
    published_at = _as_datetime(
        item.get("published_at")
        or item.get("publish_time")
        or item.get("publish_date")
        or item.get("date")
        or item.get("published_date")
    )
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
        title=title,
        site_name=site_name,
        snippet=snippet,
        published_at=published_at,
        position=position,
        provider_fields=dict(item),
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
    payload.brand_identified = (
        bool(raw_response["brand_identified"])
        if "brand_identified" in raw_response
        else None
    )
    payload.brand_recommendation = (
        bool(raw_response["brand_recommendation"])
        if "brand_recommendation" in raw_response
        else None
    )
    payload.recommendation_reason = _clean_text(raw_response.get("recommendation_reason"))
    raw_entity_count = raw_response.get("entity_mention_count")
    if isinstance(raw_entity_count, (int, float)) and not isinstance(raw_entity_count, bool):
        payload.entity_mention_count = max(0, int(raw_entity_count))
    if raw_response.get("answer_kind") is not None:
        payload.answer_kind = _as_answer_kind(raw_response.get("answer_kind"))
    for key in ("engine_model", "model_version", "country_code", "language"):
        value = raw_response.get(key)
        if value:
            setattr(payload, key, str(value))

    raw_citations = raw_response.get("citations") or raw_response.get("sources") or []
    if isinstance(raw_citations, list):
        payload.citations = [
            citation
            for item in raw_citations
            if (citation := citation_from_item(item)) is not None
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


def count_brand_occurrences(text: str | None, brand_terms: Iterable[str] | None) -> int:
    """统计品牌词出现次数；长词优先，重叠的别名命中只算一次。"""
    if not text or not brand_terms:
        return 0
    folded = text.casefold()
    terms = sorted(
        {str(term).strip().casefold() for term in brand_terms if str(term).strip()},
        key=len,
        reverse=True,
    )
    spans: list[tuple[int, int]] = []
    for term in terms:
        for match in re.finditer(re.escape(term), folded):
            start, end = match.start(), match.end()
            if any(start < existing_end and end > existing_start for existing_start, existing_end in spans):
                continue
            spans.append((start, end))
    return len(spans)


def detect_brand_identified(text: str | None, identifiers: Iterable[str] | None) -> bool:
    """答案没点名、但给出了能唯一定位品牌标识时记为可识别。

    标识通常是地址、电话、公众号名，判定口径是「包含」而不是「等于」：
    答案里通常是「地址是 xxx」「联系电话 xxx」这类句式，标识本身只是片段。
    """
    if not text or not identifiers:
        return False
    folded = text.casefold()
    return any(
        term.strip().casefold() in folded for term in identifiers if term and term.strip()
    )


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


def _promote_channels_observed(
    db: Session, project_id: uuid.UUID, channel_ids: set[uuid.UUID]
) -> None:
    """引用命中渠道域名后，把候选/待归类渠道置「已观测」。

    只推进 candidate / review_pending：published（我们已发过）与 observed 都是
    有效产出状态，发布回执结案已经推进过一次，这里不覆盖、不回退。
    """
    rows = db.scalars(
        select(Channel).where(
            Channel.project_id == project_id,
            Channel.id.in_(channel_ids),
            Channel.status.in_([ChannelStatus.CANDIDATE, ChannelStatus.REVIEW_PENDING]),
        )
    ).all()
    for row in rows:
        row.status = ensure_channel_transition(row.status, ChannelStatus.OBSERVED)


def apply_answer_payload(
    db: Session,
    sample: MonitoringSample,
    payload: AnswerPayload,
    *,
    brand_terms: Iterable[str] | None = None,
    brand_domains: Iterable[str] | None = None,
    brand_identifiers: Iterable[str] | None = None,
    published_index: dict | None = None,
    domain_channel_index: dict | None = None,
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

    # answer_kind：优先用显式字段，否则从 raw_response 兜底；两者都无则保持 NULL（执行前占位）。
    answer_kind_value = payload.answer_kind
    if answer_kind_value is None and isinstance(payload.raw_response, dict):
        answer_kind_value = payload.raw_response.get("answer_kind")
    if answer_kind_value is not None:
        sample.answer_kind = _as_answer_kind(answer_kind_value)

    brand_domain_set = {d.strip().lower().removeprefix("www.") for d in (brand_domains or []) if d}
    brand_terms = list(brand_terms or [])
    brand_identifiers = list(brand_identifiers or [])
    mention_match = locate_brand_match(payload.text, brand_terms, kind="mention")
    identifier_match = locate_brand_match(payload.text, brand_identifiers, kind="identifier")
    brand_mentioned = (
        payload.brand_mentioned
        if payload.brand_mentioned is not None
        else mention_match is not None
    )
    sample.brand_mentioned = bool(brand_mentioned)
    # 适配器若已显式上报则以它为准，否则按标识词表判定。
    sample.brand_identified = bool(
        payload.brand_identified
        if payload.brand_identified is not None
        else identifier_match is not None
    )

    # 统一匹配证据：优先记录点名提及；没有点名但可识别时记录标识命中。
    chosen_match = mention_match
    if chosen_match is None and sample.brand_identified:
        chosen_match = identifier_match
    if chosen_match is None:
        sample.brand_match_kind = None
        sample.brand_match_term = None
        sample.brand_match_offset = None
        sample.brand_match_evidence = None
        sample.brand_list_rank = None
    else:
        sample.brand_match_kind = chosen_match.kind
        sample.brand_match_term = chosen_match.term
        sample.brand_match_offset = chosen_match.offset
        sample.brand_match_evidence = chosen_match.evidence_text
        sample.brand_list_rank = chosen_match.list_rank
    sample.matcher_version = MATCHER_VERSION

    if payload.text:
        sample.entity_mention_count = (
            payload.entity_mention_count
            if payload.entity_mention_count is not None
            else count_brand_occurrences(payload.text, brand_terms)
        )
    else:
        sample.entity_mention_count = None

    recommendation = payload.brand_recommendation
    reason = payload.recommendation_reason
    if recommendation is None:
        if not payload.text:
            recommendation = None
            reason = None
        elif not sample.brand_mentioned:
            recommendation = False
            reason = "brand_absent"
        elif sample.brand_list_rank is None:
            # 提到了品牌但没有有序推荐列表：无法判断是否被推荐，保持 NULL。
            recommendation = None
            reason = "mentioned_without_ordered_list"
        else:
            recommendation = sample.brand_list_rank <= 3
            reason = "list_rank_top3" if recommendation else "list_rank_outside_top3"
    elif recommendation and reason is None:
        reason = "explicit_recommendation"
    elif not recommendation and reason is None:
        reason = "explicit_not_recommended"
    sample.brand_recommendation = recommendation
    sample.recommendation_reason = reason

    citation_count = 0
    # 渠道归属只认「我们真发过的页面 URL」（publish_receipts），不按域名糊整站；
    # 一次采集共用一份回执索引：调用方传入则复用，否则按需构建一次。
    if published_index is None:
        published_index = build_published_index(db, sample.project_id)
    if domain_channel_index is None:
        domain_channel_index = build_domain_channel_index(db, sample.project_id)
    # 来源分类用项目已登记域名做“未知”边界；未知只进审核队列，不创建渠道。
    registered_domains = known_domains(db, sample.project_id)
    manual_categories = manual_category_map(db, sample.project_id)
    reviews = {
        normalize_domain(row.domain) or row.domain: row
        for row in db.scalars(
            select(CitationSourceReview).where(
                CitationSourceReview.project_id == sample.project_id
            )
        )
    }
    competitor_domains = {
        normalize_domain(value)
        for value in db.scalars(
            select(Competitor.domain).where(Competitor.project_id == sample.project_id)
        )
        if value
    }
    # 观测口径：引用域名命中渠道台账域名（含别名，子域上溯）= 该信源被 AI 引用，
    # 候选渠道推进到 observed；渠道效果（channel_citations）仍只认发布回执 URL。
    observed_channel_ids: set[uuid.UUID] = set()
    for position, item in enumerate(payload.citations, start=1):
        raw_url, domain = normalize_url(item.url)
        if not raw_url:
            continue
        observed_channel = resolve_channel_domain(domain_channel_index, domain)
        if observed_channel is not None:
            observed_channel_ids.add(observed_channel)
        normalized = canonical_url(raw_url) or raw_url
        # 品牌相关先看自有域名，再看标题/摘要里的品牌词或唯一标识；
        # 第三方媒体/论坛/竞品文章只要正文证据命中，也会进入品牌引用候选。
        citation_text = _citation_text(item)
        if item.is_brand_related is not None:
            brand_related = bool(item.is_brand_related)
        elif domain and domain in brand_domain_set:
            brand_related = True
        else:
            brand_related = bool(
                detect_brand_mention(citation_text, brand_terms)
                or detect_brand_identified(citation_text, brand_identifiers)
            )
        existing = db.scalar(
            select(MonitoringCitation).where(
                MonitoringCitation.project_id == sample.project_id,
                MonitoringCitation.sample_id == sample.id,
                or_(
                    MonitoringCitation.normalized_url == normalized,
                    MonitoringCitation.raw_url == raw_url,
                ),
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

        classification = classify_citation(
            domain=domain, url=raw_url, title=item.title
        )
        manual_category = manual_categories.get(domain or "")
        if manual_category is not None:
            source_category = manual_category
            classification_source = ClassificationSource.MANUAL
        elif domain and domain in brand_domain_set:
            source_category = SourceCategory.BRAND_OWNED
            classification_source = ClassificationSource.RULE
        elif domain and domain in competitor_domains:
            source_category = SourceCategory.COMPETITOR_OWNED
            classification_source = ClassificationSource.RULE
        else:
            source_category = classification.source_category
            classification_source = ClassificationSource.RULE

        # 未知被引域名：只建/更新审核队列项，不自动成为发布渠道
        if domain and domain not in registered_domains:
            review = reviews.get(domain)
            if review is None:
                review = CitationSourceReview(
                    project_id=sample.project_id,
                    domain=domain,
                    status=SourceReviewStatus.PENDING,
                    suggested_source_category=classification.source_category,
                    classification_source=ClassificationSource.RULE,
                    classification_rule_version=CLASSIFIER_VERSION,
                )
                db.add(review)
                reviews[domain] = review
            elif review.suggested_source_category is None:
                review.suggested_source_category = classification.source_category

        if existing is None:
            target = resolve_published(published_index, raw_url)
            existing = MonitoringCitation(
                project_id=sample.project_id,
                sample_id=sample.id,
                trace_id=sample.trace_id,
                raw_url=raw_url,
                normalized_url=normalized,
                domain=domain,
                # 手测/网页端结果经常只带链接：用域名兜底标题，情绪盲评才有可读条目。
                title=item.title or domain,
                site_name=item.site_name,
                snippet=item.snippet,
                published_at=item.published_at,
                position=item.position if item.position is not None else position,
                source_category=source_category,
                page_type=classification.page_type,
                classification_source=classification_source,
                classification_rule_version=CLASSIFIER_VERSION,
                provider_fields=item.provider_fields,
                channel_id=target.channel_id if target else None,
                citation_usage=item.usage,
                competitor_id=competitor.id if competitor else None,
                is_brand_related=bool(brand_related),
            )
            db.add(existing)
        else:
            existing.trace_id = existing.trace_id or sample.trace_id
            existing.normalized_url = normalized
            existing.domain = existing.domain or domain
            # 原始证据只补不改：标题/站点名/摘要/发布时间/provider 字段首次落库后不再被覆盖
            existing.title = existing.title or item.title
            existing.site_name = existing.site_name or item.site_name
            existing.snippet = existing.snippet or item.snippet
            existing.published_at = existing.published_at or item.published_at
            existing.position = existing.position or (
                item.position if item.position is not None else position
            )
            existing.provider_fields = existing.provider_fields or item.provider_fields
            # 人工分类结果优先，自动分类不覆盖
            if existing.classification_source != ClassificationSource.MANUAL:
                existing.source_category = source_category
                existing.page_type = classification.page_type
                existing.classification_source = classification_source
                existing.classification_rule_version = CLASSIFIER_VERSION
            # 渠道归属只补不改：人工归类的结果不被后续采集覆盖
            if existing.channel_id is None:
                target = resolve_published(published_index, raw_url)
                if target is not None:
                    existing.channel_id = target.channel_id
            existing.citation_usage = item.usage
            if competitor is not None:
                existing.competitor_id = competitor.id
        if item.is_brand_related is not None:
            existing.is_brand_related = item.is_brand_related
        elif existing.review_status == CitationReviewStatus.AUTO:
            existing.is_brand_related = bool(brand_related)
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

    if observed_channel_ids:
        _promote_channels_observed(db, sample.project_id, observed_channel_ids)

    db.flush()
    return {
        "brand_mentioned": bool(brand_mentioned),
        "brand_identified": bool(sample.brand_identified),
        "brand_recommendation": sample.brand_recommendation,
        "entity_mention_count": sample.entity_mention_count,
        "citation_count": citation_count,
        "competitor_mention_count": mention_count,
    }
