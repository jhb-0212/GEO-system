"""情感抽样盲评（A）+ 负面风险预排序（C）。

两条线严格分开，绝不混成一个数：
- `sample`：按「轮次 + 引用 id」哈希稳定抽样，双人独立盲评，分歧留给人仲裁；
  只有当已形成共识的样本 ≥ MIN_REPORT 条，才报正向率，否则只报条数。
- `risk_scan`：负面提示词只用于把可疑条目排到前面给人看，**不进任何比率**，
  避免自动判断悄悄变成分数。

预排序纪律：词表只认明确的贬损/投诉表述，命中就标 `hints`，不推断强度、不评分。
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MonitoringCitation, SentimentLabel
from app.models.enums import CitationReviewStatus, SentimentPolarity

CONFIRMED = CitationReviewStatus.MANUAL_CONFIRMED
MIN_REPORT = 50
DEFAULT_SIZE = 12
RISK_SAMPLE = 10

# 只收明确负面表述；「价格」「学费」这类中性词不进来
NEGATIVE_HINTS: tuple[str, ...] = (
    "差评", "踩雷", "避雷", "坑人", "被骗", "骗局", "虚假宣传", "夸大宣传",
    "投诉", "维权", "退款难", "退费难", "不靠谱", "劝退", "割韭菜", "智商税",
    "跑路", "拉黑", "黑机构", "套路", "维权群", "被坑",
)


def _rank_key(round_no: int, citation_id: uuid.UUID) -> str:
    return hashlib.md5(f"{round_no}:{citation_id}".encode("utf-8")).hexdigest()


def _scan_rows(db: Session, project_id: uuid.UUID, *, brand_related_only: bool):
    stmt = select(MonitoringCitation).where(
        MonitoringCitation.project_id == project_id,
        MonitoringCitation.review_status == CONFIRMED,
        MonitoringCitation.title.is_not(None),
    )
    if brand_related_only:
        stmt = stmt.where(MonitoringCitation.is_brand_related.is_(True))
    return list(db.scalars(stmt))


def _labels_map(db: Session, project_id: uuid.UUID, citation_ids: list[uuid.UUID]):
    if not citation_ids:
        return {}
    rows = list(
        db.scalars(
            select(SentimentLabel).where(
                SentimentLabel.project_id == project_id,
                SentimentLabel.citation_id.in_(citation_ids),
            )
        )
    )
    grouped: dict[uuid.UUID, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.citation_id, []).append(
            {
                "polarity": row.polarity.value,
                "note": row.note,
                "labeled_by": str(row.labeled_by) if row.labeled_by else None,
                "labeled_at": row.labeled_at.isoformat() if row.labeled_at else None,
            }
        )
    return grouped


def _render(row: MonitoringCitation, labels: list[dict], hints: list[str]) -> dict:
    return {
        "citation_id": str(row.id),
        "title": row.title,
        "excerpt": (row.snippet or "").strip() or None,
        "url": row.raw_url,
        "domain": row.domain,
        "page_type": row.page_type.value if row.page_type else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "labels": labels,
        "label_count": len(labels),
        "hints": hints,
    }


def sampling_queue(
    db: Session,
    project_id: uuid.UUID,
    *,
    round_no: int = 1,
    size: int = DEFAULT_SIZE,
    scope: str = "brand_related",
    risk_scan: bool = True,
) -> dict:
    brand_only = scope != "all"
    rows = _scan_rows(db, project_id, brand_related_only=brand_only)
    widened = False
    # 品牌相关样本不够时放宽到全部已复核引用，但必须在返回体里说清楚
    if brand_only and len(rows) < max(size, 5):
        rows = _scan_rows(db, project_id, brand_related_only=False)
        widened = True

    pool_ids = [row.id for row in rows]
    labels = _labels_map(db, project_id, pool_ids)

    ordered = sorted(rows, key=lambda row: _rank_key(round_no, row.id))
    sample_rows = ordered[:size]

    queue = []
    for row in sample_rows:
        hints = _hints(row)
        queue.append(_render(row, labels.get(row.id, []), hints))

    risk_rows: list[dict] = []
    if risk_scan:
        scored = sorted(
            (row for row in rows if row.id not in {item.id for item in sample_rows}),
            key=lambda row: (-len(_hints(row)), _rank_key(round_no, row.id)),
        )
        for row in scored[:RISK_SAMPLE]:
            hints = _hints(row)
            if not hints:
                break
            risk_rows.append(_render(row, labels.get(row.id, []), hints))

    return {
        "round_no": round_no,
        "size": size,
        "scope": "all" if (scope == "all" or widened) else "brand_related",
        "widened": widened,
        "pool": len(rows),
        "sample": queue,
        "risk_scan": risk_rows,
        "notes": [
            "抽样按「轮次 + 引用 id」哈希排序，规则固定，任何人重跑都得到同一批。",
            "双人独立标注，分歧留待第三次标注或人工仲裁，不自动合并。",
            "risk_scan 只用于排查负面，命中词不产生任何比率。",
            "品牌相关样本不足时放宽到全部已复核引用，并在 widened 标记。",
        ],
    }


def _hints(row: MonitoringCitation) -> list[str]:
    haystack = " ".join(part for part in (row.title, row.snippet) if part)
    if not haystack:
        return []
    return [word for word in NEGATIVE_HINTS if word in haystack]


def consensus(
    db: Session,
    project_id: uuid.UUID,
    *,
    round_no: int = 1,
    size: int = DEFAULT_SIZE,
    scope: str = "brand_related",
) -> dict:
    queue = sampling_queue(db, project_id, round_no=round_no, size=size, scope=scope, risk_scan=False)
    rows = {item["citation_id"]: item for item in queue["sample"]}

    decided: list[dict] = []
    disputed: list[dict] = []
    unlabeled: list[dict] = []
    for citation_id, item in rows.items():
        polarities = {label["polarity"] for label in item["labels"]}
        if not polarities:
            unlabeled.append(item)
            continue
        if len(polarities) == 1 and len(item["labels"]) >= 2:
            decided.append({**item, "consensus": polarities.pop()})
        elif len(polarities) == 1:
            decided.append({**item, "consensus": polarities.pop(), "single_label": True})
        else:
            disputed.append(item)

    counts = {polarity.value: 0 for polarity in SentimentPolarity}
    for item in decided:
        counts[item["consensus"]] = counts.get(item["consensus"], 0) + 1

    consensus_total = len(decided)
    reportable = consensus_total >= MIN_REPORT
    positive_rate = (
        round(counts.get("positive", 0) / consensus_total, 4) if reportable and consensus_total else None
    )
    return {
        "round_no": round_no,
        "size": size,
        "scope": queue["scope"],
        "widened": queue["widened"],
        "sampled": len(rows),
        "consensus_total": consensus_total,
        "counts": counts,
        "disputed": len(disputed),
        "unlabeled": len(unlabeled),
        "min_report": MIN_REPORT,
        "reportable": reportable,
        "positive_rate": positive_rate,
        "disputed_items": disputed[:10],
        "notes": [
            f"共识样本不足 {MIN_REPORT} 条时不出正向率，只报条数（当前 {consensus_total} 条）。",
            "共识 = 至少两个标注人给出相同档位；分歧条目列在 disputed，等人仲裁。",
            "该比率只代表抽样所见，不外推为全量正向率。",
        ],
    }
