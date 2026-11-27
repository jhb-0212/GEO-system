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

from sqlalchemy import or_, select
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
        # 标题或摘要任一存在就能进入盲评；演示/手工样本常见只有摘要。
        or_(MonitoringCitation.title.is_not(None), MonitoringCitation.snippet.is_not(None)),
    )
    if brand_related_only:
        stmt = stmt.where(MonitoringCitation.is_brand_related.is_(True))
    return list(db.scalars(stmt))


def _label_rows(db: Session, project_id: uuid.UUID, citation_ids: list[uuid.UUID] | None):
    stmt = select(SentimentLabel).where(SentimentLabel.project_id == project_id)
    if citation_ids is not None:
        if not citation_ids:
            return []
        stmt = stmt.where(SentimentLabel.citation_id.in_(citation_ids))
    return list(db.scalars(stmt))


def _labels_map(db: Session, project_id: uuid.UUID, citation_ids: list[uuid.UUID] | None):
    rows = _label_rows(db, project_id, citation_ids)
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


def _labeler_key(label: dict) -> str:
    # labeled_by 为空的历史数据统一算同一个「未知标注人」，不能当成两个人
    return str(label.get("labeled_by") or "unknown")


def consensus_state(labels: list[dict]) -> tuple[str, list[str]]:
    """单条引用的共识状态。至少两个**不同**标注人给同一档位才算共识。

    - `unlabeled`：还没有标注
    - `pending_second`：只有一名标注人（或历史未知标注人），等第二人
    - `disputed`：标注人之间档位不一致，等人工仲裁
    - 其余返回具体的 polarity 值（`positive`/`neutral`/`negative`）
    """
    if not labels:
        return "unlabeled", []
    polarities = {label["polarity"] for label in labels}
    labelers = sorted({_labeler_key(label) for label in labels})
    if len(polarities) > 1:
        return "disputed", labelers
    if len(labelers) < 2:
        return "pending_second", labelers
    return next(iter(polarities)), labelers


def citation_consensus(
    db: Session, project_id: uuid.UUID, citation_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, dict]:
    """统一的共识事实源：纠正稿、情绪页、验收口径都从这里取，避免各写一套。

    `citation_ids=None` 时返回项目下所有已有标注的引用；传了 id 列表时，未标注的
    引用也会返回，状态为 `unlabeled`。
    """
    labels_map = _labels_map(db, project_id, citation_ids)
    ids = list(citation_ids) if citation_ids is not None else list(labels_map)
    result: dict[uuid.UUID, dict] = {}
    for citation_id in ids:
        labels = labels_map.get(citation_id, [])
        state, labelers = consensus_state(labels)
        latest = max(labels, key=lambda item: item["labeled_at"] or "") if labels else None
        result[citation_id] = {
            "state": state,
            "labelers": labelers,
            "labels": labels,
            "latest": latest,
        }
    return result


def _visible_labels(labels: list[dict], viewer_id: uuid.UUID | None) -> list[dict]:
    """盲评隔离：登录用户只能看到自己提交的标注。

    `viewer_id=None` 仅限服务端内部共识计算；任何 API 返回都必须传当前用户。
    """
    if viewer_id is None:
        return labels
    key = str(viewer_id)
    return [label for label in labels if _labeler_key(label) == key]


