"""公司官网页面导入脚本的纯函数回归（不连库、不联网）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "import_public_pages.py"
spec = importlib.util.spec_from_file_location("import_public_pages", SCRIPT_PATH)
assert spec and spec.loader
import_public_pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(import_public_pages)

from app.models.enums import PageType  # noqa: E402


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", "home"),
        ("/about/", "about"),
        ("/services/aigc", "services-aigc"),
        ("/services/llm", "services-llm"),
        ("/insights/how-to-judge-aigc-course", "insights-how-to-judge-aigc-course"),
        ("/news/show-3411058.html", "news-show-3411058"),
        ("/Product/Show-98519.HTML", "product-show-98519"),
    ],
)
def test_slug_from_path(path: str, expected: str) -> None:
    assert import_public_pages.slug_from_path(path) == expected


def test_page_type_maps_product_to_course() -> None:
    assert import_public_pages.page_type_from_path("/product/show-98519.html") == PageType.COURSE


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/services", PageType.COURSE),
        ("/services/aigc", PageType.COURSE),
        ("/services/llm", PageType.COURSE),
        ("/faq", PageType.FAQ),
        ("/cases/shanhai", PageType.CASE),
        ("/insights", PageType.OTHER),
        ("/glossary", PageType.OTHER),
    ],
)
def test_page_type_maps_new_site_paths(path: str, expected: PageType) -> None:
    assert import_public_pages.page_type_from_path(path) == expected


def test_news_with_course_word_in_title_stays_other() -> None:
    """资讯稿标题常带"课程"字样，不能因此被判成课程页（曾误分 8 条）。"""
    title = "AI数字人才就业实训基地针对人群分几类，课程怎么选"
    assert import_public_pages.page_type_from_path("/news/show-3086888.html", title) == PageType.OTHER


def test_resolve_title_prefers_h1_then_path_label() -> None:
    assert import_public_pages.resolve_title("<h1>公司介绍</h1>", "/about/") == "公司介绍"
    assert import_public_pages.resolve_title("", "/services/aigc") == "AIGC 生成式人工智能全栈就业班"
    generic = "<title>广东AI数字人才就业实训基地_AIGC实训_AI大模型就业培训</title>"
    assert import_public_pages.resolve_title(generic, "/news/") == "资讯列表"
