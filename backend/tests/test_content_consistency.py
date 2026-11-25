"""跨渠道一致性：电话、金额、地址只报差异，不自动改稿。"""

import uuid

from app.models import ContentItem, ContentVersion, Fact
from app.models.enums import ContentKind, ContentStatus, FactStatus, FactType
from app.services.content_consistency import consistency_report


def _content(db, project, body, status=ContentStatus.APPROVED):
    item = ContentItem(
        project_id=project.id,
        kind=ContentKind.MASTER,
        title=f"一致性稿-{uuid.uuid4().hex[:6]}",
        status=status,
    )
    db.add(item)
    db.flush()
    version = ContentVersion(
        project_id=project.id,
        item_id=item.id,
        version_no=1,
        body=body,
        content_hash=uuid.uuid4().hex.ljust(64, "0"),
        status=status,
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    db.flush()
    return item, version


def _facts(db, project):
    for fact_type, key, value in [
        (FactType.CONTACT, "business_phone", "020-88888888"),
        (FactType.COURSE_FEE, "course_fee", "3980元"),
        (FactType.BASE_ADDRESS, "base_address", "广州市天河区体育西路"),
    ]:
        db.add(Fact(
            project_id=project.id,
            fact_type=fact_type,
            fact_key=key,
            fact_value=value,
            approval_status=FactStatus.APPROVED,
        ))
    db.flush()


def test_consistency_reports_phone_fee_and_address_differences(db, project_factory):
    project = project_factory(f"consistent-{uuid.uuid4().hex[:6]}")
    _facts(db, project)
    _content(db, project, "课程价格 4980 元，联系电话 020-77777777，地址在深圳市南山区科技园。")
    db.commit()

    report = consistency_report(db, project.id)
    codes = {row["code"] for row in report["fact_conflicts"]}
    assert {"contact_mismatch", "fee_mismatch", "address_unverified"} <= codes
    assert report["summary"]["contents_scanned"] == 1
    assert report["summary"]["approved_facts"] == 3


def test_consistency_accepts_values_that_match_approved_facts(db, project_factory):
    project = project_factory(f"consistent-ok-{uuid.uuid4().hex[:6]}")
    _facts(db, project)
    _content(db, project, "课程价格 3980 元，联系电话 020-88888888，地址在广州市天河区体育西路。")
    db.commit()

    report = consistency_report(db, project.id)
    assert report["fact_conflicts"] == []
    assert report["summary"]["contents_scanned"] == 1


def test_consistency_ignores_drafts_and_unlinked_status(db, project_factory):
    project = project_factory(f"consistent-draft-{uuid.uuid4().hex[:6]}")
    _facts(db, project)
    _content(db, project, "课程价格 4980 元，联系电话 020-77777777。", status=ContentStatus.DRAFT)
    db.commit()

    report = consistency_report(db, project.id)
    assert report["summary"]["contents_scanned"] == 0
    assert report["fact_conflicts"] == []
