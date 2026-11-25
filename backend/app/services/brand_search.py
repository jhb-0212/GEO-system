"""品牌搜索量：手工/CSV 导入后的快照与增量，不接外部指数 API。"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BrandSearchSnapshot, Project
from app.services.time_windows import calendar_window


def _parse_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValueError(f"日期格式应为 YYYY-MM-DD：{value}") from exc


def import_snapshots(
    db: Session,
    project_id: uuid.UUID,
    rows: list[dict],
    *,
    source: str = "csv",
    actor_id: uuid.UUID | None = None,
    apply: bool = True,
) -> dict:
    if not rows:
        raise ValueError("没有可导入的数据行")
    if len(rows) > 1000:
        raise ValueError("单次最多导入 1000 行")
    normalized = []
    errors = []
    for index, row in enumerate(rows, start=1):
        try:
            platform = str(row.get("platform") or "").strip().lower()
            if not platform or len(platform) > 32:
                raise ValueError("platform 必须是 1-32 个字符")
            snapshot_date = _parse_date(row.get("date") or row.get("snapshot_date"))
            raw_volume = row.get("search_volume")
            if isinstance(raw_volume, bool):
                raise ValueError("search_volume 必须是数字")
            volume = int(str(raw_volume).replace(",", "").strip())
            if volume < 0:
                raise ValueError("search_volume 不能为负数")
            normalized.append({
                "platform": platform,
                "snapshot_date": snapshot_date,
                "search_volume": volume,
                "note": str(row.get("note") or "")[:2000] or None,
            })
        except (TypeError, ValueError) as exc:
            errors.append({"row": index, "error": str(exc)})
    if errors:
        return {"imported": 0, "updated": 0, "errors": errors}
    imported = updated = 0
    if apply:
        for row in normalized:
            existing = db.scalar(
                select(BrandSearchSnapshot).where(
                    BrandSearchSnapshot.project_id == project_id,
                    BrandSearchSnapshot.platform == row["platform"],
                    BrandSearchSnapshot.snapshot_date == row["snapshot_date"],
                )
            )
            if existing is None:
                db.add(BrandSearchSnapshot(
                    project_id=project_id,
                    platform=row["platform"],
                    snapshot_date=row["snapshot_date"],
                    search_volume=row["search_volume"],
                    source=source,
                    note=row["note"],
                    created_by=actor_id,
                ))
                imported += 1
            else:
                existing.search_volume = row["search_volume"]
                existing.source = source
                existing.note = row["note"]
                updated += 1
        db.commit()
    return {"imported": imported, "updated": updated, "errors": []}


def brand_search_report(
    db: Session,
    project_id: uuid.UUID,
    *,
    days: int = 90,
    platform: str | None = None,
    now: datetime | None = None,
) -> dict:
    project = db.get(Project, project_id)
    start_date, end_date, _ = calendar_window(project, days, now=now)
    stmt = select(BrandSearchSnapshot).where(
        BrandSearchSnapshot.project_id == project_id,
        BrandSearchSnapshot.snapshot_date >= start_date,
        BrandSearchSnapshot.snapshot_date <= end_date,
    )
    if platform:
        stmt = stmt.where(BrandSearchSnapshot.platform == platform.strip().lower())
    rows = list(db.scalars(stmt.order_by(BrandSearchSnapshot.platform, BrandSearchSnapshot.snapshot_date)))

    grouped: dict[str, list[BrandSearchSnapshot]] = {}
    for row in rows:
        grouped.setdefault(row.platform, []).append(row)

    platforms = []
    for name, values in grouped.items():
        values.sort(key=lambda item: item.snapshot_date)
        latest = values[-1]
        previous = values[-2] if len(values) > 1 else None
        first = values[0]
        delta = latest.search_volume - previous.search_volume if previous else None
        delta_pct = (
            round(delta / previous.search_volume, 4)
            if previous and delta is not None and previous.search_volume else None
        )
        period_delta = latest.search_volume - first.search_volume if len(values) > 1 else None
        platforms.append({
            "platform": name,
            "points": len(values),
            "first_date": first.snapshot_date.isoformat(),
            "latest_date": latest.snapshot_date.isoformat(),
            "first_volume": first.search_volume,
            "latest_volume": latest.search_volume,
            "previous_volume": previous.search_volume if previous else None,
            "delta": delta,
            "delta_pct": delta_pct,
            "period_delta": period_delta,
            "series": [
                {"date": item.snapshot_date.isoformat(), "search_volume": item.search_volume}
                for item in values
            ],
        })
    platforms.sort(key=lambda item: item["latest_volume"], reverse=True)
    return {
        "window_days": max(days, 1),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "platforms": platforms,
        "notes": [
            "搜索量来自手工或 CSV 导入，不是指数平台实时接口。",
            "增量按同一平台相邻快照计算；不同平台不直接相加。",
        ],
    }
