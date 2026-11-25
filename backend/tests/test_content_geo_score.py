"""GEO 内容评分 v2：六个独立分项、无总分、失分项必须定位到段落。"""

import uuid

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models import AuditLog
from app.models.enums import RoleCode
from app.services.content_geo_score import score_content_geo

DIMENSION_LABELS = ["答案前置", "问题匹配", "实体完整", "证据密度", "结构可引用", "权威信号"]


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _score_kwargs(**overrides):
    body = overrides.pop("body", "\n\n".join([
        "广州基地的新任管理者训练营是一个 6 周企业内训项目，面向 50–500 人规模、正在扩张管理团队的企业。",
        "## 适合哪些企业？",
        "适合连锁零售、制造业和互联网公司。广州基地会先做需求访谈，再按行业定制课程。",
        "## 课程包含什么？",
        "- 目标管理：拆解团队季度目标；",
        "- 团队沟通：建立复盘机制；",
        "- 绩效复盘：形成改进清单。",
        "## 如何交付？",
        "第一步完成需求访谈；第二步定制课程；第三步驻场交付；第四步复盘评估。",
        "## 数据与案例",
        "据广州基地 2025 年服务报告，累计交付 320 场企业内训，覆盖 2.4 万名学员。来源：https://example.com/report",
        "## 报名方式",
        "广州基地位于广州市天河区，联系电话 020-88888888，官网 https://example.com 可预约试听。",
        "## 常见问题",
        "企业管理培训可以按行业定制，也可以先试听半天再决定。",
        "## 服务边界",
        "具体交付周期以需求访谈后的排期为准，不承诺任何平台推荐或排名结果。",
        "## 补充说明",
        "广州基地的课程研发团队按季度更新案例库，并把学员反馈纳入下一期课程设计。",
    ]))
    defaults = dict(
        title="广州基地新任管理者训练营：6 周企业内训方案",
        body=body,
        question_texts=["企业内训怎么做", "新任管理者培训哪家好", "企业管理培训包括什么"],
        keyword_names=["企业管理培训", "新任管理者", "企业内训"],
        citation_count=3,
        fact_links=[{"stale": False}, {"stale": False}, {"stale": False}],
        brand_terms=["广州基地"],
        product_terms=["新任管理者训练营", "销售团队陪跑"],
        context_terms=["广州", "企业管理培训"],
        identifier_terms=["020-88888888"],
        owned_domains=["example.com"],
    )
    defaults.update(overrides)
    return defaults


def test_geo_score_returns_six_named_dimensions_without_total():
    report = score_content_geo(**_score_kwargs())
    assert "score" not in report
    assert "grade" not in report
    assert [dim["label"] for dim in report["dimensions"]] == DIMENSION_LABELS
    assert len(report["dimensions"]) == 6
    assert all(0 <= dim["score"] <= 100 for dim in report["dimensions"])
    assert "不合成总分" in report["disclaimer"]


def test_every_low_dimension_locates_at_least_one_paragraph():
    report = score_content_geo(**_score_kwargs(
        title="培训",
        body="我们做培训。\n\n价格便宜，欢迎咨询。",
        question_texts=[],
        keyword_names=[],
        citation_count=0,
        fact_links=[],
        brand_terms=[],
        product_terms=[],
        context_terms=[],
        identifier_terms=[],
        owned_domains=[],
    ))
    assert report["attention_count"] >= 5
    for dim in report["dimensions"]:
        if dim["low"]:
            assert dim["issues"], f"{dim['label']} 低于 70 但没有段落定位"
            for issue in dim["issues"]:
                assert issue["paragraph_index"] >= 1
                assert issue["excerpt"]
                assert issue["char_end"] >= issue["char_start"]


def test_unsourced_number_points_to_the_exact_paragraph():
    report = score_content_geo(**_score_kwargs(
        body="\n\n".join([
            "广州基地提供企业内训服务。",
            "## 交付数据",
            "2025 年累计交付 320 场，覆盖 2.4 万名学员。",
            "## 服务边界",
            "具体排期以需求访谈为准。",
        ]),
    ))
    evidence = next(item for item in report["dimensions"] if item["key"] == "evidence")
    issue = next(item for item in evidence["issues"] if item["check_key"] == "unsourced_numbers")
    assert issue["paragraph_index"] == 3
    assert "320" in issue["excerpt"]


