"""质量门槛升级：数字与引语必须带可核查来源；级别由项目口径决定（默认 warning）。"""

from app.services.content_quality import run_quality_check


def _keys(items: list[dict]) -> set[str]:
    return {item["key"] for item in items}


def test_unsourced_number_is_warning_by_default():
    body = "本校就业率 92%，欢迎到校参观。"
    report = run_quality_check(body, set())
    assert report["ok"] is True
    assert "number_unsourced" in _keys(report["warnings"])
    assert report["warnings"][0]["level"] == "warn"


def test_number_with_url_or_source_marker_passes():
    body = "本校就业率 92%（来源：广东省人社厅 2025 年公示 https://example.gov/report）。"
    report = run_quality_check(body, set())
    assert "number_unsourced" not in _keys(report["warnings"])

    body2 = "据广东省教育厅 2025 年统计报告，平均月薪 6800 元。"
    report2 = run_quality_check(body2, set())
    assert "number_unsourced" not in _keys(report2["warnings"])


def test_source_must_be_in_same_paragraph():
    body = "本校就业率 92%。\n\n（来源：省人社厅 2025 年公示）"
    report = run_quality_check(body, set())
    assert "number_unsourced" in _keys(report["warnings"])


def test_unsourced_quote_is_warning_and_sourced_quote_passes():
    body = "校长说：“我们从不承诺包就业，只看真实数据。”"
    report = run_quality_check(body, set())
    assert "quote_unsourced" in _keys(report["warnings"])

    body2 = "校长说：“我们从不承诺包就业。”——出处：校企合作座谈会纪要（2025-06）"
    report2 = run_quality_check(body2, set())
    assert "quote_unsourced" not in _keys(report2["warnings"])


def test_project_can_block_on_policy():
    body = "本校就业率 92%，欢迎到校参观。"
    report = run_quality_check(body, set(), number_level="block")
    assert report["ok"] is False
    assert "number_unsourced" in _keys(report["blockers"])

    body2 = "校长说：“我们从不承诺包就业。”"
    report2 = run_quality_check(body2, set(), quote_level="block")
    assert "quote_unsourced" in _keys(report2["blockers"])


def test_short_quoted_phrase_is_not_treated_as_quote():
    body = "他说“好”，随后离开。"
    report = run_quality_check(body, set())
    assert "quote_unsourced" not in _keys(report["warnings"])
