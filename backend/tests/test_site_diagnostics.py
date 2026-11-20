"""C11 官网诊断：L1 页面检查、L2/L3 日志导入与四状态汇总。"""

import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.api import site_diagnostics as site_api
from app.core.security import create_access_token
from app.models import AiEngine, AuditLog, CrawlerEvent, Lead, PublicPage, TrafficEvent
from app.models.enums import EnrollmentStatus, PagePublishStatus, PageType, RoleCode
from app.services.site_diagnostics import _robots_allowed, _sitemap_urls


class _RobotsClient:
    def __init__(self, text: str) -> None:
        self._text = text

    def get(self, url: str, follow_redirects: bool = True) -> httpx.Response:
        return httpx.Response(200, text=self._text)


class _StatusClient:
    def __init__(self, status_code: int, text: str = "") -> None:
        self._status_code = status_code
        self._text = text

    def get(self, url: str, follow_redirects: bool = True) -> httpx.Response:
        return httpx.Response(self._status_code, text=self._text)


def test_sitemap_404_is_known_not_listed():
    assert _sitemap_urls(_StatusClient(404), "https://www.gdccai.com/a") == set()


def test_sitemap_server_error_is_unknown():
    assert _sitemap_urls(_StatusClient(500), "https://www.gdccai.com/a") is None


def test_sitemap_parses_loc_urls():
    text = "<urlset><url><loc>https://www.gdccai.com/a</loc></url></urlset>"
    assert _sitemap_urls(_StatusClient(200, text), "https://www.gdccai.com/a") == {
        "https://www.gdccai.com/a"
    }


def test_robots_specific_agent_overrides_wildcard():
    text = "User-agent: *\nAllow: /news\n\nUser-agent: Bytespider\nDisallow: /\n"
    assert _robots_allowed(_RobotsClient(text), "https://www.gdccai.com/news/a") is False


def test_robots_wildcard_rule_matches_path():
    text = "User-agent: *\nDisallow: /private/*\n"
    assert _robots_allowed(_RobotsClient(text), "https://www.gdccai.com/private/a") is False
    assert _robots_allowed(_RobotsClient(text), "https://www.gdccai.com/public/a") is True


def test_robots_anchor_rule_matches_only_suffix():
    text = "User-agent: *\nDisallow: /*.pdf$\n"
    assert _robots_allowed(_RobotsClient(text), "https://www.gdccai.com/a.pdf") is False
    assert _robots_allowed(_RobotsClient(text), "https://www.gdccai.com/a.pdf.bak") is True


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _create_page(db, project, *, url: str | None = None) -> PublicPage:
    page = PublicPage(
        project_id=project.id,
        slug=f"p-{uuid.uuid4().hex[:8]}",
        title="官网页面",
        page_type=PageType.FAQ,
        url=url or "https://www.gdccai.com/faq/test",
        canonical_url=url or "https://www.gdccai.com/faq/test",
        publish_status=PagePublishStatus.PUBLISHED,
    )
    db.add(page)
    db.commit()
    return page


