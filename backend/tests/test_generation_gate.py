"""批次级生成闸门回归：体检、小样打分、人工签核、规模达线才拦。

口径：闸门只决定「要不要全量出稿」，不放宽发布审批；小批次（<20 篇）不过闸门。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import GenerationBatch, GenerationGateResult, GenerationItem
from app.models.enums import GenerationBatchStatus, GenerationItemStatus, RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _setup(project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"gate-{suffix}")
    editor = user_factory(f"gate-editor-{suffix}")
    reviewer = user_factory(f"gate-reviewer-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, reviewer, RoleCode.REVIEWER)
    return project, editor, reviewer


def _make_batch(db, project, *, total: int, facts: bool = True, brand: str = "测试品牌") -> GenerationBatch:
    batch = GenerationBatch(
        project_id=project.id,
        name="闸门批次",
        source="remediation",
        status=GenerationBatchStatus.QUEUED,
        total_items=total,
    )
    db.add(batch)
    db.flush()
    for index in range(total):
        brief = {
            "source": "remediation",
            "citation_id": str(uuid.uuid4()),
            "brand": brand,
            "facts": [{"key": "课程周期", "value": "6 个月"}, {"key": "授课方式", "value": "线上直播"}] if facts else [],
            "official_urls": ["https://www.gdccai.com"],
            "guidance": "只做事实补充与澄清",
        }
        db.add(
            GenerationItem(
                project_id=project.id,
                batch_id=batch.id,
                title=f"纠正稿样本 {index + 1}",
                brief=brief,
                status=GenerationItemStatus.PENDING,
                sort_order=index,
            )
        )
    db.commit()
    return batch


def test_precheck_records_blockers_without_facts(
    client, db, project_factory, user_factory, member_factory
):
    project, editor, _ = _setup(project_factory, user_factory, member_factory)
    batch = _make_batch(db, project, total=3, facts=True)

    passed = client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{batch.id}/precheck",
        headers=_auth(editor),
    )
    assert passed.status_code == 200, passed.text
    body = passed.json()["data"]
    assert body["passed"] is True
    assert body["blockers"] == []
    assert body["gate_type"] == "precheck"

    bare = _make_batch(db, project, total=2, facts=False)
    blocked = client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{bare.id}/precheck",
        headers=_auth(editor),
    )
    assert blocked.status_code == 200, blocked.text
    data = blocked.json()["data"]
    assert data["passed"] is False
    assert {item["code"] for item in data["blockers"]} >= {"facts_missing"}


def test_sample_review_drafts_samples_and_scores(
    client, db, project_factory, user_factory, member_factory
):
    project, editor, _ = _setup(project_factory, user_factory, member_factory)
    batch = _make_batch(db, project, total=4)

    reviewed = client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{batch.id}/sample-review",
        json={"sample_size": 2, "threshold": 0},
        headers=_auth(editor),
    )
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()["data"]
    assert body["gate_type"] == "sample_review"
    assert body["sample_size"] == 2
    assert body["passed"] is True
    assert len(body["metrics"]["items"]) == 2
    # 小样是真出稿：样本项转 drafted 且带正文
    items = list(db.scalars(select(GenerationItem).where(GenerationItem.batch_id == batch.id)))
    drafted = [item for item in items if item.status == GenerationItemStatus.DRAFTED]
    assert len(drafted) == 2
    assert all(item.draft_body for item in drafted)


def test_big_batch_needs_approval_before_full_run(
    client, db, project_factory, user_factory, member_factory
):
    project, editor, reviewer = _setup(project_factory, user_factory, member_factory)
    batch = _make_batch(db, project, total=20)

    blocked = client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{batch.id}/run",
        headers=_auth(editor),
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "generation_gate_required"

    # 未跑小样直接签核 → 拒
    early = client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{batch.id}/gate-approval",
        json={"note": "直接放行"},
        headers=_auth(reviewer),
    )
    assert early.status_code == 409, early.text
    assert early.json()["error"]["code"] == "gate_sample_missing"

    sample = client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{batch.id}/sample-review",
        json={"sample_size": 3, "threshold": 0},
        headers=_auth(editor),
    )
    assert sample.status_code == 200, sample.text

    approved = client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{batch.id}/gate-approval",
        json={"note": "样本可用"},
        headers=_auth(reviewer),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["gate_type"] == "approval"

    ran = client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{batch.id}/run",
        headers=_auth(editor),
    )
    assert ran.status_code == 200, ran.text
    items = list(db.scalars(select(GenerationItem).where(GenerationItem.batch_id == batch.id)))
    assert all(item.status == GenerationItemStatus.DRAFTED for item in items)


def test_small_batch_runs_without_gate(
    client, db, project_factory, user_factory, member_factory
):
    project, editor, _ = _setup(project_factory, user_factory, member_factory)
    batch = _make_batch(db, project, total=3)

    ran = client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{batch.id}/run",
        headers=_auth(editor),
    )
    assert ran.status_code == 200, ran.text
    gates = list(db.scalars(select(GenerationGateResult).where(GenerationGateResult.batch_id == batch.id)))
    assert gates == []


def test_sample_below_threshold_cannot_be_approved(
    client, db, project_factory, user_factory, member_factory
):
    project, editor, reviewer = _setup(project_factory, user_factory, member_factory)
    batch = _make_batch(db, project, total=20)

    sample = client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{batch.id}/sample-review",
        json={"sample_size": 2, "threshold": 100},
        headers=_auth(editor),
    )
    assert sample.status_code == 200, sample.text
    assert sample.json()["data"]["passed"] is False
    assert any(item["code"] == "sample_below_threshold" for item in sample.json()["data"]["blockers"])

    refused = client.post(
        f"/api/v1/projects/{project.id}/generation-batches/{batch.id}/gate-approval",
        json={"note": "勉强放行"},
        headers=_auth(reviewer),
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "gate_sample_failed"

    gates = client.get(
        f"/api/v1/projects/{project.id}/generation-batches/{batch.id}/gates",
        headers=_auth(editor),
    )
    assert gates.status_code == 200, gates.text
    types = [row["gate_type"] for row in gates.json()["data"]]
    assert types == ["sample_review"]
