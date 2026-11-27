"""项目接口：创建项目属系统级能力，项目列表按成员授权返回。"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectContext, get_current_user, require_permission, require_system_permission
from app.api.responses import (
    COMMON_ERRORS,
    Envelope,
    PagedEnvelope,
    ProjectData,
    ProjectTimezoneData,
    ok,
    ok_page,
)
from app.core.config import settings
from app.core.errors import AppError
from app.db.session import get_db
from app.services import onboarding, organization_members, organization_settings, quota_alerts, usage_metering
from app.models import Project, ProjectMember, Role, User
from app.models.industry import IndustryPreset, Organization
from app.models.enums import ProjectStatus, RoleCode
from app.schemas import ProjectConfirm, ProjectCreate, ProjectTimezoneUpdate
from app.services.project_registry import (
    code_exists,
    industry_presets,
    page_projects,
    project_admin_role,
    user_by_username,
)
from app.services.project_summaries import organization_names, project_summaries
from app.services.audit import record_audit
from app.services.time_windows import (
    ProjectTimezoneInvalid,
    local_today,
    resolve_timezone,
)

router = APIRouter(prefix="/api/v1/projects", tags=["项目"], responses=COMMON_ERRORS)


def _serialize(
    project: Project,
    *,
    owner_name: str | None = None,
    channel_count: int = 0,
    task_count: int = 0,
    organization_name: str | None = None,
) -> dict:
    return {
        "id": str(project.id),
        "code": project.code,
        "name": project.name,
        "status": project.status,
        "organization_id": str(project.organization_id),
        "organization_name": organization_name,
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


@router.get("", response_model=PagedEnvelope[ProjectData])
def list_projects(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
    organization_id: uuid.UUID | None = Query(default=None, description="按客户筛选"),
) -> dict:
    """系统管理员看到全部项目；其他人只看自己已加入的项目。"""
    total, rows = page_projects(
        db,
        user,
        page=page,
        page_size=page_size,
        organization_id=organization_id,
    )
    channel_counts, task_counts, owners = project_summaries(db, [row.id for row in rows])
    org_names = organization_names(db, [row.organization_id for row in rows])
    return ok_page(
        [
            _serialize(
                row,
                owner_name=owners.get(row.id),
                channel_count=channel_counts.get(row.id, 0),
                task_count=task_counts.get(row.id, 0),
                organization_name=org_names.get(row.organization_id),
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
    if code_exists(db, payload.code):
        raise AppError("项目 code 已存在", code="project_code_exists")
    # 配额按客户计：在建项目前先查，避免建出半截项目。
    from app.services.industry_presets import default_organization

    if payload.organization_id is not None:
        org = db.get(Organization, payload.organization_id)
        if org is None or org.status != "active":
            raise AppError("客户不存在或已停用", code="organization_missing")
    elif settings.app_env.lower() in {"prod", "production"}:
        raise AppError(
            "生产环境创建项目必须指定客户，不能落入默认客户",
            code="organization_required",
        )
    else:
        org = default_organization(db)
    org_id = org.id
    organization_settings.enforce_project_quota(db, org_id)

    owner = db.get(User, payload.owner_id) if payload.owner_id else user
    if owner is None or not owner.is_active:
        raise AppError("项目 owner 不存在或已停用", code="project_owner_missing")
    owner_role = project_admin_role(db)
    if owner_role is None:
        raise AppError("project_admin 角色未初始化", code="role_missing")

    project = Project(
        code=payload.code,
        name=payload.name,
        status=ProjectStatus.ACTIVE,
        timezone=payload.timezone,
        organization_id=org_id,
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
    # 不预选行业：未选时接口明确返回 selected=false，由开通向导让人选，不静默套用别的行业规则。
    db.flush()
    # 仅当客户显式开启 inherit_members 时，才把名册成员加成 viewer。
    inheritance = organization_settings.inherit_members(db, project, owner.id)
    record_audit(
        db,
        project_id=project.id,
        actor_id=user.id,
        action="project.create",
        target_type="project",
        target_id=project.id,
        payload={"code": project.code, "name": project.name, "timezone": project.timezone, "owner_id": str(owner.id), "inherited_members": inheritance},
    )
    quota_alerts.sync(
        db, org_id, project.id, organization_settings.get_settings(db, org_id, project.id)["alerts"]
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
    return ok(_serialize(project, owner_name=owner.display_name or owner.username, organization_name=org.name))


def _local_today_or_none(name: str, moment: datetime) -> str | None:
    """审计用的口径说明：旧值可能已是脏数据，不能因此阻断修复。"""
    try:
        return local_today(resolve_timezone(name), now=moment).isoformat()
    except ProjectTimezoneInvalid:
        return None


@router.put("/{project_id}/timezone", response_model=Envelope[ProjectTimezoneData])
def update_project_timezone(
    payload: ProjectTimezoneUpdate,
    ctx: ProjectContext = Depends(require_permission("project.timezone.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """修改项目业务时区；时区变更与审计同一事务。

    权限使用独立的 `project.timezone.manage`：只有 PROJECT_ADMIN 持有，
    不与“确认项目资料”复用，避免未来授权变化时扩大时区修改范围。
    """
    # 锁项目行并重新读取：并发修改时，第二个请求必须拿到第一个请求提交后的旧值。
    db.refresh(ctx.project, with_for_update=True)
    project = ctx.project
    # 锁获取后再读旧值，两个管理员并发修改时审计链才能形成真实连续变化。
    previous = project.timezone
    new_timezone = payload.timezone
    moment = datetime.now(timezone.utc)
    impact = {
        "policy": "按新项目时区重新计算今天/本周及项目级日期窗口；不保存历史时区、不回写历史业务数据",
        "historical_recalculated": False,
        "old_local_today": _local_today_or_none(previous, moment),
        "new_local_today": local_today(resolve_timezone(new_timezone), now=moment).isoformat(),
    }

    if new_timezone == previous:
        # 幂等：相同新旧值不产生变更事件，也不写重复审计。
        return ok(
            {
                "project_id": str(project.id),
                "timezone": previous,
                "previous_timezone": previous,
                "changed": False,
                "updated_at": project.updated_at,
                "impact": {**impact, "old_local_today": impact["new_local_today"]},
            }
        )

    try:
        project.timezone = new_timezone
        record_audit(
            db,
            project_id=project.id,
            actor_id=ctx.user.id,
            action="project.timezone.update",
            target_type="project",
            target_id=project.id,
            payload={
                "old_timezone": previous,
                "new_timezone": new_timezone,
                "changed_at": moment.isoformat(),
                "impact": impact,
            },
        )
        # 更新与审计必须一起成功；任一写入失败都回滚，不能留下“改了时区但没有审计”。
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(project)
    return ok(
        {
            "project_id": str(project.id),
            "timezone": project.timezone,
            "previous_timezone": previous,
            "changed": True,
            "updated_at": project.updated_at,
            "impact": impact,
        }
    )


@router.post("/{project_id}/confirm", response_model=Envelope[ProjectData])
def confirm_project(
    payload: ProjectConfirm,
    ctx: ProjectContext = Depends(require_permission("project.confirm")),
    db: Session = Depends(get_db),
) -> dict:
    """业务负责人确认资料并设置优先级。

    这是项目级动作，需要当前项目具备 `project.confirm` 能力；当前项目管理员
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
    channel_counts, task_counts, owners = project_summaries(db, [project.id])
    return ok(
        _serialize(
            project,
            owner_name=owners.get(project.id),
            channel_count=channel_counts.get(project.id, 0),
            task_count=task_counts.get(project.id, 0),
        )
    )


