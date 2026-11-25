"""行业适配四问：只给建议，不阻断项目创建或内容生产。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project_policy import ProjectPolicy
from app.services.project_policy import policy_value

KEY = "adaptation.four_questions"

QUESTIONS = [
    {"key": "ai_demand", "label": "用户会不会经常向 AI 提问？", "hint": "有稳定的搜索/问答需求，而不是只能靠私域或线下触达。"},
    {"key": "comparison", "label": "用户需不需要比较和选择？", "hint": "存在多个可选服务商或产品，用户会找推荐、排名、区别。"},
    {"key": "fragmented_info", "label": "信息是否分散、需要整理？", "hint": "价格、地址、服务范围、资质散落在多处，AI 需要汇总后才好回答。"},
    {"key": "conversion", "label": "被提及后，是否可能带来咨询或成交？", "hint": "从 AI 答案到电话、到店、私信或下单有可走通的路径。"},
]

ANSWERS = {"yes": 2, "partial": 1, "no": 0, "unknown": None}
ANSWER_LABELS = {"yes": "是", "partial": "部分", "no": "否", "unknown": "不确定"}


def _verdict(evaluated: int, score: int | None) -> tuple[str, str]:
    if evaluated < 3 or score is None:
        return "insufficient", "有效回答不足 3 项，先补齐再判断"
    if score >= 7:
        return "prioritize", "四问支持优先布局 GEO"
    if score >= 4:
        return "pilot", "可小范围试点，先用一组问题验证 AI 是否提及"
    return "defer", "暂缓投入，先把需求或转化路径验证清楚"


def adaptation_report(db: Session, project_id: uuid.UUID) -> dict:
    raw = policy_value(db, project_id, KEY) or {}
    answers = raw.get("answers") if isinstance(raw, dict) else {}
    answers = answers if isinstance(answers, dict) else {}
    rows = []
    evaluated = 0
    score = 0
    for question in QUESTIONS:
        value = answers.get(question["key"], "unknown")
        if value not in ANSWERS:
            value = "unknown"
        points = ANSWERS[value]
        if points is not None:
            evaluated += 1
            score += points
        rows.append({**question, "answer": value, "answer_label": ANSWER_LABELS[value], "points": points})
    verdict, reason = _verdict(evaluated, score if evaluated else None)
    return {
        "evaluated": bool(evaluated),
        "answers": rows,
        "score": score if evaluated else None,
        "max_score": len(QUESTIONS) * 2,
        "evaluated_count": evaluated,
        "verdict": verdict,
        "verdict_label": {
            "insufficient": "信息不足", "prioritize": "优先布局",
            "pilot": "可试点", "defer": "暂缓",
        }[verdict],
        "reason": reason,
        "note": raw.get("note") if isinstance(raw, dict) else None,
        "evaluated_at": raw.get("evaluated_at") if isinstance(raw, dict) else None,
        "evaluated_by": raw.get("evaluated_by") if isinstance(raw, dict) else None,
        "disclaimer": "结论只作布局建议，不阻断建项目、不改变评分，也不代表平台实际收录。",
    }


def save_adaptation(
    db: Session,
    project_id: uuid.UUID,
    answers: dict,
    *,
    note: str | None = None,
    actor_id: uuid.UUID | None = None,
    apply: bool = True,
) -> dict:
    normalized: dict[str, str] = {}
    for question in QUESTIONS:
        value = answers.get(question["key"], "unknown")
        if value not in ANSWERS:
            raise ValueError(f"无效答案：{question['key']}={value}")
        normalized[question["key"]] = value
    payload = {
        "answers": normalized,
        "note": note,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "evaluated_by": str(actor_id) if actor_id else None,
    }
    if apply:
        row = db.scalar(
            select(ProjectPolicy).where(
                ProjectPolicy.project_id == project_id, ProjectPolicy.key == KEY
            )
        )
        if row is None:
            row = ProjectPolicy(project_id=project_id, key=KEY, value={"v": payload},
                                note=note, updated_by=actor_id)
            db.add(row)
        else:
            row.value = {"v": payload}
            row.note = note
            row.updated_by = actor_id
        db.commit()
    return adaptation_report(db, project_id)
