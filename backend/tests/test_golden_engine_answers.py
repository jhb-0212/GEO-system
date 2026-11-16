"""Golden set 回归：固定一段真实形状的回答，断言提及、引用域名、竞品顺序。

这些夹具不是数据库 seed，也不调用真实引擎；CI 的 `pytest -q` 会在每次引擎/提示词
变更时跑同一组断言，避免只靠人工看 24 格。
"""

import json
from pathlib import Path

import pytest

from app.services.monitoring_extraction import (
    detect_brand_mention,
    normalize_url,
    parse_raw_response,
)

FIXTURE = Path(__file__).parent / "golden" / "engine_answers.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_golden_answer_extraction(case):
    payload = parse_raw_response(case["raw_response"])
    expected = case["expected"]

    assert detect_brand_mention(payload.text, case["brand_terms"]) is expected["brand_mentioned"]
    domains = [normalize_url(citation.url)[1] for citation in payload.citations]
    assert domains == expected["citation_domains"]
    assert [
        [mention.name, mention.position] for mention in payload.competitor_mentions
    ] == expected["competitors"]

    usage = payload.raw_response.get("usage") if payload.raw_response else None
    total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
    assert total_tokens == expected["total_tokens"]
