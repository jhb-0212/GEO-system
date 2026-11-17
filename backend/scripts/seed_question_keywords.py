"""把「首批问题与内容」表里的目标词落进系统，并挂到对应题目。

背景：题目集（Q01–Q06）早就在库里，但 `keywords` 是 0 行——也就是策划表里
「目标词」这一列从来没进过系统。后果是内容侧的覆盖判断没有基准：
写出来的稿子到底盖没盖住「广州 AI 实训费用」这类词，无从核对。

映射来自业务方 2026-11-17 的「首批问题与内容」表（用户提供截图），逐题照搬，
不额外造词。词的分类只用于工作台分组，不影响任何指标。

用法（backend 目录下，先设 PYTHONPATH）：
    .\\.venv\\Scripts\\python.exe scripts\\seed_question_keywords.py
    .\\.venv\\Scripts\\python.exe scripts\\seed_question_keywords.py --apply

幂等：按 `(project_id, name)` 唯一约束复用已有词，已建的题目关联跳过，重复跑不产生重复行。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Keyword, Project, Question, QuestionKeyword

# 逐条来自「首批问题与内容」表：题目 code → 目标词。
# priority 越小越靠前：品牌与费用类是转化直接相关，排前面。
MAPPING: dict[str, list[dict[str, object]]] = {
    "Q01": [
        {"name": "基地全称", "category": "品牌识别", "priority": 1},
        {"name": "基地广州地址", "category": "品牌识别", "priority": 1},
        {"name": "报名", "category": "报名与费用", "priority": 1},
    ],
    "Q02": [
        {"name": "广州 AI 线下实训", "category": "地域与选校", "priority": 2},
        {"name": "广州零基础 AIGC 实训", "category": "地域与选校", "priority": 2},
    ],
    "Q03": [
        {"name": "广州 AI 视频制作实训", "category": "课程与实训", "priority": 2},
        {"name": "AIGC 数字创意应用", "category": "课程与实训", "priority": 2},
    ],
    "Q04": [
        {"name": "AI 大模型行业应用实训", "category": "课程与实训", "priority": 2},
        {"name": "AI 办公自动化培训", "category": "课程与实训", "priority": 2},
    ],
    "Q05": [
        {"name": "广州 AI 就业实训", "category": "就业与作品", "priority": 2},
        {"name": "AIGC 求职作品集", "category": "就业与作品", "priority": 2},
    ],
    "Q06": [
        {"name": "广州 AI 实训费用", "category": "报名与费用", "priority": 1},
        {"name": "AIGC 实训周期", "category": "报名与费用", "priority": 1},
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-code", default="gz-base", help="项目 code，默认 gz-base")
    parser.add_argument("--apply", action="store_true", help="真正写库；不加则只预演")
    args = parser.parse_args()

    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            print(f"找不到项目 {args.project_code}", file=sys.stderr)
            return 2

        questions = {
            row.code: row
            for row in db.scalars(
                select(Question).where(Question.project_id == project.id)
            ).all()
        }
        existing_keywords = {
            row.name: row
            for row in db.scalars(
                select(Keyword).where(Keyword.project_id == project.id)
            ).all()
        }
        existing_links = {
            (row.question_id, row.keyword_id)
            for row in db.scalars(
                select(QuestionKeyword).where(QuestionKeyword.project_id == project.id)
            ).all()
        }

        missing_questions = [code for code in MAPPING if code not in questions]
        if missing_questions:
            print(f"项目里缺这些题目：{missing_questions}", file=sys.stderr)
            return 3

        to_create: list[dict[str, object]] = []
        to_link: list[tuple[str, str]] = []
        for code, items in MAPPING.items():
            for item in items:
                name = str(item["name"])
                if name not in existing_keywords and name not in {str(x["name"]) for x in to_create}:
                    to_create.append(item)
                question = questions[code]
                keyword_id = None
                if name in existing_keywords:
                    keyword_id = existing_keywords[name].id
                if keyword_id is not None:
                    to_link.append((code, name))

        print(f"项目：{args.project_code}（{project.name}）")
        print(f"现有目标词：{len(existing_keywords)} 个    现有题目关联：{len(existing_links)} 条")
        print(f"将新增目标词：{len(to_create)} 个")
        for item in to_create:
            print(f"  + [{item['category']}] {item['name']}（priority={item['priority']}）")
        print(f"\n现有词与题目的关联：{len(to_link)} 条将补齐（新增词在本次落库后自动关联）")

        if not args.apply:
            print("\n[dry-run] 未写入。加 --apply 落库。")
            return 0

        created: dict[str, Keyword] = {}
        for item in to_create:
            keyword = Keyword(
                project_id=project.id,
                name=str(item["name"]),
                category=str(item["category"]),
                priority=int(item["priority"]),
                is_active=True,
                notes="来自「首批问题与内容」表（2026-11-17）",
            )
            db.add(keyword)
            created[str(item["name"])] = keyword
        db.flush()

        all_keywords = {**existing_keywords, **created}
        links_added = 0
        for code, items in MAPPING.items():
            for item in items:
                keyword = all_keywords.get(str(item["name"]))
                if keyword is None:
                    continue
                key = (questions[code].id, keyword.id)
                if key in existing_links:
                    continue
                db.add(
                    QuestionKeyword(
                        project_id=project.id,
                        question_id=questions[code].id,
                        keyword_id=keyword.id,
                    )
                )
                existing_links.add(key)
                links_added += 1
        db.commit()

        print(f"\n已写入：新增目标词 {len(created)} 个，新增题目关联 {links_added} 条。")
        total_keywords = len(all_keywords)
        total_links = len(existing_links)
        print(f"当前合计：目标词 {total_keywords} 个，题目关联 {total_links} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
