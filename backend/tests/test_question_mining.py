"""问题候选池：挖掘、导入、去重、人工采纳/驳回与权限边界。"""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.errors import ConflictError
from app.core.security import create_access_token
from app.models import BrandProfile, CompanyProfile, Question, QuestionCandidate, QuestionVersion
from app.models.enums import (
    QuestionCandidateBucket,
    QuestionCandidateStatus,
    QuestionType,
    RoleCode,
)
from app.services.question_mining import (
    accept_candidate,
    import_candidates,
    mine_candidates,
    reject_candidate,
)


def _auth(user) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"
    }


def _seed_context(db, project, *, brand_name="成才AI"):
    db.add(
        CompanyProfile(
            project_id=project.id,
            legal_name="广州成才人工智能培训有限公司",
            brand_name=brand_name,
            province="广东",
            industries=["人工智能培训", "AIGC内容制作"],
            regions=["广州", "深圳"],
            products=[{"name": "AIGC漫剧实训"}, {"name": "GEO搜索优化课程"}],
        )
    )
    db.add(BrandProfile(project_id=project.id, canonical_name=brand_name, aliases=[]))
    db.flush()


def _question_count(db, project) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(Question).where(Question.project_id == project.id)
        )
        or 0
    )


def test_mine_creates_pending_candidates_and_is_idempotent(
    db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"mine-{suffix}")
    editor = user_factory(f"mine-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    _seed_context(db, project)

    first = mine_candidates(
        db, project_id=project.id, actor_id=editor.id, limit=20
    )

    assert first["created_count"] > 0
    assert first["missing_context"] == []
    assert _question_count(db, project) == 0
    rows = db.scalars(
        select(QuestionCandidate).where(QuestionCandidate.project_id == project.id)
    ).all()
    assert rows
    assert all(row.status == QuestionCandidateStatus.PENDING for row in rows)
    assert {row.bucket for row in rows} == {
        QuestionCandidateBucket.CATEGORY,
        QuestionCandidateBucket.PURCHASE,
        QuestionCandidateBucket.REPUTATION,
    }
    assert any("成才AI怎么样" in row.text for row in rows)
    assert any("AIGC漫剧实训怎么选" in row.text for row in rows)

    second = mine_candidates(
        db, project_id=project.id, actor_id=editor.id, limit=20
    )
    assert second["created_count"] == 0
    assert second["skipped_count"] > 0


def test_accept_creates_draft_question_and_cannot_repeat(
    db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"accept-{suffix}")
    editor = user_factory(f"accept-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    _seed_context(db, project)
    mine_candidates(db, project_id=project.id, actor_id=editor.id, limit=20)
    candidate = db.scalar(
        select(QuestionCandidate)
        .where(
            QuestionCandidate.project_id == project.id,
            QuestionCandidate.bucket == QuestionCandidateBucket.REPUTATION,
        )
        .order_by(QuestionCandidate.priority, QuestionCandidate.created_at)
    )
    assert candidate is not None

    result = accept_candidate(
        db,
        project_id=project.id,
        candidate_id=candidate.id,
        actor_id=editor.id,
    )

    assert result["question_code"].startswith("Q")
    assert candidate.status == QuestionCandidateStatus.ACCEPTED
    assert candidate.converted_question_id == result["question_id"]
    question = db.get(Question, result["question_id"])
    version = db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.project_id == project.id,
            QuestionVersion.question_id == result["question_id"],
        )
    )
    assert question is not None and question.status.value == "draft"
    assert question.question_type == QuestionType.BRAND
    assert version is not None and version.text == candidate.text
    assert _question_count(db, project) == 1

    with pytest.raises(ConflictError, match="已处理"):
        accept_candidate(
            db,
            project_id=project.id,
            candidate_id=candidate.id,
            actor_id=editor.id,
        )


def test_import_dedupes_within_payload_and_marks_brand_questions(
    db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"import-{suffix}")
    editor = user_factory(f"import-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    _seed_context(db, project)

    result = import_candidates(
        db,
        project_id=project.id,
        actor_id=editor.id,
        texts=[
            "成才AI 学费多少？",
            "成才AI   学费多少？",
            "人工智能培训哪家好？",
        ],
        bucket=QuestionCandidateBucket.PURCHASE,
    )

    assert result["created_count"] == 2
    assert result["skipped_count"] == 1
    rows = db.scalars(
        select(QuestionCandidate)
        .where(QuestionCandidate.project_id == project.id)
        .order_by(QuestionCandidate.text)
    ).all()
    assert len(rows) == 2
    assert all(row.source.value == "import" for row in rows)
    assert any(row.question_type == QuestionType.BRAND for row in rows)


def test_reject_keeps_question_bank_unchanged(
    db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"reject-{suffix}")
    editor = user_factory(f"reject-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    import_candidates(
        db,
        project_id=project.id,
        actor_id=editor.id,
        texts=["人工智能培训怎么选？"],
        bucket=QuestionCandidateBucket.PURCHASE,
    )
    candidate = db.scalar(
        select(QuestionCandidate).where(QuestionCandidate.project_id == project.id)
    )
    reject_candidate(
        db,
        project_id=project.id,
        candidate_id=candidate.id,
        actor_id=editor.id,
    )

    assert candidate.status == QuestionCandidateStatus.REJECTED
    assert candidate.converted_question_id is None
    assert _question_count(db, project) == 0


def test_candidate_api_list_mine_and_accept(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"candidate-api-{suffix}")
    editor = user_factory(f"candidate-api-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    _seed_context(db, project)

    mined = client.post(
        f"/api/v1/projects/{project.id}/question-candidates/mine",
        json={"limit": 10, "buckets": ["reputation"]},
        headers=_auth(editor),
    )
    assert mined.status_code == 200, mined.text
    assert mined.json()["data"]["created_count"] > 0

    listed = client.get(
        f"/api/v1/projects/{project.id}/question-candidates?status=pending&bucket=reputation",
        headers=_auth(editor),
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]
    assert len(rows) == mined.json()["data"]["created_count"]

    accepted = client.post(
        f"/api/v1/projects/{project.id}/question-candidates/{rows[0]['id']}/accept",
        headers=_auth(editor),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["question_code"].startswith("Q")


def test_read_only_member_cannot_mine_candidates(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"candidate-ro-{suffix}")
    viewer = user_factory(f"candidate-ro-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)

    resp = client.post(
        f"/api/v1/projects/{project.id}/question-candidates/mine",
        json={"limit": 10},
        headers=_auth(viewer),
    )
    assert resp.status_code == 403, resp.text
