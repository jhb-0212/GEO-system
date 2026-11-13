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


# 与《广州基地GEO执行与系统开发计划》第 1 节一致：1 道品牌题 + 5 道通用题。
BASELINE_QUESTIONS: tuple[BaselineQuestion, ...] = (
    BaselineQuestion(
        code="Q01",
        question_type=QuestionType.BRAND,
        text="广东省AI数字人才就业实训基地在广州哪里，怎么报名？",
        audience="意向学员及家长",
        intent="核对基地全称、广州地址与报名入口",
    ),
    BaselineQuestion(
        code="Q02",
        question_type=QuestionType.GENERAL,
        text="广州有哪些适合零基础、可以现场做项目的 AI 实训？",
        audience="零基础转行者",
        intent="寻找可现场做项目的广州 AI 实训",
    ),
    BaselineQuestion(
        code="Q03",
        question_type=QuestionType.GENERAL,
        text="零基础怎么从脚本做出一条 AI 短视频？",
        audience="零基础短视频学习者",
        intent="学习 AI 短视频制作流程",
    ),
    BaselineQuestion(
        code="Q04",
        question_type=QuestionType.GENERAL,
        text="大模型能怎么做办公自动化，实训成果怎么验收？",
        audience="在职办公人群",
        intent="学习大模型办公自动化并验收成果",
    ),
    BaselineQuestion(
        code="Q05",
        question_type=QuestionType.GENERAL,
        text="学完 AIGC 能应聘什么岗位，作品集怎么准备？",
        audience="求职与转行学员",
        intent="了解 AIGC 岗位与作品集准备",
    ),
    BaselineQuestion(
        code="Q06",
        question_type=QuestionType.GENERAL,
        text="广州 AI 实训怎么收费，要学多久？",
        audience="比价阶段学员及家长",
        intent="比较课程费用与学习周期",
    ),
)

BASELINE_VERSION_NO = 2


def activate_technical_baseline(
    session: Session,
    project_code: str,
    *,
    dry_run: bool = False,
) -> dict:
    """把目标项目的 6 题切成技术基线 v2。

    幂等：v2 已存在时只补齐题目状态/画像，不改写 v2 正文。
    """
    project = session.scalar(select(Project).where(Project.code == project_code))
    if project is None:
        raise ValueError(f"项目不存在：{project_code}")

    questions = {
        row.code: row
        for row in session.scalars(select(Question).where(Question.project_id == project.id))
    }
    missing = [item.code for item in BASELINE_QUESTIONS if item.code not in questions]
    if missing:
        raise ValueError(f"项目 {project_code} 缺少题目：{missing}")

    rows: list[dict] = []
    created_versions = 0
    already_active = 0

    for item in BASELINE_QUESTIONS:
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
