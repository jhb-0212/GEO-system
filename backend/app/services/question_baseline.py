"""首期 6 题的技术基线激活。

设计口径：
- 题目身份用稳定的 code（Q01–Q06），问法放在 question_versions；
- 旧占位版本 v1 不覆盖、不删除，技术基线写成 v2；
- ``status=active`` 只表示“进入监测”，不表示“运营已定稿”；
- 运营确认后继续追加 v3，历史轮次仍由 monitoring_tasks.question_version_id 锁定旧版本。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, Question, QuestionVersion
from app.models.enums import QuestionStatus, QuestionType


@dataclass(frozen=True)
class BaselineQuestion:
    code: str
    question_type: QuestionType
    text: str
    audience: str
    intent: str
    priority: int = 100

    @property
    def change_note(self) -> str:
        return "technical-baseline-v1"


from app.services.industry_presets import default_terms, project_industry_config


def _build_questions(rows: list[dict]) -> tuple[BaselineQuestion, ...]:
    return tuple(
        BaselineQuestion(
            code=row["code"],
            question_type=QuestionType(row["question_type"]),
            text=row["text"],
            audience=row.get("audience", ""),
            intent=row.get("intent", ""),
            priority=int(row.get("priority", 100)),
        )
        for row in rows
    )


# 默认基线题目来自行业预设；项目策略可在 `baseline_questions` 下整组覆盖。
BASELINE_QUESTIONS: tuple[BaselineQuestion, ...] = _build_questions(
    default_terms("baseline_questions", []) or []
)

BASELINE_VERSION_NO = 2


def activate_technical_baseline(
    session: Session,
    project_code: str,
    *,
    dry_run: bool = False,
    questions_override: list[dict] | None = None,
) -> dict:
    """把目标项目的 6 题切成技术基线 v2。

    幂等：v2 已存在时只补齐题目状态/画像，不改写 v2 正文。
    """
    project = session.scalar(select(Project).where(Project.code == project_code))
    if project is None:
        raise ValueError(f"项目不存在：{project_code}")

    config = project_industry_config(session, project.id)
    rows_cfg = questions_override or config.get("baseline_questions") or []
    baseline = _build_questions(rows_cfg) if rows_cfg else BASELINE_QUESTIONS
    questions = {
        row.code: row
        for row in session.scalars(select(Question).where(Question.project_id == project.id))
    }
    missing = [item.code for item in baseline if item.code not in questions]
    if missing:
        raise ValueError(f"项目 {project_code} 缺少题目：{missing}")

    rows: list[dict] = []
    created_versions = 0
    already_active = 0

    for item in baseline:
        question = questions[item.code]
        version = session.scalar(
            select(QuestionVersion).where(
                QuestionVersion.question_id == question.id,
                QuestionVersion.version_no == BASELINE_VERSION_NO,
            )
        )
        version_created = False

        if version is None:
            version_created = True
            created_versions += 1
            if not dry_run:
                session.add(
                    QuestionVersion(
                        project_id=project.id,
                        question_id=question.id,
                        version_no=BASELINE_VERSION_NO,
                        text=item.text,
                        change_note=item.change_note,
                    )
                )
                session.flush()
        elif version.text.strip() != item.text.strip():
            raise ValueError(
                f"{project_code}/{item.code} 已存在 v{BASELINE_VERSION_NO}，"
                "正文与技术基线不一致；拒绝静默覆盖，请改用新版本"
            )

        if question.status == QuestionStatus.ACTIVE and question.current_version_no == BASELINE_VERSION_NO:
            already_active += 1

        if not dry_run:
            question.title = item.text
            question.question_type = item.question_type
            question.audience = item.audience
            question.intent = item.intent
            question.priority = item.priority
            question.status = QuestionStatus.ACTIVE
            question.current_version_no = BASELINE_VERSION_NO

        rows.append(
            {
                "code": item.code,
                "text": item.text,
                "question_type": item.question_type.value,
                "status": QuestionStatus.ACTIVE.value,
                "version_no": BASELINE_VERSION_NO,
                "version_created": version_created,
            }
        )

    if not dry_run:
        session.flush()

    return {
        "project_code": project_code,
        "baseline": "technical-baseline-v1",
        "activated": len(BASELINE_QUESTIONS),
        "created_versions": created_versions,
        "already_active": already_active,
        "dry_run": dry_run,
        "questions": rows,
    }
