"""发布回链看板与诊断报告导出：空数据下的口径与 CSV 形态。"""

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_publish_board_empty_project(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"board-{suffix}")
    editor = user_factory(f"board-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    resp = client.get(f"/api/v1/projects/{project.id}/publish-board", headers=_auth(editor))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["items"] == []
    summary = data["summary"]
    assert summary["total_receipts"] == 0
    # 没有回执时比率为 null，不用 0 假装「一篇都没被引用」
    assert summary["visibility_match_rate"] is None
    assert summary["cited_rate"] is None
    assert any("人工复核" in note for note in data["caveats"])


def test_publish_board_export_has_header_only(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"board-exp-{suffix}")
    editor = user_factory(f"board-exp-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    resp = client.get(f"/api/v1/projects/{project.id}/publish-board/export", headers=_auth(editor))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    lines = [line for line in resp.text.strip().splitlines() if line]
    assert len(lines) == 1
    assert "published_url" in lines[0] and "cited" in lines[0]


def test_diagnosis_export_keeps_null_as_blank(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"diag-exp-{suffix}")
    editor = user_factory(f"diag-exp-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    resp = client.get(f"/api/v1/projects/{project.id}/diagnosis-report/export", headers=_auth(editor))
    assert resp.status_code == 200, resp.text
    rows = [line.split(",") for line in resp.text.strip().splitlines()]
    assert rows[0][:5] == ["key", "label", "value_percent", "numerator", "denominator"]
    # 无样本时百分比留空，导出不写 0
    first = rows[1]
    assert first[0] == "mention_rate"
    assert first[2] == ""
    assert first[3] == "0" and first[4] == "0"
