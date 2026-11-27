"""GEO 数据大屏：演示占位、真实口径切换、分页筛选与 IP 脱敏。

钉住七条：
1. 空项目四项 KPI 全部走演示样例，且每项带 source="demo"，不出现「真实 0 + 样例」的混合；
2. 只要有一条真实记录就整项切回真实值，inactive 关键词不计入训练词；
3. 报表明细按引擎筛选与分页，列出来源标题、凭证链接与官方域名；
4. 线索事件把访问与表单线索合并排序，IP 只给 8 位摘要，响应里不得出现完整哈希；
5. 卡片 spark 长度等于窗口天数，窗口外记录不参与；
6. 平台占比跟随采集端（pc/mobile/api）过滤，线索下拉三种计数同时返回、不随筛选变化；
7. 品牌名取项目品牌档案，缺失时回退项目名并给出 configured=False。
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.security import create_access_token
from app.models import (
    AiEngine,
    AiEngineEntry,
    BrandProfile,
    Keyword,
    Lead,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Question,
    QuestionKeyword,
    QuestionVersion,
    TrafficEvent,
)
from app.models.enums import (
    AnswerKind,
    CitationReviewStatus,
    EngineEntryType,
    QuestionStatus,
    QuestionType,
    RoleCode,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _project_and_member(project_factory, user_factory, member_factory, role=RoleCode.EDITOR):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"board-{suffix}")
    user = user_factory(f"board-u-{suffix}")
    member_factory(project, user, role)
    return project, user


def _board(client, project, user, query: str = "days=30") -> dict:
    resp = client.get(
        f"/api/v1/projects/{project.id}/dashboard/board?{query}", headers=_auth(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _kpi(data: dict, key: str) -> dict:
    return next(item for item in data["kpis"] if item["key"] == key)


def _add_keyword(db, project, name: str, *, active: bool = True) -> Keyword:
    keyword = Keyword(project_id=project.id, name=name, priority=100, is_active=active)
    db.add(keyword)
    db.flush()
    return keyword


def _add_question(db, project, title: str, keyword: Keyword | None = None, *, intent: str | None = None) -> Question:
    question = Question(
        project_id=project.id,
        code=f"Q-{uuid.uuid4().hex[:6]}",
        title=title,
        question_type=QuestionType.GENERAL,
        status=QuestionStatus.ACTIVE,
        intent=intent,
    )
    db.add(question)
    db.flush()
    version = QuestionVersion(
        project_id=project.id, question_id=question.id, version_no=1, text=title, intent=intent
    )
    db.add(version)
    db.flush()
    if keyword is not None:
        db.add(
            QuestionKeyword(
                project_id=project.id, question_id=question.id, keyword_id=keyword.id
            )
        )
        db.flush()
    return question


def _round(db, project, name: str) -> MonitoringRound:
    seq = int(
        db.scalar(
            select(func.max(MonitoringRound.seq)).where(MonitoringRound.project_id == project.id)
        )
        or 0
    ) + 1
    row = MonitoringRound(
        project_id=project.id, seq=seq, name=name, status=RoundStatus.RUNNING
    )
    db.add(row)
    db.flush()
    return row


def _add_sample_with_citation(
    db,
    project,
    *,
    engine_name: str,
    question: Question,
    title: str,
    url: str,
    domain: str,
    sampled_at: datetime | None = None,
    answer_kind: AnswerKind | None = None,
    brand_mentioned: bool = True,
    entry_type: EngineEntryType = EngineEntryType.WEB_USER,
) -> MonitoringCitation:
    version = db.scalar(
        select(QuestionVersion).where(QuestionVersion.question_id == question.id)
    )
    assert version is not None
    engine = db.scalar(select(AiEngine).where(AiEngine.name == engine_name))
    if engine is None:
        engine = AiEngine(
            code=f"e-{uuid.uuid4().hex[:6]}", name=engine_name, vendor="test", supports_search=True
        )
        db.add(engine)
        db.flush()
    entry = AiEngineEntry(
        engine_id=engine.id,
        name=f"{engine_name}-入口-{uuid.uuid4().hex[:4]}",
        entry_type=entry_type,
        entry_url="https://example.com",
        is_active=True,
    )
    db.add(entry)
    db.flush()
    task = MonitoringTask(
        project_id=project.id,
        round_id=_round(db, project, "大屏轮次").id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=1,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=TaskStatus.RUNNING,
    )
    db.add(task)
    db.flush()
    sample = MonitoringSample(
        project_id=project.id,
        task_id=task.id,
        attempt_no=1,
        status=SampleStatus.HIT,
        brand_mentioned=brand_mentioned,
        answer_kind=answer_kind,
        sampled_at=sampled_at or datetime.now(UTC),
    )
    db.add(sample)
    db.flush()
    citation = MonitoringCitation(
        project_id=project.id,
        sample_id=sample.id,
        raw_url=url,
        normalized_url=url,
        domain=domain,
        title=title,
        review_status=CitationReviewStatus.MANUAL_CONFIRMED,
        is_brand_related=True,
    )
    db.add(citation)
    db.flush()
    return citation


def test_empty_project_uses_demo_kpis(client, project_factory, user_factory, member_factory):
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    data = _board(client, project, user)

    assert len(data["kpis"]) == 4
    assert [item["key"] for item in data["kpis"]] == [
        "training_words",
        "recommended_words",
        "indexed_total",
        "lead_events",
    ]
    for item in data["kpis"]:
        assert item["source"] == "demo"
        assert item["spark"] and len(item["spark"]) == 30
        assert item["value"] > 0
    assert data["has_demo"] is True
    assert data["indexed_series"]["source"] == "demo"
    assert len(data["indexed_series"]["items"]) == 30
    assert data["report"]["total"] == 0
    assert data["lead_events"]["total"] == 0
    assert data["notes"]


def test_real_records_switch_whole_kpi_back_to_real(
    client, db, project_factory, user_factory, member_factory
):
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    _add_keyword(db, project, "AI 实训基地")
    _add_keyword(db, project, "GEO 优化")
    _add_keyword(db, project, "停用词", active=False)
    _add_question(db, project, "广州有哪些 AI 实训机构")
    db.commit()

    data = _board(client, project, user, "days=7")
    training = _kpi(data, "training_words")
    recommended = _kpi(data, "recommended_words")

    # 停用关键词不进训练词总数；真实值一出现就整项切回 real，不再混样例。
    assert training["source"] == "real"
    assert training["value"] == 2
    assert training["spark"] and len(training["spark"]) == 7
    assert recommended["source"] == "real"
    assert recommended["value"] == 1
    assert _kpi(data, "indexed_total")["source"] == "demo"
    assert data["has_demo"] is True


def test_report_filters_by_engine_and_pages(
    client, db, project_factory, user_factory, member_factory
):
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    keyword = _add_keyword(db, project, "AI 数字人才实训基地")
    question = _add_question(db, project, "广州 AI 实训哪家靠谱", keyword)
    _add_sample_with_citation(
        db,
        project,
        engine_name="豆包",
        question=question,
        title="广州靠谱的 AI 数字人才实训企业",
        url="https://example.com/a",
        domain="example.com",
    )
    _add_sample_with_citation(
        db,
        project,
        engine_name="DeepSeek",
        question=question,
        title="AI 实训机构对比",
        url="https://example.org/b",
        domain="example.org",
    )
    db.commit()

    data = _board(client, project, user)
    report = data["report"]
    assert report["total"] == 2
    assert report["pages"] == 1
    assert [item["engine_name"] for item in report["engines"]][0] == "全部"
    assert report["engines"][0]["value"] == 2
    first = report["rows"][0]
    assert first["training_word"] == "AI 数字人才实训基地"
    assert first["voucher_url"].startswith("https://example.")
    assert first["official_url"].startswith("https://example.")
    assert first["platform"] in {"豆包", "DeepSeek"}

    engine = db.scalar(select(AiEngine).where(AiEngine.name == "豆包"))
    assert engine is not None
    doubao = _board(client, project, user, f"days=30&engine_id={engine.id}")
    assert doubao["report"]["total"] == 1
    assert doubao["report"]["selected_engine_id"] == str(engine.id)
    assert doubao["report"]["rows"][0]["platform"] == "豆包"

    paged = _board(client, project, user, "days=30&page=2&page_size=1")
    assert paged["report"]["pages"] == 2
    assert len(paged["report"]["rows"]) == 1


def test_report_kind_splits_answer_kind_intent_and_brand(
    client, db, project_factory, user_factory, member_factory
):
    """五类报表：all 全量；search/qa 按样本答案口径拆；intent 看问题意图；brand 看品牌命中。"""
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    question = _add_question(db, project, "广州 AI 实训哪家靠谱", intent="推荐")
    _add_sample_with_citation(
        db,
        project,
        engine_name="豆包",
        question=question,
        title="检索结果条目",
        url="https://example.com/search",
        domain="example.com",
        answer_kind=AnswerKind.SEARCH_RESULT,
        brand_mentioned=False,
    )
    _add_sample_with_citation(
        db,
        project,
        engine_name="豆包",
        question=question,
        title="生成回答条目",
        url="https://example.org/answer",
        domain="example.org",
        answer_kind=AnswerKind.ANSWER,
        brand_mentioned=True,
    )
    db.commit()

    def rows(kind: str) -> list[str]:
        report = _board(client, project, user, f"days=30&report_kind={kind}")["report"]
        assert report["kind"] == kind
        return [row["answer_entity"] for row in report["rows"]]

    assert set(rows("all")) == {"生成回答条目", "检索结果条目"}
    assert rows("search") == ["检索结果条目"]
    assert rows("qa") == ["生成回答条目"]
    assert set(rows("intent")) == {"生成回答条目", "检索结果条目"}
    assert rows("brand") == ["生成回答条目"]

    # 类型与引擎筛选叠加：两类条件同时生效，不是互相覆盖。
    engine = db.scalar(select(AiEngine).where(AiEngine.name == "豆包"))
    assert engine is not None
    combined = _board(client, project, user, f"days=30&engine_id={engine.id}&report_kind=search")["report"]
    assert combined["total"] == 1
    assert combined["rows"][0]["answer_entity"] == "检索结果条目"


def test_report_kind_rejects_unknown(client, db, project_factory, user_factory, member_factory):
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    resp = client.get(
        f"/api/v1/projects/{project.id}/dashboard/board?days=30&report_kind=nope", headers=_auth(user)
    )
    assert resp.status_code == 422
    resp = client.get(
        f"/api/v1/projects/{project.id}/dashboard/board?days=30&device=nope", headers=_auth(user)
    )
    assert resp.status_code == 422


def test_report_device_splits_web_and_mobile(
    client, db, project_factory, user_factory, member_factory
):
    """采集端：pc 只看网页用户端；mobile 看客户端 + 应用内搜索；all 合并（官方 API 只在全部）。"""
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    question = _add_question(db, project, "广州 AI 实训哪家靠谱")
    cases = (
        ("网页端条目", EngineEntryType.WEB_USER, "https://example.com/web", "example.com"),
        ("App 条目", EngineEntryType.APP_USER, "https://example.org/app", "example.org"),
        ("应用内搜索条目", EngineEntryType.APP_SEARCH, "https://example.net/search", "example.net"),
        ("API 条目", EngineEntryType.API, "https://example.edu/api", "example.edu"),
    )
    for title, entry_type, url, domain in cases:
        _add_sample_with_citation(
            db, project, engine_name="豆包", question=question,
            title=title, url=url, domain=domain, entry_type=entry_type,
        )
    db.commit()

    def report(device: str) -> dict:
        return _board(client, project, user, f"days=30&device={device}")["report"]

    assert report("all")["device"] == "all"
    assert report("all")["total"] == 4
    assert report("all")["engines"][0]["value"] == 4

    pc = report("pc")
    assert [row["answer_entity"] for row in pc["rows"]] == ["网页端条目"]
    assert pc["engines"][0]["value"] == 1

    mobile = report("mobile")
    assert {row["answer_entity"] for row in mobile["rows"]} == {"App 条目", "应用内搜索条目"}
    assert mobile["engines"][0]["value"] == 2

    api = report("api")
    assert [row["answer_entity"] for row in api["rows"]] == ["API 条目"]
    assert api["engines"][0]["value"] == 1


def test_lead_events_merge_sources_and_mask_ip(
    client, db, project_factory, user_factory, member_factory
):
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    traffic_hash = "a" * 32 + uuid.uuid4().hex
    lead_hash = "b" * 32 + uuid.uuid4().hex
    db.add(
        TrafficEvent(
            project_id=project.id,
            visitor_session_id="s-1",
            visitor_ip_hash=traffic_hash,
            visitor_region="广东",
            landing_url="https://example.com/landing",
            utm_source="doubao",
            is_bot=False,
            occurred_at=datetime.now(UTC),
        )
    )
    db.add(
        Lead(
            project_id=project.id,
            lead_source="官网表单",
            visitor_region="上海",
            ip_hash=lead_hash,
            landing_url="https://example.com/form",
        )
    )
    db.commit()

    data = _board(client, project, user)
    events = data["lead_events"]
    assert events["total"] == 2
    assert {row["event"] for row in events["rows"]} == {"访问官网", "提交线索"}
    for row in events["rows"]:
        assert row["ip_masked"].endswith("…")
        assert len(row["ip_masked"].rstrip("…")) == 8
    body = str(events)
    assert traffic_hash not in body
    assert lead_hash not in body
    assert _kpi(data, "lead_events")["source"] == "real"
    assert _kpi(data, "lead_events")["value"] == 2


def test_platform_share_counts_only_window_samples(
    client, db, project_factory, user_factory, member_factory
):
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    keyword = _add_keyword(db, project, "GEO")
    question = _add_question(db, project, "AI 搜索优化怎么做", keyword)
    _add_sample_with_citation(
        db,
        project,
        engine_name="豆包",
        question=question,
        title="窗口内样本",
        url="https://example.com/w",
        domain="example.com",
        sampled_at=datetime.now(UTC) - timedelta(days=1),
    )
    _add_sample_with_citation(
        db,
        project,
        engine_name="元宝",
        question=question,
        title="窗口外样本",
        url="https://example.com/old",
        domain="example.com",
        sampled_at=datetime.now(UTC) - timedelta(days=45),
    )
    db.commit()

    data = _board(client, project, user, "days=30")
    share = data["engine_share"]
    assert share["total"] == 1
    assert share["items"][0]["engine_name"] == "豆包"
    assert share["items"][0]["share"] == 1.0
    # 窗口外的引用仍在累计收录里，但不进 30 天平台占比
    assert data["report"]["total"] == 1
    assert data["report"]["engines"][0]["value"] == 1


def test_lead_kind_splits_traffic_and_form_lead(
    client, db, project_factory, user_factory, member_factory
):
    """线索事件类型：all 合并时间轴；traffic 只看访问；lead 只看表单；counts 三种计数一次返回。"""
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    db.add(
        TrafficEvent(
            project_id=project.id,
            visitor_session_id="s-kind",
            visitor_ip_hash="c" * 40 + uuid.uuid4().hex[:8],
            visitor_region="广东",
            landing_url="https://example.com/landing",
            is_bot=False,
            occurred_at=datetime.now(UTC),
        )
    )
    db.add(
        Lead(
            project_id=project.id,
            lead_source="官网表单",
            visitor_region="上海",
            ip_hash="d" * 40 + uuid.uuid4().hex[:8],
            landing_url="https://example.com/form",
        )
    )
    db.commit()

    def events(kind: str) -> dict:
        return _board(client, project, user, f"days=30&lead_kind={kind}")["lead_events"]

    all_events = events("all")
    assert all_events["kind"] == "all"
    assert all_events["total"] == 2
    assert all_events["counts"] == {"all": 2, "traffic": 1, "lead": 1}

    traffic = events("traffic")
    assert traffic["kind"] == "traffic"
    assert traffic["total"] == 1
    assert [row["event"] for row in traffic["rows"]] == ["访问官网"]
    # counts 不随筛选变化：下拉里的三个数始终是全量分母。
    assert traffic["counts"] == {"all": 2, "traffic": 1, "lead": 1}

    form_only = events("lead")
    assert form_only["kind"] == "lead"
    assert form_only["total"] == 1
    assert [row["event"] for row in form_only["rows"]] == ["提交线索"]

    resp = client.get(
        f"/api/v1/projects/{project.id}/dashboard/board?days=30&lead_kind=nope", headers=_auth(user)
    )
    assert resp.status_code == 422


def test_share_follows_device_and_brand_falls_back(
    client, db, project_factory, user_factory, member_factory
):
    """平台占比按采集端过滤（不再固定全量 13 平台）；品牌名优先品牌档案，缺失时回退项目名。"""
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    question = _add_question(db, project, "广州 AI 实训哪家靠谱")
    _add_sample_with_citation(
        db, project, engine_name="豆包", question=question, title="网页端结果",
        url="https://example.com/web", domain="example.com", entry_type=EngineEntryType.WEB_USER,
    )
    _add_sample_with_citation(
        db, project, engine_name="元宝", question=question, title="App 端结果",
        url="https://example.org/app", domain="example.org", entry_type=EngineEntryType.APP_USER,
    )
    db.commit()

    all_share = _board(client, project, user, "days=30")["engine_share"]
    assert all_share["total"] == 2
    assert {item["engine_name"] for item in all_share["items"]} == {"豆包", "元宝"}

    mobile_share = _board(client, project, user, "days=30&device=mobile")["engine_share"]
    assert mobile_share["total"] == 1
    assert [item["engine_name"] for item in mobile_share["items"]] == ["元宝"]

    # 没配品牌档案：回退项目名，configured=False 让前端有据可依地提示「未配置」。
    before = _board(client, project, user)
    assert before["brand"] == {"name": project.name, "configured": False, "active": False}

    db.add(
        BrandProfile(project_id=project.id, canonical_name="广东省AI数字人才就业实训基地", is_active=True)
    )
    db.commit()
    after = _board(client, project, user)
    assert after["brand"]["name"] == "广东省AI数字人才就业实训基地"
    assert after["brand"]["configured"] is True
    assert after["brand"]["active"] is True


def test_report_rows_carry_question_and_source_title(
    client, db, project_factory, user_factory, member_factory
):
    """报表「最新搜索词场景」放问题题干，「来源标题」放引用标题，两者不混用。"""
    project, user = _project_and_member(project_factory, user_factory, member_factory)
    keyword = _add_keyword(db, project, "GEO 优化")
    question = _add_question(db, project, "广州 AI 实训哪家靠谱", keyword)
    _add_sample_with_citation(
        db, project, engine_name="豆包", question=question,
        title="知乎实测：广州 AI 实训怎么选", url="https://example.com/q", domain="example.com",
    )
    db.commit()

    row = _board(client, project, user)["report"]["rows"][0]
    assert row["question"] == "广州 AI 实训哪家靠谱"
    assert row["source_title"] == "知乎实测：广州 AI 实训怎么选"
    assert row["training_word"] == "GEO 优化"
    assert row["answer_entity"] == "知乎实测：广州 AI 实训怎么选"
