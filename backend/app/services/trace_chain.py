"""跨域 trace 串接：内容版本引用的监测证据 → 发布任务。

只做“唯一 trace 才继承”：一个内容版本可能同时引用多个样本/多个 trace，
这时返回 None，不能随便挑一条冒充完整链路。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContentVersionCitation, MonitoringCitation


def trace_for_content_version(db: Session, version_id: uuid.UUID) -> str | None:
    rows = db.scalars(
        select(MonitoringCitation.trace_id)
        .join(
            ContentVersionCitation,
            ContentVersionCitation.citation_id == MonitoringCitation.id,
        )
        .where(
            ContentVersionCitation.version_id == version_id,
            MonitoringCitation.trace_id.is_not(None),
        )
    ).all()
    traces = {trace for trace in rows if trace}
    return next(iter(traces)) if len(traces) == 1 else None
