"""基线验收：检查一个轮次是否真的形成 6 题 × 4 引擎 = 24 个测试格。

通过条件（任一不满足即非零退出）：

1. 任务数 = 期望值（默认 24），且 (question_id, engine_id) 唯一组合 = 24；
2. 覆盖的问题数 = 6、引擎数 = 4；
3. 每个任务至少有一条 `monitoring_samples`；
4. 每个任务至少有一个“有效结果”（hit/miss，且 brand_mentioned 已判定）
   或“明确失败原因”（failed 且 failure_code 非空）；
5. 任务状态只能是 done/failed；failed 任务必须至少有一条 failed 且带 failure_code 的样本；
6. `manual_review` / `pending` / `running` 不视为已完成结果，会单独列出来。

用法（在 backend 目录下）：

    .venv\\Scripts\\python.exe scripts\\validate_baseline.py --project-code gz-base

默认取 `is_baseline=true` 的轮次；没有基线轮次时取 seq 最小的轮次。
也可以显式指定 `--round-seq 1` 或 `--round-id <uuid>`。
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AiEngine,
    AiEngineEntry,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
)
from app.models.enums import SampleStatus, TaskStatus  # noqa: E402


def _find_round(session, project, round_seq: int | None, round_id: uuid.UUID | None):
    rounds = session.scalars(
        select(MonitoringRound)
        .where(MonitoringRound.project_id == project.id)
        .order_by(MonitoringRound.seq)
    ).all()
    if not rounds:
        return None
    if round_id is not None:
        return next((row for row in rounds if row.id == round_id), None)
    if round_seq is not None:
        return next((row for row in rounds if row.seq == round_seq), None)
    baseline = next((row for row in rounds if row.is_baseline), None)
    return baseline or rounds[0]


def validate(
    session,
    project,
    round_row,
    *,
    expect_tasks: int,
    expect_questions: int,
    expect_engines: int,
) -> list[str]:
    issues: list[str] = []

    rows = session.execute(
        select(
            MonitoringTask,
            QuestionVersion.question_id,
            Question.code,
            Question.title,
            AiEngineEntry.engine_id,
            AiEngine.code,
            AiEngine.name,
        )
        .select_from(MonitoringTask)
        .join(QuestionVersion, MonitoringTask.question_version_id == QuestionVersion.id)
        .join(Question, QuestionVersion.question_id == Question.id)
        .join(AiEngineEntry, MonitoringTask.engine_entry_id == AiEngineEntry.id)
        .join(AiEngine, AiEngineEntry.engine_id == AiEngine.id)
        .where(
            MonitoringTask.project_id == project.id,
            MonitoringTask.round_id == round_row.id,
        )
        .order_by(Question.code, AiEngine.code, MonitoringTask.sampling_no)
    ).all()

    task_count = len(rows)
    question_ids = {question_id for _, question_id, *_ in rows}
    engine_ids = {engine_id for _, _, _, _, engine_id, *_ in rows}
    combinations = Counter((question_id, engine_id) for _, question_id, _, _, engine_id, *_ in rows)

    if task_count != expect_tasks:
        issues.append(f"任务数 {task_count} != 期望 {expect_tasks}")
    if len(question_ids) != expect_questions:
        issues.append(f"覆盖问题数 {len(question_ids)} != 期望 {expect_questions}")
    if len(engine_ids) != expect_engines:
        issues.append(f"覆盖引擎数 {len(engine_ids)} != 期望 {expect_engines}")
    duplicates = [pair for pair, count in combinations.items() if count > 1]
    if duplicates:
        issues.append(f"存在重复的 (问题, 引擎) 组合：{duplicates}")
    if len(combinations) != expect_tasks:
        issues.append(f"唯一测试组合数 {len(combinations)} != 期望 {expect_tasks}")

    missing_samples = []
    invalid_results = []
    non_terminal_tasks = []
    failed_without_code = []
    failed_task_without_failed_sample = []
    manual_review_tasks = []
    pending_or_running_tasks = []
    missing_brand_flag = []

    for task, question_id, question_code, _, engine_id, engine_code, _ in rows:
        samples = session.scalars(
            select(MonitoringSample)
            .where(
                MonitoringSample.project_id == project.id,
                MonitoringSample.task_id == task.id,
            )
            .order_by(MonitoringSample.attempt_no)
        ).all()
        if not samples:
            missing_samples.append(f"{question_code}/{engine_code}#{task.sampling_no}")
            invalid_results.append(f"{question_code}/{engine_code}#{task.sampling_no}（无样本）")
            continue

        if task.status not in (TaskStatus.DONE, TaskStatus.FAILED):
            non_terminal_tasks.append(
                f"{question_code}/{engine_code}#{task.sampling_no}={task.status}"
            )
            if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                pending_or_running_tasks.append(
                    f"{question_code}/{engine_code}#{task.sampling_no}={task.status}"
                )

        has_valid_result = False
        has_failed_with_code = False
        has_manual_review = False
        for sample in samples:
            status = sample.status
            if status in (SampleStatus.HIT, SampleStatus.MISS):
                if sample.brand_mentioned is None:
                    missing_brand_flag.append(
                        f"{question_code}/{engine_code}#{task.sampling_no} sample={sample.id}"
                    )
                else:
                    has_valid_result = True
            elif status == SampleStatus.FAILED:
                if sample.failure_code:
                    has_failed_with_code = True
                    has_valid_result = True
                else:
                    failed_without_code.append(
                        f"{question_code}/{engine_code}#{task.sampling_no} sample={sample.id}"
                    )
            elif status == SampleStatus.MANUAL_REVIEW:
                has_manual_review = True

        if not has_valid_result:
            invalid_results.append(
                f"{question_code}/{engine_code}#{task.sampling_no}"
            )
        if has_manual_review:
            manual_review_tasks.append(f"{question_code}/{engine_code}#{task.sampling_no}")
        if task.status == TaskStatus.FAILED and not has_failed_with_code:
            failed_task_without_failed_sample.append(
                f"{question_code}/{engine_code}#{task.sampling_no}"
            )

    if missing_samples:
        issues.append(f"以下任务没有任何样本：{missing_samples}")
    if invalid_results:
        issues.append(f"以下测试格没有有效结果或明确失败原因：{invalid_results}")
    if non_terminal_tasks:
        issues.append(f"以下任务不是终态：{non_terminal_tasks}")
    if failed_without_code:
        issues.append(f"以下 failed 样本缺 failure_code：{failed_without_code}")
    if failed_task_without_failed_sample:
        issues.append(
            f"以下 failed 任务没有带 failure_code 的 failed 样本：{failed_task_without_failed_sample}"
        )
    if manual_review_tasks:
        issues.append(f"以下任务仍停在 manual_review：{manual_review_tasks}")
    if pending_or_running_tasks:
        issues.append(f"以下任务仍停在 pending/running：{pending_or_running_tasks}")
    if missing_brand_flag:
        issues.append(f"以下 hit/miss 样本未判定 brand_mentioned：{missing_brand_flag}")

    print(f"项目：{project.code} / {project.name}")
    print(f"轮次：seq={round_row.seq} name={round_row.name} id={round_row.id}")
    print(
        f"任务数：{task_count}/{expect_tasks}；问题数：{len(question_ids)}/{expect_questions}；"
        f"引擎数：{len(engine_ids)}/{expect_engines}；唯一组合：{len(combinations)}/{expect_tasks}"
    )
    print(f"缺样本任务：{len(missing_samples)}；无有效结果：{len(invalid_results)}；"
          f"非终态任务：{len(non_terminal_tasks)}；failed 缺 failure_code：{len(failed_without_code)}")
    print(f"manual_review 任务：{len(manual_review_tasks)}；pending/running 任务：{len(pending_or_running_tasks)}")

    if issues:
        print("\n验收失败：")
        for index, issue in enumerate(issues, start=1):
            print(f"  [{index}] {issue}")
    else:
        print("\n验收通过：24 个测试格均已形成有效结果或明确失败原因。")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="验收 6 题 × 4 引擎 = 24 个测试格")
    parser.add_argument("--project-code", default="gz-base", help="项目 code，默认 gz-base")
    parser.add_argument("--round-seq", type=int, default=None, help="轮次 seq；不传时取基线轮次")
    parser.add_argument("--round-id", default=None, help="轮次 UUID；与 --round-seq 二选一")
    parser.add_argument("--expect-tasks", type=int, default=24, help="期望任务数，默认 24")
    parser.add_argument("--expect-questions", type=int, default=6, help="期望问题数，默认 6")
    parser.add_argument("--expect-engines", type=int, default=4, help="期望引擎数，默认 4")
    args = parser.parse_args()

    round_id = uuid.UUID(args.round_id) if args.round_id else None
    session = SessionLocal()
    try:
        project = session.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            print(f"验收失败：找不到项目 code={args.project_code}", file=sys.stderr)
            return 2
        round_row = _find_round(session, project, args.round_seq, round_id)
        if round_row is None:
            print(
                f"验收失败：项目 {args.project_code} 没有匹配的轮次，"
                "请先用监测轮次接口建轮次并生成任务",
                file=sys.stderr,
            )
            return 2
        issues = validate(
            session,
            project,
            round_row,
            expect_tasks=args.expect_tasks,
            expect_questions=args.expect_questions,
            expect_engines=args.expect_engines,
        )
        return 1 if issues else 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
