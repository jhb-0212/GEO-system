"""只处理引用来源分类（`citation_source_reviews` / `source_category`）。

注意：本脚本**不写 citation.channel_id**。渠道归属只认发布回执里的真实 URL，
由 `backfill_citation_channels.py` 处理；按来源域名回填会把整站算成我们的渠道成果。
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import CitationSourceReview, MonitoringCitation, Project, User
from app.models.enums import ClassificationSource, SourceReviewStatus
from app.services.audit import record_audit
from app.services.citation_classification import CLASSIFIER_VERSION

PROJECT_ID = uuid.UUID("154640d4-6356-4a1c-8bde-2d511cfb06cd")


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
        if not project or not actor:
            raise SystemExit("项目或执行人不存在")

        reviews = db.scalars(
            select(CitationSourceReview).where(
                CitationSourceReview.project_id == PROJECT_ID,
                CitationSourceReview.status == SourceReviewStatus.PENDING,
                CitationSourceReview.suggested_source_category.is_not(None),
                CitationSourceReview.suggested_source_category != "other",
            )
        ).all()
        preview = []
        now = datetime.now(timezone.utc)
        for review in reviews:
            category = review.suggested_source_category
            preview.append(
                {
                    "review_id": str(review.id),
                    "domain": review.domain,
                    "source_category": getattr(category, "value", str(category)),
                }
            )
            if args.apply:
                review.status = SourceReviewStatus.CLASSIFIED
                review.source_category = category
                review.classification_source = ClassificationSource.MANUAL
                review.classification_rule_version = CLASSIFIER_VERSION
                review.reviewed_by = actor.id
                review.reviewed_at = now
                review.review_note = (
                    "按系统高置信建议批量确认；仅确认非 other 类别，"
                    "other 保留待人工逐项判断。"
                )

        if args.apply and reviews:
            db.flush()
            for review in reviews:
                db.execute(
                    MonitoringCitation.__table__.update()
                    .where(
                        MonitoringCitation.project_id == PROJECT_ID,
                        MonitoringCitation.domain == review.domain,
                    )
                    .values(
                        source_category=review.suggested_source_category,
                        classification_source=ClassificationSource.MANUAL,
                        classification_rule_version=CLASSIFIER_VERSION,
                    )
                )
            record_audit(
                db,
                project_id=PROJECT_ID,
                actor_id=actor.id,
                action="citation.source_classify_bulk",
                target_type="citation_source_review",
                target_id=None,
                payload={
                    "count": len(reviews),
                    "domains": [row["domain"] for row in preview],
                    "note": "仅确认高置信建议；other 保持 pending；不写 channel_id",
                },
            )
            db.commit()

        after_reviews = {
            getattr(status, "value", str(status)): int(count)
            for status, count in db.execute(
                select(CitationSourceReview.status, func.count())
                .where(CitationSourceReview.project_id == PROJECT_ID)
                .group_by(CitationSourceReview.status)
            ).all()
        }
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "source_backfill_count": len(reviews),
                    "preview": preview[:10],
                    "after_source_reviews": after_reviews,
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
