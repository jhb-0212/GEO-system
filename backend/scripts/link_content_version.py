"""给内容版本挂目标词 / 题目 / 证据（母稿-渠道稿这条链的另一半）。

## 背景

`content_version_keywords` / `content_version_questions` / `content_version_citations`
三张表长期是 0 行。但这不是"缺工具"，是**没有真实内容可挂**：库里仅有的 2 条内容
都是联调草稿（一条正文 15 字、一条夹着未核实的场地面积），给它们挂业务关联会直接
污染"内容覆盖目标词"的判断——以后看覆盖率，看到的是测试数据的覆盖。

所以这个脚本刻意做成**显式挂接 + 可疑稿警告**，不做"按字面自动全挂"：

- `--keywords` / `--questions` / `--citations` 都必须由人指定，脚本只给建议；
- 正文过短（< 200 字）或标题含"联调/测试/mock"时打印警告，提醒这不是可发布内容；
- 幂等：已存在的关联跳过，重复跑不产生重复行。

## 用法

先看一条版本的现状与建议（不写库）：

    ... --version 交付包联调-2026-11-17
    ... --version 09ad3e29            # 也可以用 id 前 8 位

确认后挂接：

    ... --version <id> --keywords 广州 AI 实训费用,AIGC 实训周期 --questions Q06 --apply
    ... --version <id> --keywords "广州 AI 就业实训" --questions Q05 --citations <citation_id> --apply

## 判断标准（写内容时对齐这条）

一条版本挂哪个词，看它**回答的是哪道题**，而不是看正文里碰巧出现了哪个词的字面。
字面命中只作为提示，不能作为依据——否则品牌名"AI数字人才就业实训基地"会让每篇稿子
都命中"就业"。
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import (
    ContentItem,
    ContentVersion,
    ContentVersionCitation,
    ContentVersionKeyword,
    ContentVersionQuestion,
    Keyword,
    Project,
    Question,
    QuestionKeyword,
)
from app.models.enums import ContentStatus

SUSPICIOUS_MARKERS = ("联调", "测试", "mock", "demo", "样例数据")
MIN_BODY_LEN = 200


def _resolve_version(db: Session, project: Project, token: str) -> ContentVersion | None:
    """支持完整 id、id 前 8 位、或标题片段。"""
    candidates: list[ContentVersion] = []
    try:
        uid = uuid.UUID(token)
        candidates = list(
            db.scalars(
                select(ContentVersion).where(
                    ContentVersion.project_id == project.id, ContentVersion.id == uid
                )
            ).all()
        )
    except ValueError:
        pass

    if not candidates and len(token) <= 12:
        rows = db.scalars(
            select(ContentVersion).where(ContentVersion.project_id == project.id)
        ).all()
        candidates = [r for r in rows if str(r.id).startswith(token.lower())]

    if not candidates:
        rows = db.execute(
            select(ContentVersion, ContentItem)
            .join(ContentItem, ContentItem.id == ContentVersion.item_id)
            .where(ContentVersion.project_id == project.id)
        ).all()
        candidates = [v for v, item in rows if token in item.title]

    if len(candidates) > 1:
        print(f"匹配到 {len(candidates)} 个版本，请用 id 指定其中一个：", file=sys.stderr)
        for v in candidates:
            print(f"  {v.id}  v{v.version_no}  {v.status.value}", file=sys.stderr)
        return None
    return candidates[0] if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-code", default="gz-base")
    parser.add_argument("--version", required=True, help="版本 id（全或前 8 位）、标题片段，或 all 列出全部")
    parser.add_argument("--keywords", help="目标词名，逗号分隔（必须与 keywords 表里的名字完全一致）")
    parser.add_argument("--questions", help="题目 code，逗号分隔（如 Q06）")
    parser.add_argument("--citations", help="引用 id，逗号分隔（可选，证据追溯用）")
    parser.add_argument("--apply", action="store_true", help="真正写库；不加只预演")
    args = parser.parse_args()

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            print(f"找不到项目 {args.project_code}", file=sys.stderr)
            return 2

        keywords = {
            row.name: row
            for row in db.scalars(select(Keyword).where(Keyword.project_id == project.id)).all()
        }
        questions = {
            row.code: row
            for row in db.scalars(select(Question).where(Question.project_id == project.id)).all()
        }

        if args.version == "all":
            rows = db.execute(
                select(ContentVersion, ContentItem)
                .join(ContentItem, ContentItem.id == ContentVersion.item_id)
                .where(ContentVersion.project_id == project.id)
                .order_by(ContentVersion.created_at)
            ).all()
            print(f"{'版本':<12}{'状态':<10}{'正文字数':>6}  标题")
            for version, item in rows:
                body = version.body or ""
                flag = ""
                if len(body) < MIN_BODY_LEN or any(m in item.title for m in SUSPICIOUS_MARKERS):
                    flag = "  ⚠ 疑似联调/过短"
                print(f"{str(version.id)[:8]:<12}{version.status.value:<10}{len(body):>6}  {item.title}{flag}")
            print("\n用 --version <id前8位> 查看单条并挂接。")
            return 0

        version = _resolve_version(db, project, args.version)
        if version is None:
            print("找不到匹配的版本。", file=sys.stderr)
            return 2
        item = db.scalar(select(ContentItem).where(ContentItem.id == version.item_id))
        body = version.body or ""

        print(f"版本 {str(version.id)[:8]} v{version.version_no}（{version.status.value}）")
        print(f"内容：{item.title if item else '(无标题)'}  正文字数：{len(body)}")

        warnings: list[str] = []
        if len(body) < MIN_BODY_LEN:
            warnings.append(f"正文仅 {len(body)} 字（< {MIN_BODY_LEN}），不像可发布内容")
        if item and any(m in item.title for m in SUSPICIOUS_MARKERS):
            warnings.append("标题含『联调/测试』字样，疑似联调稿")
        if warnings:
            print("\n⚠ " + "；".join(warnings))
            print("  给这种版本挂业务关联会污染内容覆盖率统计，建议先归档或用真实稿挂接。")

        # 建议：字面命中的目标词（只作提示，不作依据）
        hits = [name for name in keywords if name in body]
        print(f"\n正文里字面出现的目标词：{('、'.join(hits)) if hits else '无'}")
        print("  注意：字面命中不等于该挂。判据是『这条内容回答的是哪道题』。")

        # 现有题目 → 其挂载的目标词，便于人工判断
        # 现有题目 → 其挂载的目标词，便于人工判断（一次查询后内存分组，避免 N×M 次查库）
        keyword_names = {kw.id: name for name, kw in keywords.items()}
        links = db.execute(
            select(QuestionKeyword.question_id, QuestionKeyword.keyword_id).where(
                QuestionKeyword.keyword_id.in_(list(keyword_names))
            )
        ).all()
        keywords_by_question: dict[uuid.UUID, set[str]] = {}
        for question_id, keyword_id in links:
            name = keyword_names.get(keyword_id)
            if name:
                keywords_by_question.setdefault(question_id, set()).add(name)

        print("\n可供挂接的题目与目标词：")
        for code, question in sorted(questions.items()):
            kw_names = sorted(keywords_by_question.get(question.id, ()))
            print(f"  {code}  {question.title[:30]}  → {' / '.join(kw_names) or '(未挂词)'}")

        want_keywords = [k.strip() for k in (args.keywords or "").split(",") if k.strip()]
        want_questions = [q.strip() for q in (args.questions or "").split(",") if q.strip()]
        want_citations = [c.strip() for c in (args.citations or "").split(",") if c.strip()]

        unknown_kw = [k for k in want_keywords if k not in keywords]
        if unknown_kw:
            print(f"\n目标词不存在于 keywords 表：{unknown_kw}", file=sys.stderr)
            return 2
        unknown_q = [q for q in want_questions if q not in questions]
        if unknown_q:
            print(f"\n题目不存在：{unknown_q}", file=sys.stderr)
            return 2

        existing_kw = {
            row.keyword_id
            for row in db.scalars(
                select(ContentVersionKeyword).where(ContentVersionKeyword.version_id == version.id)
            ).all()
        }
        existing_q = {
            row.question_id
            for row in db.scalars(
                select(ContentVersionQuestion).where(ContentVersionQuestion.version_id == version.id)
            ).all()
        }
        existing_c = {
            row.citation_id
            for row in db.scalars(
                select(ContentVersionCitation).where(ContentVersionCitation.version_id == version.id)
            ).all()
        }

        print("\n待挂接：")
        for name in want_keywords:
            mark = "（已存在）" if keywords[name].id in existing_kw else "+"
            print(f"  {mark} 目标词 {name}")
        for code in want_questions:
            mark = "（已存在）" if questions[code].id in existing_q else "+"
            print(f"  {mark} 题目 {code}")
        for cid in want_citations:
            print(f"  + 证据引用 {cid}")
        if not (want_keywords or want_questions or want_citations):
            print("  （未指定 --keywords / --questions / --citations，无事可做）")
            return 0

        if not args.apply:
            print("\n[dry-run] 未写入。确认无误后加 --apply。")
            return 0

        added = 0
        for name in want_keywords:
            kw = keywords[name]
            if kw.id in existing_kw:
                continue
            db.add(
                ContentVersionKeyword(
                    project_id=project.id, version_id=version.id, keyword_id=kw.id
                )
            )
            added += 1
        for code in want_questions:
            q = questions[code]
            if q.id in existing_q:
                continue
            db.add(
                ContentVersionQuestion(
                    project_id=project.id, version_id=version.id, question_id=q.id
                )
            )
            added += 1
        for cid in want_citations:
            try:
                cuuid = uuid.UUID(cid)
            except ValueError:
                print(f"引用 id 不合法：{cid}，整批未提交。", file=sys.stderr)
                db.rollback()
                return 2
            if cuuid in existing_c:
                continue
            db.add(
                ContentVersionCitation(
                    project_id=project.id, version_id=version.id, citation_id=cuuid
                )
            )
            added += 1
        db.commit()
        print(f"\n已写入 {added} 条关联。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