def test_page_check_writes_result_and_audit(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    project = project_factory(f"site-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    page = _create_page(db, project)

    result = {
        "robots_allowed": True,
        "in_sitemap": True,
        "canonical_ok": True,
        "http_status": 200,
        "js_dependent": False,
        "checked_at": datetime.now(timezone.utc),
        "check_error": None,
    }
    monkeypatch.setattr(site_api, "check_public_page", lambda _page: result)

    resp = client.post(
        f"/api/v1/projects/{project.id}/pages/{page.id}/check",
        headers=_auth(editor),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["http_status"] == 200
    assert data["robots_allowed"] is True

    db.refresh(page)
    assert page.checked_at is not None
    assert page.in_sitemap is True
    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "page.check",
            AuditLog.target_id == page.id,
        )
    )
    assert audit is not None
    assert audit.payload["http_status"] == 200


def test_page_check_batch_writes_all_results_and_one_audit(
    client, db, project_factory, user_factory, member_factory, monkeypatch
):
    project = project_factory(f"site-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    first = _create_page(db, project, url="https://www.gdccai.com/a")
    second = _create_page(db, project, url="https://www.gdccai.com/b")

    base = {
        "robots_allowed": True,
        "in_sitemap": None,
        "canonical_ok": True,
        "http_status": 200,
        "js_dependent": False,
        "checked_at": datetime.now(timezone.utc),
        "check_error": None,
    }

    def fake_check(page):
        return {**base, "http_status": 500 if page.url.endswith("/b") else 200, "check_error": "upstream 500" if page.url.endswith("/b") else None}

    monkeypatch.setattr(site_api, "check_public_page", fake_check)

    resp = client.post(
        f"/api/v1/projects/{project.id}/pages/check-batch",
        json={"page_ids": [str(first.id), str(second.id)]},
        headers=_auth(editor),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["checked"] == 2
    assert data["errors"] == 1
    assert [item["id"] for item in data["items"]] == [str(first.id), str(second.id)]

    db.refresh(first)
    db.refresh(second)
    assert first.http_status == 200
    assert second.http_status == 500
    assert second.check_error == "upstream 500"

    audits = db.scalars(
        select(AuditLog).where(
            AuditLog.action == "page.check_batch",
            AuditLog.project_id == project.id,
        )
    ).all()
    assert len(audits) == 1
    assert audits[0].payload == {
        "checked": 2,
        "errors": 1,
        "page_ids": [str(first.id), str(second.id)],
    }
    assert db.scalar(
        select(AuditLog).where(
            AuditLog.action == "page.check",
            AuditLog.project_id == project.id,
        )
    ) is None


def test_crawler_and_traffic_import_summary(
    client, db, project_factory, user_factory, member_factory
):
    project = project_factory(f"site-{uuid.uuid4().hex[:6]}")
    editor = user_factory(f"ed-{uuid.uuid4().hex[:6]}")
    lead_ops = user_factory(f"lo-{uuid.uuid4().hex[:6]}")
    member_factory(project, editor, RoleCode.EDITOR)
    member_factory(project, lead_ops, RoleCode.LEAD_OPS)
    page = _create_page(db, project, url="http://www.gdccai.com/faq/a/")
    page.robots_allowed = True
    page.in_sitemap = True
    page.checked_at = datetime.now(timezone.utc)
    db.commit()

    crawler = client.post(
        f"/api/v1/projects/{project.id}/crawler-events/import",
        json={
            "source": "cdn_csv",
            "events": [
                {
                    "page_url": "https://www.gdccai.com/faq/a",
                    "ua_claimed": "Bytespider",
                    "source_ip": "203.0.113.10",
                    "verified_bot": True,
                    "http_status": 200,
                    "bytes": 1024,
                    "occurred_at": "2026-11-18T08:00:00+08:00",
                }
            ],
        },
        headers=_auth(editor),
    )
    assert crawler.status_code == 200, crawler.text
    assert crawler.json()["data"]["matched_pages"] == 1

    traffic = client.post(
        f"/api/v1/projects/{project.id}/traffic-events/import",
        json={
            "source": "utm_log",
            "events": [
                {
                    "visitor_session_id": "s-1",
                    "landing_url": page.url,
                    "utm_source": "doubao",
                    "utm_campaign": "geo-test",
                    "referrer": "https://www.doubao.com/",
                    "is_bot": False,
                    "occurred_at": "2026-11-18T09:00:00+08:00",
                }
            ],
        },
        headers=_auth(editor),
    )
    assert traffic.status_code == 200, traffic.text
    assert traffic.json()["data"]["imported"] == 1
    db.add(
        TrafficEvent(
            project_id=project.id,
            landing_url=page.url,
            is_bot=False,
            occurred_at=datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc),
        )
    )
    db.commit()

    engine = AiEngine(
        code=f"e-{uuid.uuid4().hex[:6]}",
        name="测试引擎",
        vendor="测试",
        supports_search=True,
    )
    db.add(engine)
    db.flush()
    db.add(
        Lead(
            project_id=project.id,
            session_id="s-1",
            reported_ai_product="豆包",
            is_valid=True,
            enrollment_status=EnrollmentStatus.UNKNOWN,
        )
    )
    db.add(
        Lead(
            project_id=project.id,
            source_engine_id=engine.id,
            is_valid=True,
            enrollment_status=EnrollmentStatus.UNKNOWN,
        )
    )
    db.commit()

    summary = client.get(
        f"/api/v1/projects/{project.id}/site-diagnostics",
        headers=_auth(editor),
    )
    assert summary.status_code == 200, summary.text
    data = summary.json()["data"]
    assert data["pages_total"] == 1
    assert data["crawler_events"] == 1
    assert data["verified_bot_events"] == 1
    assert data["traffic_events"] == 2
    assert data["visitor_sessions"] == 1
    assert data["leads_with_session"] == 1
    assert data["buckets"]["visited_no_citation"] == 1

    funnel = client.get(
        f"/api/v1/projects/{project.id}/leads/funnel",
        headers=_auth(lead_ops),
    )
    assert funnel.status_code == 200, funnel.text
    ai = funnel.json()["data"]["ai_attribution"]
    assert ai == {
        "crawler_events": 1,
        "verified_bot_events": 1,
        "human_visits": 2,
        "trackable_visits": 1,
        "human_sessions": 1,
        "monitored_citations": 0,
        "monitored_citation_urls": 0,
        "self_reported_ai_leads": 1,
        "engine_attributed_leads": 1,
        "self_reported_ai_valid_leads": 1,
    }

    assert db.scalar(select(CrawlerEvent.id).where(CrawlerEvent.project_id == project.id)) is not None
    traffic_row = db.scalar(
        select(TrafficEvent).where(
            TrafficEvent.project_id == project.id,
            TrafficEvent.import_source == "utm_log",
        )
    )
    assert traffic_row is not None and traffic_row.import_source == "utm_log"

