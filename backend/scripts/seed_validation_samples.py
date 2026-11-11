"""边界校验数据：失败监测任务、待复核证据、未知域名、跨项目同码记录。

放在独立项目 edge-validation，不污染 gz-base 的验收基线。
脚本幂等，可重复执行；所有记录都带 project_id，可直接用于隔离校验。

用法（backend 目录）：
    .venv\\Scripts\\python.exe scripts\\seed_validation_samples.py
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AiEngineEntry,
    Channel,
    EvidenceFile,
    Lead,
    MonitoringCitation,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
)
from app.models.enums import (  # noqa: E402
    ChannelCategory,
    ChannelStatus,
    CitationReviewStatus,
    EvidenceFileType,
    FailureCode,
    QuestionStatus,
    QuestionType,
    RoundStatus,
    SampleStatus,
    SamplingMode,
    TaskStatus,
)

EDGE_PROJECT_CODE = "edge-validation"
EDGE_PROJECT_NAME = "边界校验项目"
CROSS_CODES = {"question": "Q01", "channel": "36kr"}
CROSS_PHONE = "13900008888"


def get_or_create_project(session) -> Project:
    project = session.scalar(select(Project).where(Project.code == EDGE_PROJECT_CODE))
    if project:
        return project
    project = Project(code=EDGE_PROJECT_CODE, name=EDGE_PROJECT_NAME)
    session.add(project)
    session.flush()
    return project


def get_or_create_question(session, project: Project) -> QuestionVersion:
    question = session.scalar(
        select(Question).where(Question.project_id == project.id, Question.code == CROSS_CODES["question"])
    )
    if question is None:
        question = Question(
            project_id=project.id,
            code=CROSS_CODES["question"],
            title="跨项目隔离校验：与 gz-base 同 code 的题目",
            question_type=QuestionType.GENERAL,
            priority=100,
            status=QuestionStatus.DRAFT,
            current_version_no=1,
        )
        session.add(question)
        session.flush()
    version = session.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == question.id,
            QuestionVersion.version_no == 1,
        )
    )
    if version is None:
        version = QuestionVersion(
            project_id=project.id,
            question_id=question.id,
            version_no=1,
            text=question.title,
            change_note="边界校验夹具",
        )
        session.add(version)
        session.flush()
    return version


def get_or_create_channel(session, project: Project, code: str, name: str, domain: str | None,
                          status: ChannelStatus) -> Channel:
    channel = session.scalar(
        select(Channel).where(Channel.project_id == project.id, Channel.code == code)
    )
    if channel:
        return channel
    channel = Channel(
        project_id=project.id,
        code=code,
        name=name,
        category=ChannelCategory.CONTENT_PLATFORM,
        status=status,
        primary_domain=domain,
        notes="边界校验夹具",
    )
    session.add(channel)
    session.flush()
    return channel


def get_or_create_lead(session, project: Project) -> Lead:
    lead = session.scalar(
        select(Lead).where(
            Lead.project_id == project.id,
            Lead.contact_phone == CROSS_PHONE,
        )
    )
    if lead:
        return lead
    lead = Lead(
        project_id=project.id,
        contact_name="跨项目同手机号线索",
        contact_phone=CROSS_PHONE,
        contact_wechat="edge_cross_wx",
        interested_course="边界校验",
        lead_source="edge_sample",
        note="与 gz-base 无同号线索，用于证明 project_id 过滤",
    )
    session.add(lead)
    session.flush()
    return lead


def get_or_create_round(session, project: Project) -> MonitoringRound:
    item = session.scalar(
        select(MonitoringRound).where(
            MonitoringRound.project_id == project.id,
            MonitoringRound.seq == 1,
        )
    )
    if item:
        return item
    item = MonitoringRound(
        project_id=project.id,
        seq=1,
        name="边界校验轮次",
        is_baseline=False,
        planned_at=datetime.now(timezone.utc),
        status=RoundStatus.COMPLETED,
    )
    session.add(item)
    session.flush()
    return item


def get_or_create_task(session, project: Project, round_item: MonitoringRound, version: QuestionVersion,
                       entry: AiEngineEntry, sampling_no: int, status: TaskStatus) -> MonitoringTask:
    task = session.scalar(
        select(MonitoringTask).where(
            MonitoringTask.round_id == round_item.id,
            MonitoringTask.question_version_id == version.id,
            MonitoringTask.engine_entry_id == entry.id,
            MonitoringTask.sampling_no == sampling_no,
        )
    )
    if task:
        return task
    task = MonitoringTask(
        project_id=project.id,
        round_id=round_item.id,
        question_version_id=version.id,
        engine_entry_id=entry.id,
        sampling_no=sampling_no,
        sampling_mode=SamplingMode.SEARCH_ON,
        status=status,
        planned_at=datetime.now(timezone.utc),
    )
    session.add(task)
    session.flush()
    return task


def get_or_create_sample(session, project: Project, task: MonitoringTask, status: SampleStatus,
                         failure_code: FailureCode | None = None,
                         failure_note: str | None = None,
                         brand_mentioned: bool | None = None) -> MonitoringSample:
    sample = session.scalar(
        select(MonitoringSample).where(
            MonitoringSample.task_id == task.id,
            MonitoringSample.attempt_no == 1,
        )
    )
    if sample:
        return sample
    sample = MonitoringSample(
        project_id=project.id,
        task_id=task.id,
        attempt_no=1,
        status=status,
        sampled_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        sampling_mode=SamplingMode.SEARCH_ON,
        raw_answer="边界校验用原始回答：提到广州 AI 实训基地。",
        brand_mentioned=brand_mentioned,
        failure_code=failure_code,
        failure_note=failure_note,
    )
    session.add(sample)
    session.flush()
    return sample


def get_or_create_citation(session, project: Project, sample: MonitoringSample, url: str,
                          domain: str) -> MonitoringCitation:
    citation = session.scalar(
        select(MonitoringCitation).where(
            MonitoringCitation.project_id == project.id,
            MonitoringCitation.sample_id == sample.id,
            MonitoringCitation.raw_url == url,
        )
    )
    if citation:
        return citation
    citation = MonitoringCitation(
        project_id=project.id,
        sample_id=sample.id,
        raw_url=url,
        normalized_url=url,
        domain=domain,
        channel_id=None,
        is_brand_related=True,
        review_status=CitationReviewStatus.AUTO,
        review_note="未知域名，待人工归类",
    )
    session.add(citation)
    session.flush()
    return citation


def get_or_create_evidence(session, project: Project, sample: MonitoringSample, key: str) -> EvidenceFile:
    item = session.scalar(
        select(EvidenceFile).where(
            EvidenceFile.project_id == project.id,
            EvidenceFile.storage_key == key,
        )
    )
    if item:
        return item
    item = EvidenceFile(
        project_id=project.id,
        sample_id=sample.id,
        storage_key=key,
        file_type=EvidenceFileType.SCREENSHOT,
        checksum="0" * 64,
        byte_size=1024,
        content_type="image/png",
    )
    session.add(item)
    session.flush()
    return item


def main() -> None:
    session = SessionLocal()
    try:
        project = get_or_create_project(session)
        version = get_or_create_question(session, project)

        # 跨项目同 code 渠道：gz-base 已有 36kr，这里再建一条同 code
        get_or_create_channel(
            session, project, CROSS_CODES["channel"], "36氪（边界副本）", "36kr.com", ChannelStatus.CANDIDATE
        )
        # 未知域名，待归类队列
        for index in range(1, 4):
            domain = f"unknown-{index}.edge.example"
            get_or_create_channel(
                session, project, f"edge-unknown-{index:02d}", f"未知域名 {index}", domain,
                ChannelStatus.REVIEW_PENDING,
            )
        get_or_create_lead(session, project)

        round_item = get_or_create_round(session, project)
        engine_entries = list(
            session.scalars(select(AiEngineEntry).where(AiEngineEntry.is_active.is_(True)).order_by(AiEngineEntry.name))
        )
        if len(engine_entries) < 4:
            raise SystemExit(f"可用引擎入口不足 4 个，实际 {len(engine_entries)}")

        # 3 条失败监测任务，failure_code 各不相同
        failure_cases = [
            (FailureCode.TIMEOUT, "目标站点 30s 未返回"),
            (FailureCode.CAPTCHA, "出现验证码，转人工"),
            (FailureCode.ACCESS_BLOCKED, "返回 403，访问被拦截"),
        ]
        failed_sample_ids = []
        for index, (code, note) in enumerate(failure_cases):
            task = get_or_create_task(
                session, project, round_item, version, engine_entries[index], index + 1, TaskStatus.FAILED
            )
            sample = get_or_create_sample(
                session, project, task, SampleStatus.FAILED,
                failure_code=code, failure_note=note, brand_mentioned=False,
            )
            failed_sample_ids.append(sample.id)

        # 2 条待人工复核样本，各带 1 条 auto 引用和 1 个证据文件
        manual_sample_ids = []
        for index in range(2):
            task = get_or_create_task(
                session, project, round_item, version, engine_entries[index], index + 4, TaskStatus.DONE
            )
            sample = get_or_create_sample(
                session, project, task, SampleStatus.MANUAL_REVIEW, brand_mentioned=True
            )
            manual_sample_ids.append(sample.id)
            get_or_create_citation(
                session, project, sample,
                f"https://unknown-{index + 1}.edge.example/post/{index + 1}",
                f"unknown-{index + 1}.edge.example",
            )
            get_or_create_evidence(session, project, sample, f"edge/evidence/{sample.id}.png")

        session.commit()

        counts = {
            "questions": session.scalar(
                select(func.count()).select_from(Question).where(Question.project_id == project.id)
            ),
            "channels": session.scalar(
                select(func.count()).select_from(Channel).where(Channel.project_id == project.id)
            ),
            "leads": session.scalar(
                select(func.count()).select_from(Lead).where(Lead.project_id == project.id)
            ),
            "rounds": session.scalar(
                select(func.count()).select_from(MonitoringRound).where(MonitoringRound.project_id == project.id)
            ),
            "tasks": session.scalar(
                select(func.count()).select_from(MonitoringTask).where(MonitoringTask.project_id == project.id)
            ),
            "samples": session.scalar(
                select(func.count()).select_from(MonitoringSample).where(MonitoringSample.project_id == project.id)
            ),
            "citations": session.scalar(
                select(func.count()).select_from(MonitoringCitation).where(MonitoringCitation.project_id == project.id)
            ),
            "evidence_files": session.scalar(
                select(func.count()).select_from(EvidenceFile).where(EvidenceFile.project_id == project.id)
            ),
        }
        print(f"项目 {project.code} 已就绪：{counts}")
        print(f"失败样本：{len(failed_sample_ids)}，待复核样本：{len(manual_sample_ids)}")

        # 隔离校验：同 code 在两个项目各一条，按 project_id 过滤必须各返回 1
        gz = session.scalar(select(Project).where(Project.code == "gz-base"))
        for label, model, code in (
            ("questions", Question, CROSS_CODES["question"]),
            ("channels", Channel, CROSS_CODES["channel"]),
        ):
            edge_count = session.scalar(
                select(func.count()).select_from(model).where(
                    model.project_id == project.id, model.code == code
                )
            )
            base_count = session.scalar(
                select(func.count()).select_from(model).where(
                    model.project_id == gz.id, model.code == code
                )
            )
            print(f"隔离校验 {label} code={code}: edge={edge_count} gz-base={base_count}")
            if edge_count != 1 or base_count != 1:
                raise SystemExit(f"隔离校验失败：{label} {code} 计数异常")

        cross_phone_edge = session.scalar(
            select(func.count()).select_from(Lead).where(
                Lead.project_id == project.id, Lead.contact_phone == CROSS_PHONE
            )
        )
        cross_phone_base = session.scalar(
            select(func.count()).select_from(Lead).where(
                Lead.project_id == gz.id, Lead.contact_phone == CROSS_PHONE
            )
        )
        print(f"隔离校验 leads phone={CROSS_PHONE}: edge={cross_phone_edge} gz-base={cross_phone_base}")
        if cross_phone_edge != 1 or cross_phone_base != 0:
            raise SystemExit("隔离校验失败：同手机号线索串项目")

        # 所有本脚本记录都必须属于 edge-validation
        leaked = session.scalar(
            select(func.count()).select_from(MonitoringSample).where(
                MonitoringSample.project_id != project.id,
                MonitoringSample.id.in_(failed_sample_ids + manual_sample_ids),
            )
        )
        print(f"监测样本 project_id 泄漏检查：{leaked}（应为 0）")
        if leaked:
            raise SystemExit("project_id 隔离失败：监测样本串项目")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
