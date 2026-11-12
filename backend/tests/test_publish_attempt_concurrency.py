"""发布 attempt 并发保护：一个事务持锁时，另一个请求必须等锁并最终被状态机拒绝。"""

import hashlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from sqlalchemy import delete, func, select

from app.api.publishing import create_attempt
from app.core.errors import TaskRejectedError
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    Channel,
    ContentItem,
    ContentVersion,
    Project,
    PublishAccount,
    PublishAttempt,
    PublishTask,
    User,
)
from app.models.enums import (
    AttemptResult,
    ChannelCategory,
    ChannelStatus,
    ContentKind,
    ContentStatus,
    ProjectStatus,
    PublishMode,
    PublishTaskStatus,
)
from app.schemas import PublishAttemptCreate


def _cleanup(session, project_id, user_id) -> None:
    session.execute(delete(AuditLog).where(AuditLog.project_id == project_id))
    session.execute(delete(PublishAttempt).where(PublishAttempt.project_id == project_id))
    session.execute(delete(PublishTask).where(PublishTask.project_id == project_id))
    session.execute(delete(PublishAccount).where(PublishAccount.project_id == project_id))
    session.execute(delete(ContentVersion).where(ContentVersion.project_id == project_id))
    session.execute(delete(ContentItem).where(ContentItem.project_id == project_id))
    session.execute(delete(Channel).where(Channel.project_id == project_id))
    session.execute(delete(Project).where(Project.id == project_id))
    session.execute(delete(User).where(User.id == user_id))
    session.commit()


def _setup_publish_task() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    session = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    project = Project(
        code=f"lock-{suffix}",
        name=f"发布锁测试-{suffix}",
        status=ProjectStatus.ACTIVE,
        timezone="Asia/Shanghai",
    )
    operator = User(
        username=f"lock-user-{suffix}",
        display_name="发布锁测试用户",
        password_hash=hash_password("unit-test-password"),
        is_active=True,
    )
    session.add_all([project, operator])
    session.flush()

    channel = Channel(
        project_id=project.id,
        code=f"lock-ch-{suffix}",
        name="发布锁测试渠道",
        category=ChannelCategory.CONTENT_PLATFORM,
        status=ChannelStatus.CANDIDATE,
    )
    item = ContentItem(
        project_id=project.id,
        kind=ContentKind.MASTER,
        title="发布锁测试母稿",
        status=ContentStatus.DRAFT,
    )
    session.add_all([channel, item])
    session.flush()

    body = "发布锁测试正文"
    version = ContentVersion(
        project_id=project.id,
        item_id=item.id,
        version_no=1,
        body=body,
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        status=ContentStatus.DRAFT,
    )
    account = PublishAccount(
        project_id=project.id,
        channel_id=channel.id,
        account_name=f"账号-{suffix}",
        credential_ref="vault://test/publish-lock",
        is_active=True,
    )
    session.add_all([version, account])
    session.flush()
    item.current_version_id = version.id

    task = PublishTask(
        project_id=project.id,
        version_id=version.id,
        channel_id=channel.id,
        account_id=account.id,
        task_key=f"tk-{suffix}",
        idempotency_key=f"idem-{suffix}",
        status=PublishTaskStatus.PENDING,
    )
    session.add(task)
    session.commit()

    ids = (project.id, operator.id, task.id)
    session.close()
    return ids


def test_create_attempt_waits_for_row_lock_and_rejects_after_publish():
    project_id, user_id, task_id = _setup_publish_task()
    blocker = SessionLocal()
    worker_session = None
    started = threading.Event()

    try:
        locked = blocker.scalar(
            select(PublishTask)
            .where(PublishTask.id == task_id, PublishTask.project_id == project_id)
            .with_for_update()
        )
        assert locked is not None

        def _attempt() -> str:
            nonlocal worker_session
            worker_session = SessionLocal()
            ctx = SimpleNamespace(
                project=SimpleNamespace(id=project_id),
                user=SimpleNamespace(id=user_id),
            )
            started.set()
            try:
                create_attempt(
                    task_id,
                    PublishAttemptCreate(result=AttemptResult.SUCCESS, mode=PublishMode.MANUAL),
                    ctx,
                    worker_session,
                )
                return "created"
            except TaskRejectedError:
                return "rejected"
            finally:
                worker_session.close()
                worker_session = None

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_attempt)
            assert started.wait(timeout=2), "并发请求未启动"
            time.sleep(0.5)
            assert not future.done(), "请求没有等待已存在的行锁"

            locked.status = PublishTaskStatus.PUBLISHING
            blocker.commit()

            outcome = future.result(timeout=10)

        assert outcome == "rejected"
        verify = SessionLocal()
        try:
            attempt_count = verify.scalar(
                select(func.count()).select_from(PublishAttempt).where(
                    PublishAttempt.task_id == task_id
                )
            )
            assert attempt_count == 0
        finally:
            verify.close()
    finally:
        if worker_session is not None:
            worker_session.close()
        blocker.rollback()
        blocker.close()
        cleanup = SessionLocal()
        try:
            _cleanup(cleanup, project_id, user_id)
        finally:
            cleanup.close()
