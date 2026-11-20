"""一次性数据修正：作废 36氪 测试回执、回退小红书渠道状态。

背景：36氪 的 `https://36kr.com/p/geo-live-smoke` 是联调测试回执，任务却按 published 结案，
渠道仍是 candidate，导致台账一致性告警；小红书被手工置为 published，但没有任何发布回执。

用法：
    python scripts/void_36kr_receipt_and_revert_xhs.py          # 预览
    python scripts/void_36kr_receipt_and_revert_xhs.py --apply  # 执行
"""

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import Channel, Project, PublishReceipt, PublishTask, User  # noqa: E402
from app.models.enums import ChannelStatus, PublishTaskStatus  # noqa: E402
from app.services.audit import record_audit  # noqa: E402

PROJECT_CODE = "gz-base"
TEST_URL = "https://36kr.com/p/geo-live-smoke"
XHS_NAME = "小红书"


def main() -> None:
    parser = argparse.ArgumentParser(description="作废测试回执并回退小红书状态")
    parser.add_argument("--apply", action="store_true", help="真正写库；默认只预览")
    args = parser.parse_args()

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == PROJECT_CODE))
        if project is None:
            raise SystemExit(f"项目不存在：{PROJECT_CODE}")
        actor = db.scalar(select(User).where(User.username == "geo_admin"))

        receipt = db.scalar(
            select(PublishReceipt).where(
                PublishReceipt.project_id == project.id,
                PublishReceipt.published_url == TEST_URL,
            )
        )
        if receipt is None:
            raise SystemExit("未找到目标测试回执，可能已处理")
        task = db.scalar(
            select(PublishTask).where(
                PublishTask.project_id == project.id,
                PublishTask.id == receipt.task_id,
            )
        )
        channel = db.scalar(
            select(Channel).where(
                Channel.project_id == project.id,
                Channel.name == XHS_NAME,
            )
        )
        if channel is None:
            raise SystemExit("未找到小红书渠道")

        print(f"[预览] 回执 {receipt.id} url={receipt.published_url} -> 删除")
        print(f"[预览] 任务 {task.id} 状态 {task.status.value} -> {PublishTaskStatus.CANCELLED.value}")
        print(f"[预览] 渠道 {channel.name} 状态 {channel.status.value} -> {ChannelStatus.CANDIDATE.value}")

        if not args.apply:
            print("未加 --apply，仅预览")
            return

        db.delete(receipt)
        task.status = PublishTaskStatus.CANCELLED
        old_status = channel.status
        channel.status = ChannelStatus.CANDIDATE

        record_audit(
            db,
            project_id=project.id,
            actor_id=actor.id if actor else None,
            action="publish.receipt_void",
            target_type="publish_receipt",
            target_id=receipt.id,
            payload={"published_url": TEST_URL, "task_id": str(task.id), "reason": "联调测试回执，非真实发布"},
        )
        record_audit(
            db,
            project_id=project.id,
            actor_id=actor.id if actor else None,
            action="publish.task_cancel",
            target_type="publish_task",
            target_id=task.id,
            payload={"from_status": PublishTaskStatus.PUBLISHED.value, "to_status": PublishTaskStatus.CANCELLED.value, "reason": "测试回执作废"},
        )
        record_audit(
            db,
            project_id=project.id,
            actor_id=actor.id if actor else None,
            action="channel.update",
            target_type="channel",
            target_id=channel.id,
            payload={
                "changed_fields": ["status"],
                "code": channel.code,
                "status": channel.status.value,
                "from_status": old_status.value,
                "reason": "手工置为 published 但无发布回执，回退为 candidate",
            },
        )
        db.commit()
        print("[完成] 已删除回执、任务置 cancelled、小红书回退 candidate")


if __name__ == "__main__":
    main()