def test_completeness_marks_answered_intents_and_used_facts():
    report = score_content_geo(**_score_kwargs(
        body="\n\n".join([
            "广州基地企业内训课程价格是 3980 元，地址在广州市天河区。",
            "报名怎么操作：第一步填写需求，第二步完成访谈，第三步确认排期。",
        ]),
        question_texts=["课程价格是多少", "地址在哪里", "报名怎么操作"],
        fact_links=[
            {"fact_key": "course_fee", "fact_value": "3980", "stale": False},
            {"fact_key": "base_address", "fact_value": "广州市天河区", "stale": False},
        ],
    ))
    completeness = report["completeness"]
    assert completeness["status"] == "ok"
    assert completeness["questions_total"] == 3
    assert completeness["questions_answered"] == 3
    assert completeness["facts_total"] == 2
    assert completeness["facts_used"] == 2
    assert all(row["status"] == "covered" for row in completeness["questions"])


def test_completeness_marks_keyword_only_when_intent_has_no_answer_signal():
    report = score_content_geo(**_score_kwargs(
        body="广州基地的课程价格说明如下，具体以需求访谈为准。",
        question_texts=["课程价格是多少"],
        fact_links=[],
    ))
    completeness = report["completeness"]
    assert completeness["status"] == "partial"
    assert completeness["questions"][0]["intent"] == "price"
    assert completeness["questions"][0]["status"] == "keyword_only"
    assert "没有价格数字" in completeness["questions"][0]["detail"]


def test_short_title_and_missing_product_locate_to_paragraph():
    report = score_content_geo(**_score_kwargs(
        title="广州基地方案",
        product_terms=[],
        keyword_names=[],
        question_texts=[],
    ))
    entity = next(item for item in report["dimensions"] if item["key"] == "entity")
    product_issue = next(item for item in entity["issues"] if item["check_key"] == "product_mention")
    assert product_issue["paragraph_index"] >= 1
    assert product_issue["excerpt"]


def test_geo_score_api_and_submit_audit_has_no_total(
    client, db, project_factory, user_factory, member_factory
):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"geo-score-{suffix}")
    editor = user_factory(f"geo-score-editor-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)

    item_response = client.post(
        f"/api/v1/projects/{project.id}/contents",
        json={"title": "广州基地企业内训介绍", "kind": "master"},
        headers=_auth(editor),
    )
    assert item_response.status_code == 201, item_response.text
    item_id = item_response.json()["data"]["item_id"]
    version_response = client.post(
        f"/api/v1/projects/{project.id}/contents/{item_id}/versions",
        json={
            "body": "广州基地提供企业管理培训服务。\n\n## 适合谁？\n适合正在扩张团队的企业。",
            "change_note": "首版",
        },
        headers=_auth(editor),
    )
    assert version_response.status_code == 201, version_response.text
    version_id = version_response.json()["data"]["version_id"]

    score_response = client.get(
        f"/api/v1/projects/{project.id}/content-versions/{version_id}/geo-score",
        headers=_auth(editor),
    )
    assert score_response.status_code == 200, score_response.text
    score = score_response.json()["data"]
    assert "score" not in score
    assert score["rule_version"] == "geo-content-score-v2"
    assert [dim["label"] for dim in score["dimensions"]] == DIMENSION_LABELS
    assert score["attention_count"] > 0
    assert score["content_hash"]

    submit = client.post(
        f"/api/v1/projects/{project.id}/content-versions/{version_id}/submit",
        headers=_auth(editor),
    )
    assert submit.status_code == 200, submit.text
    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.action == "content.submit",
            AuditLog.target_id == uuid.UUID(version_id),
        )
    )
    assert audit is not None
    assert "score" not in audit.payload["geo_score"]
    assert audit.payload["geo_score"]["scores"]["answer_frontload"] >= 0
    assert audit.payload["geo_score"]["rule_version"] == "geo-content-score-v2"


@pytest.mark.parametrize(
    ("missing", "expected_dimension"),
    [
        ("question_texts", "问题匹配"),
        ("citation_count", "证据密度"),
        ("product_terms", "实体完整"),
        ("owned_domains", "权威信号"),
    ],
)
def test_each_missing_evidence_shows_up_in_its_dimension(missing, expected_dimension):
    overrides = {missing: [] if missing != "citation_count" else 0}
    report = score_content_geo(**_score_kwargs(**overrides))
    dim = next(item for item in report["dimensions"] if item["label"] == expected_dimension)
    assert dim["score"] < 100
    assert dim["issues"]