def _render(
    row: MonitoringCitation,
    labels: list[dict],
    hints: list[str],
    *,
    viewer_id: uuid.UUID | None = None,
) -> dict:
    state, labelers = consensus_state(labels)
    visible = _visible_labels(labels, viewer_id)
    decided = state in {polarity.value for polarity in SentimentPolarity}
    return {
        "citation_id": str(row.id),
        "title": row.title,
        "excerpt": (row.snippet or "").strip() or None,
        "url": row.raw_url,
        "domain": row.domain,
        "page_type": row.page_type.value if row.page_type else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "labels": visible,
        "label_count": len(labels),
        "my_label_count": len(visible),
        "state": state,
        "consensus": state if decided else None,
        # 盲评期间不暴露任何其他人的 ID；两人都提交后才由 state/consensus 给出结论。
        "labelers": [] if viewer_id is not None else labelers,
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
    viewer_id: uuid.UUID | None = None,
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
        queue.append(_render(row, labels.get(row.id, []), hints, viewer_id=viewer_id))

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
            risk_rows.append(_render(row, labels.get(row.id, []), hints, viewer_id=viewer_id))

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
    """单轮共识：看这一轮抽样的标注情况。"""
    return _consensus_for_rounds(
        db, project_id, rounds=[round_no], size=size, scope=scope, round_no=round_no
    )


def cumulative_consensus(
    db: Session,
    project_id: uuid.UUID,
    *,
    size: int = DEFAULT_SIZE,
    scope: str = "brand_related",
    max_rounds: int = 12,
    min_report: int | None = None,
) -> dict:
    """跨轮累计共识：每轮抽 12 条、要攒 50 条共识，单轮永远不够。

    把第 1..N 轮的抽样批并起来算：同一引用在不同轮被重复抽中只计一次。
    """
    return _consensus_for_rounds(
        db,
        project_id,
        rounds=range(1, max_rounds + 1),
        size=size,
        scope=scope,
        round_no=max_rounds,
        cumulative=True,
        min_report=min_report,
    )


def _consensus_for_rounds(
    db: Session,
    project_id: uuid.UUID,
    *,
    rounds,
    size: int,
    scope: str,
    round_no: int,
    cumulative: bool = False,
    min_report: int | None = None,
) -> dict:
    merged: dict[str, dict] = {}
    widened = False
    for one_round in rounds:
        queue = sampling_queue(db, project_id, round_no=one_round, size=size, scope=scope, risk_scan=False)
        widened = widened or queue["widened"]
        for item in queue["sample"]:
            merged.setdefault(item["citation_id"], item)
    rows = merged

    decided: list[dict] = []
    disputed: list[dict] = []
    unlabeled: list[dict] = []
    pending_second: list[dict] = []
    for citation_id, item in rows.items():
        state, _ = consensus_state(item["labels"])
        if state == "unlabeled":
            unlabeled.append(item)
        elif state == "pending_second":
            # 单人标注不算共识：必须等第二个不同标注人，否则验收数字由一个人决定
            pending_second.append(item)
        elif state == "disputed":
            disputed.append(item)
        else:
            decided.append({**item, "consensus": state})

    counts = {polarity.value: 0 for polarity in SentimentPolarity}
    for item in decided:
        counts[item["consensus"]] = counts.get(item["consensus"], 0) + 1

    consensus_total = len(decided)
    threshold = MIN_REPORT if min_report is None else int(min_report)
    reportable = consensus_total >= threshold
    positive_rate = (
        round(counts.get("positive", 0) / consensus_total, 4) if reportable and consensus_total else None
    )
    return {
        "round_no": round_no,
        "cumulative": cumulative,
        "rounds": list(rounds)[-1] if rounds else 0,
        "size": size,
        "scope": scope,
        "widened": widened,
        "sampled": len(rows),
        "consensus_total": consensus_total,
        "counts": counts,
        "disputed": len(disputed),
        "unlabeled": len(unlabeled),
        "pending_second": len(pending_second),
        "min_report": threshold,
        "reportable": reportable,
        "positive_rate": positive_rate,
        # 分歧条目只给引用与状态，不回传任何一方的 polarity/note/labeled_by；
        # 否则任何登录用户都能通过 /consensus 看到另一个标注人的判断。
        "disputed_items": [
            {
                **{k: v for k, v in item.items() if k not in {"labels", "labelers", "latest"}},
                "state": "disputed",
                "consensus": None,
                "labels": [],
                "labelers": [],
            }
            for item in disputed[:10]
        ],
        "notes": [
            f"共识样本不足 {threshold} 条时不出正向率，只报条数（当前 {consensus_total} 条）。",
            "单人标注只计入 pending_second，不进共识；必须两人同档。",
            "共识 = 至少两名不同标注人给出相同档位；分歧条目列在 disputed，等人仲裁。",
            "该比率只代表抽样所见，不外推为全量正向率。",
        ],
    }
