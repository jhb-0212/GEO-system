"""历史导入脚本的边界行为：试跑与正式导入口径一致、超长/重复/线索去重。"""

from sqlalchemy import func, select

from app.models import Lead, Question
from scripts.import_legacy import import_leads, import_questions


def test_question_dry_run_matches_real_and_lengths(db, project_factory):
    project = project_factory("edge-import-q")
    rows = [
        {"code": "Q-OK", "question_text": "正常题目", "qtype": "general", "audience": ""},
        {"code": "Q-OK", "question_text": "同文件重复", "qtype": "general", "audience": ""},
        {"code": "", "question_text": "缺 code", "qtype": "general", "audience": ""},
        {"code": "Q" * 40, "question_text": "超长 code", "qtype": "general", "audience": ""},
        {"code": "Q-LONG", "question_text": "长" * 300, "qtype": "general", "audience": ""},
    ]
    dry = import_questions(db, project, rows, None, dry_run=True)
    real = import_questions(db, project, rows, None, dry_run=False)
    db.flush()

    assert dry["imported"] == real["imported"] == 1
    assert dry["skipped"] == real["skipped"] == 1
    assert dry["failed"] == real["failed"] == 3
    assert db.scalar(
        select(func.count()).select_from(Question).where(Question.project_id == project.id)
    ) == 1


def test_lead_dedupe_by_phone_or_wechat(db, project_factory):
    project = project_factory("edge-import-l")
    rows = [
        {"contact_name": "正常", "phone": "13900000001", "wechat": "wx_1",
         "course": "", "source": "", "remark": ""},
        {"contact_name": "同手机不同微信", "phone": "13900000001", "wechat": "wx_2",
         "course": "", "source": "", "remark": ""},
        {"contact_name": "同微信不同手机", "phone": "13900000002", "wechat": "wx_1",
         "course": "", "source": "", "remark": ""},
        {"contact_name": "无联系方式", "phone": "", "wechat": "",
         "course": "", "source": "", "remark": ""},
        {"contact_name": "名" * 80, "phone": "13900000003", "wechat": "",
         "course": "", "source": "", "remark": ""},
    ]
    dry = import_leads(db, project, rows, None, dry_run=True)
    real = import_leads(db, project, rows, None, dry_run=False)
    db.flush()

    assert dry["imported"] == real["imported"] == 1
    assert dry["skipped"] == real["skipped"] == 2
    assert dry["failed"] == real["failed"] == 2
    assert db.scalar(
        select(func.count()).select_from(Lead).where(Lead.project_id == project.id)
    ) == 1
