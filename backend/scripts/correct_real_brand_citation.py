"""修正唯一一条真实品牌引用样本：知乎渠道稿引用 + 品牌可识别。

依据：样本 6c01c4b0 的 raw_answer 明确写“广东省AI数字人才就业实训基地（番禺）”
和“番禺番山创业中心”；citation 2c4054eb 的 manually confirmed 备注写明
“引用 URL 即已发布知乎渠道稿”。旧界面没有 is_brand_related 字段，导致两项漏记。
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import MonitoringCitation, MonitoringSample, Project, User
from app.models.enums import CitationReviewStatus
from app.services.audit import record_audit

PROJECT_ID = uuid.UUID("154640d4-6356-4a1c-8bde-2d511cfb06cd")
SAMPLE_ID = uuid.UUID("6c01c4b0-fc65-44df-9af3-1b05fee97fc6")
CITATION_ID = uuid.UUID("2c4054eb-20c1-4201-8ac1-8307c5d86b42")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        parser.error("必须指定 --dry-run 或 --apply")

    db = SessionLocal()
    try:
        project = db.get(Project, PROJECT_ID)
        actor = db.scalar(select(User).where(User.username == "geo_admin"))
        sample = db.get(MonitoringSample, SAMPLE_ID)
        citation = db.get(MonitoringCitation, CITATION_ID)
        if not project or not actor or not sample or not citation:
            raise SystemExit("项目、执行人、样本或引用不存在")
        if sample.project_id != PROJECT_ID or citation.project_id != PROJECT_ID:
            raise SystemExit("样本或引用不属于目标项目")
        before = {
            "sample_brand_identified": sample.brand_identified,
            "citation_brand_related": citation.is_brand_related,
            "citation_review_status": citation.review_status.value,
        }
        note = (
            (citation.review_note + "\n") if citation.review_note else ""
        ) + "2026-11-21 补记：该 URL 为已发布知乎渠道稿，品牌相关=是（旧界面无品牌字段导致漏记）。"
        if args.apply:
            sample.brand_identified = True
            sample.request_payload = {
                **(sample.request_payload or {}),
                "manual_correction": {
                    "field": "brand_identified",
                    "value": True,
                    "reason": "答案明确给出基地全称、番禺地址与番山创业中心",
                    "corrected_by": str(actor.id),
                    "corrected_at": datetime.now(timezone.utc).isoformat(),
                },
            }
            citation.is_brand_related = True
            citation.review_status = CitationReviewStatus.MANUAL_CONFIRMED
            citation.review_note = note
            db.flush()
            record_audit(
                db,
                project_id=PROJECT_ID,
                actor_id=actor.id,
                action="citation.brand_flag_correct",
                target_type="monitoring_citation",
                target_id=citation.id,
                payload={
                    "before": before,
                    "after": {
                        "sample_brand_identified": True,
                        "citation_brand_related": True,
                    },
                    "reason": "manual_brand_correction_after_schema_fix",
                },
            )
            db.commit()
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "before": before,
                    "after": {
                        "sample_brand_identified": sample.brand_identified,
                        "citation_brand_related": citation.is_brand_related,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
