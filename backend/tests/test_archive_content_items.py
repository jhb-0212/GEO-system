"""归档脚本的可疑稿判定：只挑明显的联调残留，不误伤真实稿。

这条规则的实际意义是：批量归档一旦误判，会把真实内容一起退出统计，
比不归档更难发现——所以判定必须保守（标题字样 + 正文字数两条硬信号）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import ContentItem, ContentVersion
from scripts.archive_content_items import _is_suspicious


def _version(body: str) -> ContentVersion:
    version = ContentVersion()
    version.body = body
    return version


def _item(title: str) -> ContentItem:
    item = ContentItem()
    item.title = title
    return item


def test_flags_title_with_test_marker() -> None:
    assert _is_suspicious(_item("发布闭环联调稿-728280"), [_version("正文" * 200)]) is not None


def test_flags_short_body_even_with_clean_title() -> None:
    reason = _is_suspicious(_item("AIGC 实训路线复盘"), [_version("短稿")])
    assert reason is not None and "过短" in reason


def test_does_not_flag_real_draft() -> None:
    body = "正文" * 500
    assert _is_suspicious(_item("AIGC 实训路线复盘"), [_version(body)]) is None


def test_checks_all_versions() -> None:
    """多版本内容里只要有一个短稿就提示——短稿通常正是联调残留。"""
    body = "正文" * 500
    assert _is_suspicious(_item("正常标题"), [_version(body), _version("15 字的联调正文")]) is not None
