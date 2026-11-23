"""引用页型规则重判：只救 other，人工结论永不覆盖。

钉住四条：
1. 规则按 URL 路径/站点/标题判页型，判不出仍是 other；
2. 预览不写库，apply 才写，且写入 rule_version 与 page_type_source=rule；
3. page_type_source=manual 的行即使 URL 有强信号也不动；
4. 每次 apply 落一条审计（citations.page_type.reclassify）。
"""

import uuid
from datetime import UTC, datetime

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    AuditLog,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    CitationPageType,
    CitationReviewStatus,
    EngineEntryType,
    QuestionType,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    SourceCategory,
    TaskStatus,
)
from app.services.page_type_rules import infer_page_type, infer_page_type_from_content


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _seed(db, project) -> None:
    suffix = uuid.uuid4().hex[:6]
    engine = AiEngine(code=f"pt-{suffix}", name="页型引擎", vendor="测试", supports_search=True,
                      supports_citation=True, is_active=True)
    db.add(engine)
    db.flush()
    entry = AiEngineEntry(engine_id=engine.id, entry_type=EngineEntryType.WEB_USER, name="网页端", is_active=True)
    db.add(entry)
    question = Question(project_id=project.id, code=f"PT-{suffix}", title="页型题",
                        question_type=QuestionType.GENERAL, status="active", current_version_no=1)
    db.add(question)
    db.flush()
    version = QuestionVersion(project_id=project.id, question_id=question.id, version_no=1, text="页型题")
    round_row = MonitoringRound(project_id=project.id, seq=1, name="页型轮次", status=RoundStatus.RUNNING)
    db.add_all([version, round_row])
    db.flush()
    task = MonitoringTask(project_id=project.id, round_id=round_row.id, question_version_id=version.id,
                          engine_entry_id=entry.id, sampling_no=1, sampling_mode=SamplingMode.SEARCH_ON,
                          status=TaskStatus.DONE)
    db.add(task)
    db.flush()
    sample = MonitoringSample(project_id=project.id, task_id=task.id, attempt_no=1,
                             status=SampleStatus.HIT, sampled_at=datetime.now(UTC), brand_mentioned=True)
    db.add(sample)
    db.flush()

    rows = [
        # 可重判：知乎专栏 → article；知乎问题 → forum_or_qa
        ("https://zhuanlan.zhihu.com/p/123", "unknown", CitationPageType.OTHER),
        ("https://www.zhihu.com/question/456", "unknown", CitationPageType.OTHER),
        # 人工结论：即使 URL 是榜单也不动
        ("https://example.com/top-10", "manual", CitationPageType.OTHER),
        # 已是 rule 判出的非 other：不在 other 目标里
        ("https://example.com/rank/1", "rule", CitationPageType.ARTICLE),
        # 无 URL 信号、但标题有形态词：只有 content 模式能救
        ("https://example.com/xyz-abc", "rule", CitationPageType.OTHER),
    ]
    titles = {"https://example.com/top-10": "十大培训机构排名",
              "https://example.com/xyz-abc": "2026 广州 AI 培训机构十大排名"}
    for index, (url, source, page_type) in enumerate(rows):
        db.add(MonitoringCitation(
            project_id=project.id, sample_id=sample.id,
            raw_url=url, normalized_url=url, domain=url.split("/")[2], title=titles.get(url),
            page_type=page_type, page_type_source=source,
            source_category=SourceCategory.SOCIAL_COMMUNITY,
            review_status=CitationReviewStatus.MANUAL_CONFIRMED,
        ))
    db.flush()


