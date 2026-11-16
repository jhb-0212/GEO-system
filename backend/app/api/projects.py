"""项目接口：创建项目属系统级能力，项目列表按成员授权返回。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_system_permission
from app.api.responses import COMMON_ERRORS, Envelope, PagedEnvelope, ProjectData, ok, ok_page
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Channel, MonitoringTask, Project, ProjectMember, Role, User
from app.models.enums import ProjectStatus, RoleCode
from app.schemas import ProjectCreate
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

    project = Project(
        code=payload.code,
        name=payload.name,
        status=ProjectStatus.ACTIVE,
        timezone=payload.timezone,
    )
    db.add(project)
    db.flush()
    record_audit(
        db,
        project_id=project.id,
        actor_id=user.id,
        action="project.create",
        target_type="project",
        target_id=project.id,
        payload={"code": project.code, "name": project.name},
    )
    db.commit()
    return ok(_serialize(project))
