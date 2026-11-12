"""采样执行服务（本期 CLI 采样器，Worker 后续再接）。

边界（B4 方案四·五）：
- 批量接口只建 pending 任务；本服务读 pending 任务，落一条样本（attempt_no=1）并回写任务终态；
- 本期无可用入口/凭据，不发起真实 HTTP 请求；按库里真实的 `ai_engine_entries` 可用性判定分支，
  不可用落 `failed` + `failure_code` + `failure_note`；
- 真实适配器调用是控制流里的显式分支：`_is_callable` 为真才进 `_invoke_adapter`；
  本期模型无凭据字段、适配器未接入，该分支不可达，`_invoke_adapter` 为预留实现点；
- 失败归类：本期只可能落 `access_blocked`；`login_blocked / timeout / captcha /
  rate_limited / other` 必须真实发起请求后才能识别，待适配器接入后补对应分支；
- mock 只进单元测试，验收库不走 mock；不预置、不批量手写样本行（成功、失败都算造假）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AiEngineEntry, MonitoringSample, MonitoringTask
from app.models.enums import FailureCode, SampleStatus, TaskStatus


def _is_callable(entry: AiEngineEntry | None) -> bool:
    """入口本期是否可调用。

    现有 `ai_engine_entries` 模型只存 URL/备注，没有凭据字段；适配器也未接入，
    因此本期恒为 False。后续接入凭据与适配器后，在此判定 URL 与凭据是否齐备。
    """
    return False


def classify_entry(entry: AiEngineEntry | None) -> tuple[FailureCode, str]:
    """不可调用时的失败归类；需登录、验证码、429、超时等情形要真实请求后才能识别。"""
    if entry is None:
        return FailureCode.ACCESS_BLOCKED, "引擎入口不存在；未发起真实请求"
    if not entry.entry_url or not entry.entry_url.strip():
        return FailureCode.ACCESS_BLOCKED, "entry_url 未配置；无 API 凭据，未发起真实请求"
    return FailureCode.ACCESS_BLOCKED, "入口暂无可调用凭据；未发起真实请求"


def _invoke_adapter(task: MonitoringTask, entry: AiEngineEntry) -> dict[str, Any]:
    """真实适配器调用预留（可调用分支的实现点）。

    拿到 key/URL 后在此发请求，返回命中/未命中与原始回答；本期适配器未接入，不可达。
    """
    raise NotImplementedError("引擎适配器尚未接入，本期不发起真实请求")


def sample_pending_task(db: Session, task: MonitoringTask) -> MonitoringSample:
    """给单个 pending 任务落一条样本，并把任务置为终态。"""
    entry = db.get(AiEngineEntry, task.engine_entry_id)

    if not _is_callable(entry):
        failure_code, failure_note = classify_entry(entry)
        sample = MonitoringSample(
            project_id=task.project_id,
            task_id=task.id,
            attempt_no=1,
            status=SampleStatus.FAILED,
            sampled_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            sampling_mode=task.sampling_mode,
            raw_answer=None,
            raw_response=None,
            brand_mentioned=None,
            failure_code=failure_code,
            failure_note=failure_note,
        )
        db.add(sample)
        task.status = TaskStatus.FAILED
        db.flush()
        return sample

    # 适配器接入后：调用 _invoke_adapter，按命中/未命中落 hit/miss 样本，
    # 回写 brand_mentioned 与任务 done；其余失败码在此按真实响应归类。
    assert entry is not None
    _invoke_adapter(task, entry)
    raise NotImplementedError("适配器接入后在此落 hit/miss 样本并回写终态")


def run_pending_tasks(
    db: Session,
    *,
    project_id: uuid.UUID,
    round_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """跑完指定项目/轮次的 pending 任务；返回落库计数。"""
    filters = [
        MonitoringTask.project_id == project_id,
        MonitoringTask.status == TaskStatus.PENDING,
    ]
    if round_id is not None:
        filters.append(MonitoringTask.round_id == round_id)

    tasks = db.scalars(select(MonitoringTask).where(*filters)).all()
    failed = 0
    for task in tasks:
        sample_pending_task(db, task)
        failed += 1

    return {
        "project_id": str(project_id),
        "round_id": str(round_id) if round_id else None,
        "pending_task_count": len(tasks),
        "failed_task_count": failed,
    }
