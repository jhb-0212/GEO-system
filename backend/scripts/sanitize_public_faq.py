"""按公开口径清理 FAQ：报名费用、具体开班日期、退款边界不对外公开。

- 两条已 published 的 FAQ 去掉费用/开班日期表述，保留地址、学制、住宿与设备安排等可公开信息；
- 其余 published FAQ 若命中费用/开班/退款等敏感词，降为 draft，不进入公开接口。

用法（仓库根目录，仅适用于广州基地）：
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\sanitize_public_faq.py --project-code gz-base --dry-run
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\sanitize_public_faq.py --project-code gz-base --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Faq, Project, ProjectMember
from app.models.enums import FaqStatus, ProjectStatus
from app.services.audit import record_audit

DEFAULT_PROJECT_CODE = ""  # 必须显式传 --project-code，本脚本仅适用于广州基地
FORBIDDEN_TERMS = ("学费", "费用", "开班", "退款", "退费", "价格", "收费", "报名费")

REWRITES = {
    # 学制/课时可公开，具体开班日期不公开
    "1bc68768-bf29-4194-a254-5edf507fe851": (
        "AIGC 定向实训约 8 周、400 课时；AI 大模型领航实训近 3 个月、660 课时。"
        "具体上课安排以课程顾问通知为准。"
    ),
    # 住宿/设备安排可公开，费用标准不公开
    "5591e235-1616-425c-8279-c556738bd90f": (
        "基地可提供周边宿舍房源信息与对接，外地学员可入住；笔记本电脑可自带，也可在基地租赁。"
        "住宿与设备租赁的具体安排，以课程顾问确认为准。"
    ),
}


def _hits(text: str) -> list[str]:
    return [term for term in FORBIDDEN_TERMS if term in text]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-code", required=True, help="项目 code，必须显式指定；本脚本仅适用于广州基地")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("--apply 与 --dry-run 不能同时使用")

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None or project.status != ProjectStatus.ACTIVE:
            print(f"项目不存在或未启用：{args.project_code}")
            return 2
        actor = db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.is_active.is_(True),
            )
        )
        rows = db.scalars(
            select(Faq).where(
                Faq.project_id == project.id,
                Faq.status == FaqStatus.PUBLISHED,
                Faq.deleted_at.is_(None),
            )
        ).all()
        print(f"published FAQ: {len(rows)}")

        changed = 0
        for row in rows:
            before = {"question": row.question, "answer": row.answer, "status": row.status}
            if str(row.id) in REWRITES:
                answer = REWRITES[str(row.id)]
                if row.answer != answer:
                    print(f"REWRITE {row.id} {row.question}")
                    if args.apply:
                        row.answer = answer
                        record_audit(
                            db,
                            project_id=project.id,
                            actor_id=actor.user_id if actor else None,
                            action="faq.public_scope_update",
                            target_type="faq",
                            target_id=row.id,
                            payload={"before": before, "after": {"answer": answer}},
                        )
                    changed += 1
                continue

            hits = _hits(f"{row.question}\n{row.answer}")
            if hits:
                print(f"UNPUBLISH {row.id} {row.question} hits={hits}")
                if args.apply:
                    row.status = FaqStatus.DRAFT
                    record_audit(
                        db,
                        project_id=project.id,
                        actor_id=actor.user_id if actor else None,
                        action="faq.public_scope_unpublish",
                        target_type="faq",
                        target_id=row.id,
                        payload={"before": before, "hits": hits},
                    )
                changed += 1

        if args.apply:
            db.commit()
        print(f"{'APPLY' if args.apply else 'DRY'} changed={changed}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