@router.get("/{project_id}/industry-presets", response_model=Envelope[list[dict]])
def list_industry_presets(
    project_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
) -> dict:
    """可选行业预设清单；只列已落库的，不暗示默认行业。"""
    rows = industry_presets(db)
    return ok([{"code": row.code, "name": row.name} for row in rows])


@router.post("/{project_id}/onboarding/preview", response_model=Envelope[dict])
def onboarding_preview(
    project_id: uuid.UUID,
    payload: dict,
    ctx: ProjectContext = Depends(require_permission("stats.read")),
) -> dict:
    """开通向导：只算不写。返回派生的问题/渠道/策略/首轮计划草稿，供人确认。"""
    return ok(onboarding.preview(payload))


@router.post("/{project_id}/onboarding/apply", response_model=Envelope[dict])
def onboarding_apply(
    project_id: uuid.UUID,
    payload: dict,
    ctx: ProjectContext = Depends(require_permission("project.confirm")),
    db: Session = Depends(get_db),
) -> dict:
    """确认后落草稿：品牌档案、竞品、题目、渠道候选、行业策略；有引擎入口时建首轮任务。"""
    result = onboarding.apply(db, project_id, payload, actor_id=ctx.user.id)
    record_audit(
        db, project_id=project_id, actor_id=ctx.user.id,
        action="project.onboarding.apply", target_type="onboarding",
        payload={
            "preset": result["strategy"]["preset_code"],
            "questions": result["questions"]["total"],
            "channels": result["channels"]["total"],
            "tasks_created": result["tasks_created"],
        },
    )
    db.commit()
    return ok(result)


@router.get("/{project_id}/consumption", response_model=Envelope[dict])
def project_usage(
    project_id: uuid.UUID,
    start: str | None = Query(None, description="YYYY-MM-DD，默认最近 30 天"),
    end: str | None = Query(None, description="YYYY-MM-DD，含当天"),
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
) -> dict:
    """项目消耗汇总：六项计量，能派生的实时从事实表算，不能派生的读事件账本。"""
    try:
        return ok(usage_metering.summarize(db, start, end, project_id=project_id))
    except ValueError as exc:
        raise AppError(str(exc), code="usage_range_invalid") from exc


