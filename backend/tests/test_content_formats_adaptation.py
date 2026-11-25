"""内容形式覆盖与行业适配四问：只统计/建议，不改评分与准入。"""

import uuid

from app.models import ContentItem, ContentVersion
from app.models.enums import ContentFormat, ContentKind, ContentStatus
from app.services.adaptation import adaptation_report, save_adaptation
from app.services.content_formats import content_format_report


def _master(db, project, content_type=None, with_version=True):
    item = ContentItem(
        project_id=project.id,
        kind=ContentKind.MASTER,
        content_type=content_type,
        title=f"形式稿-{uuid.uuid4().hex[:6]}",
        status=ContentStatus.DRAFT,
    )
    db.add(item)
    db.flush()
    if with_version:
        version = ContentVersion(
            project_id=project.id,
            item_id=item.id,
            version_no=1,
            body="正文",
            content_hash=uuid.uuid4().hex.ljust(64, "0"),
            status=ContentStatus.DRAFT,
        )
        db.add(version)
        db.flush()
        item.current_version_id = version.id
        db.flush()
    return item


def test_content_format_report_counts_masters_and_unclassified(db, project_factory):
    project = project_factory(f"formats-{uuid.uuid4().hex[:6]}")
    _master(db, project, ContentFormat.FAQ)
    _master(db, project, ContentFormat.FAQ)
    _master(db, project, ContentFormat.CASE_STUDY)
    _master(db, project, None)
    db.commit()

    report = content_format_report(db, project.id)
    by_type = {row["content_type"]: row for row in report["formats"]}
    assert by_type["faq"]["master_items"] == 2
    assert by_type["case_study"]["master_items"] == 1
    assert by_type[None]["master_items"] == 1
    assert report["summary"]["master_items"] == 4
    assert report["summary"]["master_without_format"] == 1
    assert report["summary"]["citation_coverage"] == 0.0


def test_adaptation_defaults_to_insufficient_and_saves_verdict(db, project_factory):
    project = project_factory(f"adapt-{uuid.uuid4().hex[:6]}")
    before = adaptation_report(db, project.id)
    assert before["evaluated"] is False
    assert before["verdict"] == "insufficient"
    assert before["score"] is None

    result = save_adaptation(
        db, project.id,
        {"ai_demand": "yes", "comparison": "yes", "fragmented_info": "yes", "conversion": "yes"},
        note="本地婚纱摄影",
    )
    assert result["score"] == 8
    assert result["verdict"] == "prioritize"
    assert result["note"] == "本地婚纱摄影"

    partial = save_adaptation(
        db, project.id,
        {"ai_demand": "yes", "comparison": "yes", "fragmented_info": "unknown", "conversion": "no"},
        note=None,
    )
    assert partial["evaluated_count"] == 3
    assert partial["verdict"] == "pilot"
