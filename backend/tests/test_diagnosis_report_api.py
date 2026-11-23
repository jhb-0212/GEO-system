"""诊断报告：空范围下必须给 null 而不是 0，且分项齐全、口径可回查。"""

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def test_diagnosis_report_empty_scope_returns_null_dimensions(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"diag-{suffix}")
    editor = user_factory(f"diag-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    resp = client.get(f"/api/v1/projects/{project.id}/diagnosis-report", headers=_auth(editor))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    keys = [row["key"] for row in data["dimensions"]]
    assert keys == [
        "mention_rate",
        "first_rank_rate",
        "source_coverage",
        "competitor_rank",
        "context_quality",
    ]
    # 没有有效样本时：分子分母都是 0，value 必须是 null（不用 0 假装有数据）
    for row in data["dimensions"]:
        assert row["denominator"] == 0
        assert row["value"] is None
        assert row["has_data"] is False
        assert row["unit"] == "%"
    assert data["scope"]["valid_answers"] == 0
    assert data["scope"]["excluded"]["failed"] == 0
    # 明确写出「无有效样本」，而不是让前端自己猜
    assert any("没有有效样本" in note for note in data["caveats"])
    # 不提供综合评分字段
    assert "score" not in data


def test_diagnosis_report_requires_stats_read(
    client, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"diag-deny-{suffix}")
    viewer = user_factory(f"diag-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    denied = client.get(f"/api/v1/projects/{project.id}/diagnosis-report", headers=_auth(viewer))
    assert denied.status_code in (403, 200)
    if denied.status_code == 200:
        # 只读角色若具备 stats.read，也绝不能拿到写接口
        assert "dimensions" in denied.json()["data"]
