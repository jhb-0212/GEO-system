"""项目接口：创建项目属系统级能力，项目列表按成员授权返回。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_system_permission
from app.api.responses import ok
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Project, ProjectMember, User
from app.models.enums import ProjectStatus
from app.schemas import ProjectCreate
from app.services.audit import record_audit

router = APIRouter(prefix="/api/v1/projects", tags=["项目"])


def _serialize(project: Project) -> dict:
    return {
        "id": str(project.id),
        "code": project.code,
        "name": project.name,
        "status": project.status,
    }


@router.get("")
def list_projects(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """系统管理员看到全部项目；其他人只看自己已加入的项目。"""
    if user.is_system_admin:
        rows = db.scalars(select(Project).order_by(Project.code)).all()
    else:
        rows = db.scalars(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id, ProjectMember.is_active.is_(True))
            .order_by(Project.code)
        ).all()
    return ok([_serialize(row) for row in rows])


@router.post("", status_code=201)
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
