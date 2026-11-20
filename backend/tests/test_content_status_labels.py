"""P46 内容六态的业务标签：内部 scheduled 必须对外呈现为“待发布”。"""

from app.models.enums import ContentStatus
from app.services.content_status import content_status_label


def test_plan_six_states_have_chinese_labels():
    assert content_status_label(ContentStatus.DRAFT) == "草稿"
    assert content_status_label(ContentStatus.PENDING_REVIEW) == "待审"
    assert content_status_label(ContentStatus.APPROVED) == "已批准"
    assert content_status_label(ContentStatus.PENDING_PUBLISH) == "待发布"
    assert content_status_label(ContentStatus.PUBLISHED) == "已发布"
    assert content_status_label(ContentStatus.NEEDS_ATTENTION) == "需处理"


def test_extra_states_keep_explicit_labels():
    assert content_status_label(ContentStatus.REJECTED) == "已驳回"
    assert content_status_label(ContentStatus.ARCHIVED) == "已归档"
