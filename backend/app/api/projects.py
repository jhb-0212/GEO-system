"""项目接口：创建项目属系统级能力，项目列表按成员授权返回。"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, get_current_user, require_permission, require_system_permission
from app.api.responses import COMMON_ERRORS, Envelope, PagedEnvelope, ProjectData, ok, ok_page
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Channel, MonitoringTask, Project, ProjectMember, Role, User
from app.models.enums import ProjectStatus, RoleCode
from app.schemas import ProjectConfirm, ProjectCreate
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/projects", tags=["项目"], responses=COMMON_ERRORS)


def _serialize(
    project: Project,
    *,
    owner_name: str | None = None,
    channel_count: int = 0,
    task_count: int = 0,
) -> dict:
    return {
        "id": str(project.id),
        "code": project.code,
        "name": project.name,
        "status": project.status,
        "owner_name": owner_name,
        "priority": project.priority,
        "business_confirmed_at": project.business_confirmed_at,
        "business_confirmed_by": (
            str(project.business_confirmed_by) if project.business_confirmed_by else None
        ),
        "updated_at": project.updated_at,
        "channel_count": channel_count,
        "task_count": task_count,
    }


def _summaries(db: Session, project_ids: list) -> tuple[dict, dict, dict]:
    """项目列表展示用的小计数；一次查询，避免每行回表。"""
    if not project_ids:
        return {}, {}, {}

    channel_counts = dict(
        db.execute(
            select(Channel.project_id, func.count(Channel.id))
            .where(Channel.project_id.in_(project_ids))
            .group_by(Channel.project_id)
        ).all()
    )
    task_counts = dict(
        db.execute(
            select(MonitoringTask.project_id, func.count(MonitoringTask.id))
            .where(MonitoringTask.project_id.in_(project_ids))
            .group_by(MonitoringTask.project_id)
        ).all()
    )
    owner_rows = db.execute(
        select(ProjectMember.project_id, User.display_name, User.username)
        .join(User, User.id == ProjectMember.user_id)
        .join(Role, Role.id == ProjectMember.role_id)
        .where(
            ProjectMember.project_id.in_(project_ids),
            ProjectMember.is_active.is_(True),
            Role.code == RoleCode.PROJECT_ADMIN,
        )
        .order_by(ProjectMember.created_at)
    ).all()
    owners: dict = {}
    for project_id, display_name, username in owner_rows:
        owners.setdefault(project_id, display_name or username)
    return channel_counts, task_counts, owners


@router.get("", response_model=PagedEnvelope[ProjectData])
def list_projects(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    """系统管理员看到全部项目；其他人只看自己已加入的项目。"""
    if user.is_system_admin:
        stmt = select(Project)
    else:
        stmt = (
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id, ProjectMember.is_active.is_(True))
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Project.code).offset((page - 1) * page_size).limit(page_size)
    ).all()
    channel_counts, task_counts, owners = _summaries(db, [row.id for row in rows])
    return ok_page(
        [
            _serialize(
                row,
                owner_name=owners.get(row.id),
                channel_count=channel_counts.get(row.id, 0),
                task_count=task_counts.get(row.id, 0),
            )
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[ProjectData])
def create_project(
    payload: ProjectCreate,
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    if db.scalar(select(Project).where(Project.code == payload.code)) is not None:
        raise AppError("项目 code 已存在", code="project_code_exists")

    owner = db.get(User, payload.owner_id) if payload.owner_id else user
    if owner is None or not owner.is_active:
        raise AppError("项目 owner 不存在或已停用", code="project_owner_missing")
    owner_role = db.scalar(
        select(Role).where(Role.code == RoleCode.PROJECT_ADMIN)
    )
    if owner_role is None:
        raise AppError("project_admin 角色未初始化", code="role_missing")

    project = Project(
        code=payload.code,
        name=payload.name,
        status=ProjectStatus.ACTIVE,
        timezone=payload.timezone,
    )
    db.add(project)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("项目 code 已存在", code="project_code_exists") from exc

    # 项目创建与 owner 授权是同一个生命周期动作：不能先建项目再去数据库补成员。
    member = ProjectMember(
        project_id=project.id,
        user_id=owner.id,
        role_id=owner_role.id,
        is_active=True,
        granted_by=user.id,
    )
    db.add(member)
    db.flush()
    record_audit(
        db,
        project_id=project.id,
        actor_id=user.id,
        action="project.create",
        target_type="project",
        target_id=project.id,
        payload={"code": project.code, "name": project.name, "owner_id": str(owner.id)},
    )
    record_audit(
        db,
        project_id=project.id,
        actor_id=user.id,
        action="project.owner_grant",
        target_type="project_member",
        target_id=member.id,
        payload={"owner_id": str(owner.id), "role": RoleCode.PROJECT_ADMIN.value},
    )
    db.commit()
    return ok(_serialize(project, owner_name=owner.display_name or owner.username))


@router.post("/{project_id}/confirm", response_model=Envelope[ProjectData])
def confirm_project(
    payload: ProjectConfirm,
    ctx: ProjectContext = Depends(require_permission("project.confirm")),
    db: Session = Depends(get_db),
) -> dict:
    """业务负责人确认资料并设置优先级。

    这是项目级动作，需要当前项目具备 `project.member.manage` 能力；当前项目管理员
    默认持有该能力。系统管理员没有项目成员身份时不能越过项目边界替业务确认。
    确认结果写 `projects` 并保留审计。
    """
    project = ctx.project
    project.priority = payload.priority
    project.business_confirmed_at = datetime.now(timezone.utc)
    project.business_confirmed_by = ctx.user.id
    record_audit(
        db,
        project_id=project.id,
        actor_id=ctx.user.id,
        action="project.business_confirm",
        target_type="project",
        target_id=project.id,
        payload={"priority": payload.priority, "note": payload.note},
    )
    db.commit()
    db.refresh(project)
    channel_counts, task_counts, owners = _summaries(db, [project.id])
    return ok(
        _serialize(
            project,
            owner_name=owners.get(project.id),
            channel_count=channel_counts.get(project.id, 0),
            task_count=task_counts.get(project.id, 0),
        )
    )