@router.get("/{project_id}/consumption/events", response_model=Envelope[list[dict]])
def project_usage_events(
    project_id: uuid.UUID,
    start: str | None = Query(None),
    end: str | None = Query(None),
    metric: str | None = Query(None, description="collection/generation/publishing/reachability/report_export/lead"),
    limit: int = Query(200, ge=1, le=500),
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
) -> dict:
    """账本明细：数字要能点回来源，否则用量就是黑箱。"""
    try:
        return ok(usage_metering.events(db, start, end, project_id=project_id, metric=metric, limit=limit))
    except ValueError as exc:
        raise AppError(str(exc), code="usage_range_invalid") from exc


@router.get("/{project_id}/organization-members", response_model=Envelope[list[dict]])
def list_organization_members(
    project_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("stats.read")),
    db: Session = Depends(get_db),
) -> dict:
    """客户名册；`in_project` 表示是否已进本项目，名册本身不授予访问权。"""
    return ok(organization_members.list_members(db, ctx.project))


@router.post("/{project_id}/organization-members", response_model=Envelope[dict])
def add_organization_member(
    project_id: uuid.UUID,
    payload: dict,
    ctx: ProjectContext = Depends(require_permission("project.member.manage")),
    db: Session = Depends(get_db),
) -> dict:
    raw = str(payload.get("user_id") or "")
    if raw:
        try:
            user_id = uuid.UUID(raw)
        except ValueError as exc:
            raise AppError("user_id 无效", code="validation_error") from exc
    else:
        # 名册操作按工作账号更顺手：没传 user_id 时用 username 精确查，避免前端自己拼 UUID。
        username = str(payload.get("username") or "").strip()
        target = user_by_username(db, username) if username else None
        if target is None:
            raise AppError("工作账号不存在", code="user_missing")
        user_id = target.id
    result = organization_members.add_member(db, ctx.project, user_id, role=str(payload.get("role") or "member"))
    quota_alerts.sync(
        db, ctx.project.organization_id, ctx.project.id,
        organization_settings.get_settings(db, ctx.project.organization_id, ctx.project.id)["alerts"],
    )
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="organization.member.add", target_type="organization_member",
        target_id=user_id, payload={"role": result["role"]},
    )
    db.commit()
    return ok(result)


@router.post("/{project_id}/organization-members/sync", response_model=Envelope[dict])
def sync_organization_members(
    project_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("project.member.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """显式同步：把名册中未进项目的人加成 viewer；不复制角色、不改已有成员。"""
    result = organization_members.sync_to_project(db, ctx.project, ctx.user.id)
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="organization.member.sync_to_project", target_type="project_member",
        target_id=ctx.project.id, payload=result,
    )
    db.commit()
    return ok(result)


@router.delete("/{project_id}/organization-members/{user_id}", response_model=Envelope[dict])
def remove_organization_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_permission("project.member.manage")),
    db: Session = Depends(get_db),
) -> dict:
    result = organization_members.remove_member(db, ctx.project, user_id)
    quota_alerts.sync(
        db, ctx.project.organization_id, ctx.project.id,
        organization_settings.get_settings(db, ctx.project.organization_id, ctx.project.id)["alerts"],
    )
    record_audit(
        db, project_id=ctx.project.id, actor_id=ctx.user.id,
        action="organization.member.remove", target_type="organization_member",
        target_id=user_id, payload={},
    )
    db.commit()
    return ok(result)


@router.get("/{project_id}/organization", response_model=Envelope[dict])
def get_organization_settings(
    project_id: uuid.UUID,
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    """客户级设置：继承开关、配额、客户策略；只有系统管理员可见可改。"""
    project = db.get(Project, project_id)
    if project is None:
        raise AppError("项目不存在", code="project_missing")
    return ok(organization_settings.get_settings(db, project.organization_id, project.id))


@router.get("/{project_id}/organization/usage", response_model=Envelope[dict])
def get_organization_usage(
    project_id: uuid.UUID,
    days: int = Query(default=30, ge=1, le=90),
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    """用量趋势：当天快照 + 近 N 天历史；缺失日期按创建时间回算并标注来源。"""
    project = db.get(Project, project_id)
    if project is None:
        raise AppError("项目不存在", code="project_missing")
    result = organization_settings.usage_trend(db, project.organization_id, days)
    # 读取时顺手落当天快照，保证趋势最后一点有事实来源；仅覆盖当天一行。
    db.commit()
    return ok(result)


@router.put("/{project_id}/organization", response_model=Envelope[dict])
def update_organization_settings(
    project_id: uuid.UUID,
    payload: dict,
    user: User = Depends(require_system_permission("project.create")),
    db: Session = Depends(get_db),
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise AppError("项目不存在", code="project_missing")
    result = organization_settings.update_settings(db, project.organization_id, payload)
    quota_alerts.sync(db, project.organization_id, project.id, result["alerts"])
    record_audit(
        db, project_id=project.id, actor_id=user.id,
        action="organization.settings.update", target_type="organization",
        target_id=project.organization_id, payload={key: payload.get(key) for key in ("inherit_members", "inherit_role", "quotas", "strategy")},
    )
    db.commit()
    return ok(result)
