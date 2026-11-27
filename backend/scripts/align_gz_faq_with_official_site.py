"""把广州基地的系统 FAQ 对齐官网 /faq（2026-11-25 版，共 12 条）。

背景：系统里的 FAQ 之前装的是“官网没回答的缺口问题”（学费、开班、退款边界等），
多为 draft 占位。2026-11-27 官网已上线独立 /faq，公开了选班、零基础、保障、费用、
学习流程、企业合作共 12 条口径。继续维护第二套缺口题库会产生两个真源，因此这里
以官网文本为准做一次对齐：

1. 官网 12 条按原分类、原顺序写入 faqs，状态 published；
2. 官网没有的旧 FAQ 软删（status=unpublished + deleted_at），保留历史，不物理删除；
3. 已存在同问题则原地更新，可重复执行。

用法（backend 目录）：
    .\\.venv\\Scripts\\python.exe scripts\\align_gz_faq_with_official_site.py --project-code gz-base --dry-run
    .\\.venv\\Scripts\\python.exe scripts\\align_gz_faq_with_official_site.py --project-code gz-base --apply
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models import Faq, Project  # noqa: E402
from app.models.enums import FaqStatus  # noqa: E402
from app.services.audit import record_audit  # noqa: E402

# 官网 https://www.gdccai.com/faq 原文，最后更新 2026-11-25。
OFFICIAL_FAQS: list[dict[str, str | int]] = [
    {
        "category": "选班",
        "sort_order": 1,
        "question": "两个班型怎么选？",
        "answer": (
            "偏内容生产选 AIGC 生成式人工智能全栈就业班（约 2 个月），出片、剪辑、"
            "账号运营方向；有编程基础、想做应用与 Agent 开发选 AI 大模型全链路开发"
            "全栈就业班（约 3 个月）。两边都要求全日制到场、每周过一次作品评审。"
        ),
    },
    {
        "category": "选班",
        "sort_order": 2,
        "question": "零基础能报名吗？",
        "answer": (
            "AIGC 班可以零基础，但要求每天到场并完成当周作业；大模型班需要能读写 Python、"
            "看得懂接口文档。报名前有一次基础测评，测不过会建议先补基础或改班型。"
        ),
    },
    {
        "category": "选班",
        "sort_order": 3,
        "question": "可以只学某几个模块吗？",
        "answer": (
            "不拆卖。课程按阶段推进，每个阶段产出都是下一阶段的输入，跳阶段会导致成片"
            "或项目做不完。想单点补技能可以问是否有短期工作坊，但不计入实训班。"
        ),
    },
    {
        "category": "选班",
        "sort_order": 4,
        "question": "上课时间怎么安排？",
        "answer": (
            "全日制，周中白天为主，晚上和周末安排答疑与自习。具体作息以当期课表为准，"
            "报到前会发完整日历。"
        ),
    },
    {
        "category": "保障",
        "sort_order": 5,
        "question": "就业保障具体保什么？",
        "answer": (
            "保三件事：一是周期——按协议约定完成全部课程与作品；二是推荐次数与岗位口径"
            "——写明推荐岗位范围与推荐轮次；三是未就业的处理方式——符合协议条件但未按"
            "约定就业的，按协议全额退费。以上全部以签订的协议文本为准，不做口头承诺。"
        ),
    },
    {
        "category": "保障",
        "sort_order": 6,
        "question": "保薪资是真的吗？",
        "answer": (
            "我们只在协议里写「起薪口径」的计算方式与达成条件，不承诺一个具体数字。"
            "宣传里出现的任何薪资都是往期样本，不是对个人的保证。"
        ),
    },
    {
        "category": "费用",
        "sort_order": 7,
        "question": "学费包含什么？",
        "answer": (
            "学费含课程、机房设备与算力额度、作品评审、就业推荐服务；不含住宿、餐饮与"
            "个人设备。当期报价与退费条款以报价单和协议为准，任何口头折扣都不作数。"
        ),
    },
    {
        "category": "费用",
        "sort_order": 8,
        "question": "中途退出怎么处理？",
        "answer": (
            "按协议里的退费条款分阶段处理：开课前、开课后前两周、以及进度过半之后的标准"
            "不同。走流程需要书面申请，退款节点写进协议，不接受事后议价。"
        ),
    },
    {
        "category": "学习流程",
        "sort_order": 9,
        "question": "每周评审不过会怎样？",
        "answer": (
            "当周作品不达标不进入下一阶段，助教会给出具体返工项，最多两次补评；仍不达标"
            "会和学员一起判断是换方向还是转班型，不把人硬推到结课。"
        ),
    },
    {
        "category": "学习流程",
        "sort_order": 10,
        "question": "作品集是自己做的还是套模板？",
        "answer": (
            "自己做的，模板只用于讲结构。结课要求交付一部完整漫剧或一组可上线项目，并附"
            "生成参数与迭代记录，目的是让作品可复现、面试时讲得清过程。"
        ),
    },
    {
        "category": "合作与企业",
        "sort_order": 11,
        "question": "企业能直接来选人吗？",
        "answer": (
            "可以。合作企业可参加结课作品评审并现场看片，也可以定向提需求。我们只负责"
            "组织与背调，录用决定由企业做。"
        ),
    },
    {
        "category": "合作与企业",
        "sort_order": 12,
        "question": "能给我们公司做内训吗？",
        "answer": (
            "可以，按团队现有工具链设计 1–5 天的专题内训，内容偏落地：把你们真实的素材"
            "和项目拿进来做，不做通用宣讲。具体排期跟联系页表单或电话沟通。"
        ),
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-code", required=True)
    parser.add_argument("--apply", action="store_true", help="真正写库；不加只预演")
    parser.add_argument("--dry-run", action="store_true", help="只预演，不改库（默认行为）")
    args = parser.parse_args()
    if args.project_code != "gz-base":
        raise SystemExit("本脚本只适用于广州基地（gz-base）的官网 FAQ 对齐")

    with Session(create_engine(settings.database_url)) as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            raise SystemExit(f"找不到项目 {args.project_code}")

        all_rows = db.scalars(select(Faq).where(Faq.project_id == project.id)).all()
        active = [row for row in all_rows if row.deleted_at is None]
        by_question = {row.question.strip(): row for row in all_rows}
        official_questions = {str(item["question"]).strip() for item in OFFICIAL_FAQS}

        to_add = [item for item in OFFICIAL_FAQS if str(item["question"]).strip() not in by_question]
        to_retire = [row for row in active if row.question.strip() not in official_questions]

        print(f"项目：{args.project_code}（{project.name}）")
        print(f"现有未删除 FAQ：{len(active)} 条；其中将被官网版本替换/归档：{len(to_retire)} 条")
        for row in to_retire:
            print(f"  - [{row.status}] {row.question}")
        print(f"官网 12 条中需要新增：{len(to_add)} 条")
        for item in to_add:
            print(f"  + [{item['category']}] {item['question']}")

        if not args.apply:
            print("\n[dry-run] 未写入。确认后加 --apply。")
            return 0

        now = datetime.now(UTC)
        for row in to_retire:
            row.status = FaqStatus.UNPUBLISHED
            row.deleted_at = now
            row.deleted_by = None
            row.review_comment = "被官网 /faq（2026-11-25）对齐替换"

        for item in OFFICIAL_FAQS:
            question = str(item["question"]).strip()
            row = by_question.get(question)
            if row is None:
                row = Faq(
                    project_id=project.id,
                    question=question,
                    answer=str(item["answer"]),
                    category=str(item["category"]),
                    status=FaqStatus.PUBLISHED,
                    sort_order=int(item["sort_order"]),
                    reviewed_at=now,
                    review_comment="对齐官网 /faq（2026-11-25）",
                )
                db.add(row)
            else:
                row.answer = str(item["answer"])
                row.category = str(item["category"])
                row.sort_order = int(item["sort_order"])
                row.status = FaqStatus.PUBLISHED
                row.deleted_at = None
                row.deleted_by = None
                row.reviewed_at = now
                row.review_comment = "对齐官网 /faq（2026-11-25）"

        record_audit(
            db,
            project_id=project.id,
            actor_id=None,
            action="faq.align_official_site",
            target_type="faq_batch",
            payload={
                "source_url": "https://www.gdccai.com/faq",
                "source_last_updated": "2026-11-25",
                "official_count": len(OFFICIAL_FAQS),
                "retired_count": len(to_retire),
            },
        )
        db.commit()
        print(f"\n已写入：官网 FAQ {len(OFFICIAL_FAQS)} 条（published），归档旧 FAQ {len(to_retire)} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
