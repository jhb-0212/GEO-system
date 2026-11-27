"""渠道分类必须都有改编规则：少一条就会静默落到 UNKNOWN_RULE。"""

from app.models.enums import ChannelCategory
from app.services.content_derivation import CHANNEL_RULES, rule_for


def test_every_channel_category_has_rule():
    missing = [category.value for category in ChannelCategory if category.value not in CHANNEL_RULES]
    assert missing == []


def test_b2b_uses_media_length_budget():
    # B2B 商讯普遍超过自媒体 2000 字上限，按媒体口径 3000 字
    rule = rule_for(ChannelCategory.B2B)
    assert rule["label"] == "B2B 商贸平台"
    assert rule["max_chars"] == 3000
    assert rule["no_link"] is False
