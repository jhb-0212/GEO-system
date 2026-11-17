"""URL 比对键：只摘标准追踪参数，业务参数必须保留。"""

from app.services.citation_attribution import url_key


def test_utm_prefix_is_stripped():
    assert url_key("https://Example.com/a?utm_source=x&utm_medium=y") == "example.com/a"
    assert url_key("https://example.com/a?utm_campaign=1&p=9") == "example.com/a?p=9"


def test_exact_tracking_names_are_stripped():
    base = "https://example.com/a"
    assert url_key(f"{base}?gclid=1") == "example.com/a"
    assert url_key(f"{base}?ref=wechat") == "example.com/a"
    assert url_key(f"{base}?from=timeline") == "example.com/a"


def test_business_params_with_tracking_prefix_are_kept():
    reference_a = url_key("https://example.com/a?reference=abc")
    reference_b = url_key("https://example.com/a?reference=def")
    assert reference_a != reference_b
    assert "reference=abc" in reference_a
    assert "fromDate=2026-11" in url_key("https://example.com/a?fromDate=2026-11")
