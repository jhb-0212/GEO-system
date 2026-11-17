"""把 FAQ 表从「占位符」改成「官网尚未回答的问题清单」。

背景（2026-11-17 决策）：对外页面归公司官网 `www.gdccai.com`，官网已用 60 篇问答式
新闻稿覆盖了口碑、师资、就业、选址、课程对比等题面（见
`docs/FAQ资产盘点与引用诊断-2026-11-17.md`）。所以系统里的 `faqs` 不再复制官网内容
——复制会立刻产生第二份真源，官网改一句、系统不跟，口径就漂。

它真正该装的是**官网没有回答、而 AI 每天都在被问的问题**：学费、最近开班、到校路线、
住宿价格、退款条件细则。这些是引用率与转化率的关键缺口，且必须由业务方确认后才能对外。

用法（backend 目录下，先设 PYTHONPATH）：
    .\\.venv\\Scripts\\python.exe scripts\\seed_faq_gaps.py            # 预演，不改库
    .\\.venv\\Scripts\\python.exe scripts\\seed_faq_gaps.py --apply    # 落库

行为（幂等，且**不做破坏性删除**）：
1. 新增缺口问题（`status=draft`，答案写明「待运营确认」与官网现状）；
2. `--remove-placeholders` 才会把旧的「【占位待定】」条目软删（`deleted_at`），可恢复；
3. 已存在同问题的记录跳过，重复跑不会产生重复行。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Faq, Project

# 每条都对应官网实测的空白（2026-11-17 逐页核对，官网确实没有这些答案）。
GAP_FAQS: list[dict[str, str]] = [
    {
        "category": "报名",
        "question": "两个班型的学费分别是多少？实训费和材料费各包含什么？",
        "answer": (
            "【待运营确认】官网当前只写「费用由课程顾问在咨询时出具完整方案，含实训费、"
            "材料费等，逐项说清后决定」，全站没有公开金额或区间。"
            "确认后可补：AIGC 定向实训班 / AI 大模型领航实训班的学费、材料费、住宿与设备另计标准。"
        ),
    },
    {
        "category": "报名",
        "question": "「符合条件未按约定就业可全额退款」里的「符合条件」具体指什么？",
        "answer": (
            "【待运营确认】官网首页写明「签署就业保障协议，符合条件未按约定就业可全额退款」，"
            "但未说明条件边界。需明确：出勤率/考核合格标准、求职次数与岗位范围、"
            "退款比例与到账周期、争议处理方式。"
        ),
    },
    {
        "category": "课程",
        "question": "最近一期什么时候开班？下一期的开班时间怎么查？",
        "answer": (
            "【待运营确认】官网只写学制（AIGC 约 8 周 / 400 课时，大模型近 3 个月 / 660 课时），"
            "没有开班日期。需补：常规开班节奏、最近一期日期、满班人数与报名截止时间。"
        ),
    },
    {
        "category": "课程",
        "question": "住宿和笔记本电脑租赁怎么收费？",
        "answer": (
            "【待运营确认】官网写「实训期间基地提供住宿房源信息与对接，外地学员可入住基地周边宿舍；"
            "笔记本电脑可自带或在基地租赁」，并注明「住宿、设备租赁、体检另有标准」，未给价格。"
        ),
    },
    {
        "category": "到校",
        "question": "从地铁站怎么走到基地？附近有停车位吗？",
        "answer": (
            "【待运营确认】官网只有地址（广州市番禺区东环街番禺大道北537号番禺节能科技园内"
            "番山创业中心1号楼2区207），没有交通方式。需补：最近地铁站与出口、步行或公交路线、"
            "停车位置与是否收费、参观预约方式。"
        ),
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-code", default="gz-base", help="项目 code，默认 gz-base")
    parser.add_argument("--apply", action="store_true", help="真正写库；不加则只预演")
    parser.add_argument(
        "--remove-placeholders",
        action="store_true",
        help="把旧的「【占位待定】」条目软删（deleted_at），可恢复；默认不动",
    )
    args = parser.parse_args()

    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            print(f"找不到项目 {args.project_code}", file=sys.stderr)
            return 2

        existing = db.scalars(
            select(Faq).where(
                Faq.project_id == project.id,
                Faq.deleted_at.is_(None),
            )
        ).all()
        existing_questions = {row.question.strip() for row in existing}

        placeholders = [row for row in existing if row.question.strip().startswith("【占位待定】")]
        to_add = [item for item in GAP_FAQS if item["question"] not in existing_questions]

        print(f"项目：{args.project_code}（{project.name}）")
        print(f"现有未删除 FAQ：{len(existing)} 条（其中占位符 {len(placeholders)} 条）")
        print(f"将新增缺口问题：{len(to_add)} 条")
        for index, item in enumerate(to_add, start=1):
            print(f"  {index}. [{item['category']}] {item['question']}")
        if args.remove_placeholders and placeholders:
            print(f"将软删占位符：{len(placeholders)} 条")
            for row in placeholders:
                print(f"  - {row.question}")
        if not args.remove_placeholders and placeholders:
            print("（旧占位符保留。确认它们没用后可加 --remove-placeholders 软删）")

        if not args.apply:
            print("\n[dry-run] 未写入。加 --apply 落库。")
            return 0

        now = datetime.now(timezone.utc)
        for item in to_add:
            db.add(
                Faq(
                    project_id=project.id,
                    question=item["question"],
                    answer=item["answer"],
                    category=item["category"],
                    status="draft",
                    sort_order=0,
                )
            )
        for row in placeholders if args.remove_placeholders else []:
            row.deleted_at = now
        db.commit()

        print(f"\n已写入：新增 {len(to_add)} 条" + (f"，软删占位符 {len(placeholders)} 条" if args.remove_placeholders else ""))
        print("状态均为 draft：确认答案前不进公开只读接口。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