def test_infer_from_content():
    assert infer_page_type_from_content(title="2026广州AI培训机构十大排名")["page_type"] == CitationPageType.LISTICLE
    assert infer_page_type_from_content(title="某某教育常见问题解答")["page_type"] == CitationPageType.FAQ
    assert infer_page_type_from_content(title="报名指南：如何选择课程")["page_type"] != CitationPageType.OTHER
    # 只有弱词或证据打平，都不硬判
    assert infer_page_type_from_content(title="关于我们")["page_type"] == CitationPageType.OTHER
    # 三类词打平也算证据不足：不硬判
    assert infer_page_type_from_content(title="课程对比评测")["page_type"] == CitationPageType.OTHER


def test_infer_rules():
    assert infer_page_type("https://zhuanlan.zhihu.com/p/1")["page_type"] == CitationPageType.ARTICLE
    assert infer_page_type("https://www.zhihu.com/question/1")["page_type"] == CitationPageType.FORUM_OR_QA
    assert infer_page_type("https://www.douyin.com/video/1")["page_type"] == CitationPageType.VIDEO
    assert infer_page_type("https://example.com/faq")["page_type"] == CitationPageType.FAQ
    assert infer_page_type("https://example.com/")["page_type"] == CitationPageType.HOMEPAGE
    # 没信号就不硬判
    assert infer_page_type("https://example.com/xyz-abc")["page_type"] == CitationPageType.OTHER


def test_reclassify_preview_and_apply(client, db, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"pt-{suffix}")
    editor = user_factory(f"pt-e-{suffix}")
    viewer = user_factory(f"pt-v-{suffix}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, viewer, RoleCode.VIEWER)
    _seed(db, project)

    preview = client.get(
        f"/api/v1/projects/{project.id}/citations/page-type-preview?limit=100", headers=_auth(viewer)
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    assert data["dry_run"] is True
    # 目标只有 other + unknown 来源的 2 条；manual 行不扫
    assert data["scope"]["candidates"] == 3
    # xyz-abc 靠标题命中 listicle；三条 other 都能救
    assert data["scope"]["changed"] == 3
    assert data["by_target"] == {"article": 1, "forum_or_qa": 1, "listicle": 1}
    rules = {row["rule"] for row in data["examples"]}
    assert rules == {"path:article", "host:zhihu_question", "title:listicle"}


    # content 模式同样只救标题有形态词的条目（另两条无形态词）
    content = client.get(
        f"/api/v1/projects/{project.id}/citations/page-type-preview?mode=content&limit=100",
        headers=_auth(viewer),
    ).json()["data"]
    assert content["mode"] == "content"
    assert content["rule_version"] == "page-type-content-r1"
    assert content["scope"]["candidates"] == 3
    assert content["by_target"] == {"listicle": 1}

    # 预览不改库
    manual = db.query(MonitoringCitation).filter_by(raw_url="https://example.com/top-10").one()
    assert manual.page_type == CitationPageType.OTHER

    applied = client.post(
        f"/api/v1/projects/{project.id}/citations/page-type-reclassify?limit=100", headers=_auth(editor)
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["data"]["scope"]["changed"] == 3

    rows = {row.raw_url: row for row in db.query(MonitoringCitation).all()}
    assert rows["https://zhuanlan.zhihu.com/p/123"].page_type == CitationPageType.ARTICLE
    assert rows["https://zhuanlan.zhihu.com/p/123"].page_type_source == "rule"
    assert rows["https://zhuanlan.zhihu.com/p/123"].classification_rule_version == "page-type-r1"
    assert rows["https://www.zhihu.com/question/456"].page_type == CitationPageType.FORUM_OR_QA
    # 人工结论与既有 rule 行都不动
    assert rows["https://example.com/top-10"].page_type == CitationPageType.OTHER
    assert rows["https://example.com/top-10"].page_type_source == "manual"
    assert rows["https://example.com/rank/1"].page_type == CitationPageType.ARTICLE

    audit = db.query(AuditLog).filter_by(action="citations.page_type.reclassify", project_id=project.id).all()
    assert len(audit) == 1
    assert audit[0].payload["changed"] == 3
    assert audit[0].payload["rule_version"] == "page-type-r1"


