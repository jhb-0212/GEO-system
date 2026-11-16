"""B2/B3 边界补测。

补的是 `test_question_keyword_api.py` 现有 4 个复合用例没有断言到的边界，
不动那里的既有覆盖（content_version_count / 审计动作 / 版本正文往返）。
"""

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _create_question(client, project, user, *, code: str, status: str | None = None):
    suffix = uuid.uuid4().hex[:6]
    created = client.post(
        f"/api/v1/projects/{project.id}/questions",
        json={
            "code": code,
            "title": f"边界题-{suffix}",
            "question_type": "general",
            "text": f"边界问法-{suffix}",
        },
        headers=_auth(user),
    )
    assert created.status_code == 201, created.text
    question_id = created.json()["data"]["id"]
    if status is not None:
        patched = client.patch(
            f"/api/v1/projects/{project.id}/questions/{question_id}",
            json={"status": status},
            headers=_auth(user),
        )
        assert patched.status_code == 200, patched.text
    return question_id


def test_create_question_without_text_returns_422(
    client, project_factory, user_factory, member_factory
):
    """缺 text → 422，且走统一错误信封（code=validation_error，不是 detail 数组）。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"e1-{suffix}")
    editor = user_factory(f"e1-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    resp = client.post(
        f"/api/v1/projects/{project.id}/questions",
        json={"code": f"E1-{suffix}", "title": "缺正文", "question_type": "general"},
        headers=_auth(editor),
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "validation_error"


def test_draft_to_archived_transition_rejected(
    client, project_factory, user_factory, member_factory
):
    """draft 不能直接跳 archived（DRAFT 只允许 → ACTIVE）。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"e2-{suffix}")
    editor = user_factory(f"e2-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    question_id = _create_question(client, project, editor, code=f"E2-{suffix}")

    resp = client.patch(
        f"/api/v1/projects/{project.id}/questions/{question_id}",
        json={"status": "archived"},
        headers=_auth(editor),
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "question_status_conflict"


def test_keyword_reviewer_cannot_write(
    client, project_factory, user_factory, member_factory
):
    """reviewer 持 question.read 但不持 question.write：可读关键词、不可写。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"e3-{suffix}")
    reviewer = user_factory(f"e3-reviewer-{suffix}")
    member_factory(project, reviewer, RoleCode.REVIEWER)

    read = client.get(f"/api/v1/projects/{project.id}/keywords", headers=_auth(reviewer))
    assert read.status_code == 200, read.text

    write = client.post(
        f"/api/v1/projects/{project.id}/keywords",
        json={"name": f"reviewer-{suffix}"},
        headers=_auth(reviewer),
    )
    assert write.status_code == 403, write.text
    assert write.json()["error"]["code"] == "insufficient_permission"


def test_list_questions_filters_by_status_and_sorts_by_code(
    client, project_factory, user_factory, member_factory
):
    """status 筛选 + code 升序（插入顺序故意打乱，确保不是靠插入顺序蒙对）。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"e4-{suffix}")
    editor = user_factory(f"e4-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    code_b = f"QA-B-{suffix}"
    code_a = f"QA-A-{suffix}"
    code_c = f"QA-C-{suffix}"
    # 故意按 C → A → B 插入：若接口漏了 ORDER BY，active 集合会按插入顺序返回 [C, B]，与期望的 [B, C] 不符
    _create_question(client, project, editor, code=code_c, status="active")
    _create_question(client, project, editor, code=code_a)
    _create_question(client, project, editor, code=code_b, status="active")

    active = client.get(
        f"/api/v1/projects/{project.id}/questions",
        params={"status": "active"},
        headers=_auth(editor),
    )
    assert active.status_code == 200, active.text
    assert active.json()["meta"]["total"] == 2
    assert [row["code"] for row in active.json()["data"]] == [code_b, code_c]

    draft = client.get(
        f"/api/v1/projects/{project.id}/questions",
        params={"status": "draft"},
        headers=_auth(editor),
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["meta"]["total"] == 1
    assert [row["code"] for row in draft.json()["data"]] == [code_a]


def test_list_keywords_filters_and_sorts_by_name(
    client, project_factory, user_factory, member_factory
):
    """category / is_active 筛选 + name 升序。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"e5-{suffix}")
    editor = user_factory(f"e5-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    def _create(name: str, category: str) -> str:
        resp = client.post(
            f"/api/v1/projects/{project.id}/keywords",
            json={"name": name, "category": category},
            headers=_auth(editor),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["data"]["id"]

    name_a = f"kw-a-{suffix}"
    name_b = f"kw-b-{suffix}"
    name_c = f"kw-c-{suffix}"
    name_e = f"kw-e-{suffix}"
    _create(name_c, "品牌")
    _create(name_a, "品牌")
    _create(name_e, "竞品")
    deleted_id = _create(name_b, "品牌")

    deleted = client.delete(
        f"/api/v1/projects/{project.id}/keywords/{deleted_id}", headers=_auth(editor)
    )
    assert deleted.status_code == 200, deleted.text

    brand_active = client.get(
        f"/api/v1/projects/{project.id}/keywords",
        params={"category": "品牌", "is_active": "true"},
        headers=_auth(editor),
    )
    assert brand_active.status_code == 200, brand_active.text
    assert brand_active.json()["meta"]["total"] == 2
    assert [row["name"] for row in brand_active.json()["data"]] == [name_a, name_c]

    inactive = client.get(
        f"/api/v1/projects/{project.id}/keywords",
        params={"is_active": "false"},
        headers=_auth(editor),
    )
    assert inactive.status_code == 200, inactive.text
    assert inactive.json()["meta"]["total"] == 1
    assert [row["name"] for row in inactive.json()["data"]] == [name_b]

    competitor = client.get(
        f"/api/v1/projects/{project.id}/keywords",
        params={"category": "竞品"},
        headers=_auth(editor),
    )
    assert competitor.status_code == 200, competitor.text
    assert competitor.json()["meta"]["total"] == 1
    assert [row["name"] for row in competitor.json()["data"]] == [name_e]


def test_rename_keyword_conflicts_on_duplicate_name(
    client, project_factory, user_factory, member_factory
):
    """改名允许，但撞重名必须 409；改名成功后 name 生效、category 不受影响。"""
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"e6-{suffix}")
    editor = user_factory(f"e6-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    def _create(name: str) -> str:
        resp = client.post(
            f"/api/v1/projects/{project.id}/keywords",
            json={"name": name, "category": "品牌"},
            headers=_auth(editor),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["data"]["id"]

    first_name = f"kw-first-{suffix}"
    second_name = f"kw-second-{suffix}"
    first_id = _create(first_name)
    _create(second_name)

    conflict = client.patch(
        f"/api/v1/projects/{project.id}/keywords/{first_id}",
        json={"name": second_name},
        headers=_auth(editor),
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "keyword_name_conflict"

    renamed_to = f"kw-renamed-{suffix}"
    renamed = client.patch(
        f"/api/v1/projects/{project.id}/keywords/{first_id}",
        json={"name": renamed_to},
        headers=_auth(editor),
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["data"]["name"] == renamed_to
    assert renamed.json()["data"]["category"] == "品牌"
