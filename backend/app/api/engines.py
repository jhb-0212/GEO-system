"""AI 平台目录与入口配置：目录读取与入口维护都只对具备引擎能力的管理者开放。

运营自助边界：
- 可维护 entry_url、protocol、model_name、credential_ref（环境变量名）、限额/启停说明；
- 不接收也不回显 API Key 明文；`credential_ref` 只存变量名；
- 只有已实现协议（openai_compatible、yuanbao_search、deepseek_websearch）能真正被 Worker 调用，其余协议仍走明确失败。

权限边界：引擎目录与入口列表是全局配置，含供应商、入口地址、凭证变量名与启停状态，
不对普通登录用户开放；读取与维护统一走 `require_engine_verification`
（系统管理员持 engine.manage，或项目内持 engine.verify 的运营/项目管理员）。
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_engine_verification, require_system_permission
from app.api.responses import (
    COMMON_ERRORS,
    EngineConnectionTestData,
    EngineData,
    EngineEntryData,
    Envelope,
    PagedEnvelope,
    ok,
    ok_page,
)
from app.core.credentials import read_credential_env
from app.core.errors import AppError, ResourceMissingError
from app.db.session import get_db
from app.models import AiEngine, AiEngineEntry, User
from app.models.enums import EngineEntryType, EngineProtocol
from app.schemas import EngineCreate, EngineEntryCreate, EngineEntryUpdate, EngineEntryVerify
from app.services.audit import record_audit
from app.services.engine_connectors import test_entry_connection

router = APIRouter(prefix="/api/v1/engines", tags=["AI 平台目录"], responses=COMMON_ERRORS)


def _serialize(engine: AiEngine) -> dict:
    return {
        "id": str(engine.id),
        "code": engine.code,
        "name": engine.name,
        "vendor": engine.vendor,
        "is_active": engine.is_active,
    }


def _credential_configured(entry: AiEngineEntry) -> bool:
    if entry.protocol == EngineProtocol.DEEPSEEK_WEBSEARCH:
        # 网页版联网搜索不需要 API Key；只有显式配了桥 Token 才要求该变量存在。
        if not entry.credential_ref:
            return True
        return bool(read_credential_env(entry.credential_ref))
    ref = (entry.credential_ref or "").strip()
    if not ref:
        # 搜索类入口允许留空 credential_ref，按适配器默认变量名判断。
        if entry.protocol == EngineProtocol.DEEPSEEK_SEARCH:
            ref = "DEEPSEEK_API_KEY"
        elif entry.protocol == EngineProtocol.DOUBAO_SEARCH:
            ref = "ARK_API_KEY"
        elif entry.protocol == EngineProtocol.WENXIN_SEARCH:
            ref = "QIANFAN_API_KEY"
    if not read_credential_env(ref):
        return False
    if entry.protocol == EngineProtocol.YUANBAO_SEARCH:
        from app.services.yuanbao_search_adapter import SECRET_KEY_ENV

        return bool(os.getenv(SECRET_KEY_ENV, "").strip())
    return True


def _serialize_entry(entry: AiEngineEntry) -> dict:
    credential_configured = _credential_configured(entry)
    return {
        "id": str(entry.id),
        "engine_id": str(entry.engine_id),
        "entry_type": getattr(entry.entry_type, "value", str(entry.entry_type)),
        "name": entry.name,
        "entry_url": entry.entry_url,
        "protocol": getattr(entry.protocol, "value", str(entry.protocol)),
        "model_name": entry.model_name,
        "credential_ref": entry.credential_ref,
        "credential_configured": credential_configured,
        "supports_search": entry.supports_search,
        "access_note": entry.access_note,
        "last_verified_at": entry.last_verified_at,
        "is_active": entry.is_active,
    }


def _get_engine(db: Session, engine_id: uuid.UUID) -> AiEngine:
    engine = db.get(AiEngine, engine_id)
    if engine is None:
        raise ResourceMissingError("AI 平台不存在", code="engine_missing")
    return engine


def _get_entry(db: Session, engine_id: uuid.UUID, entry_id: uuid.UUID) -> AiEngineEntry:
    entry = db.scalar(
        select(AiEngineEntry).where(
            AiEngineEntry.engine_id == engine_id,
            AiEngineEntry.id == entry_id,
        )
    )
    if entry is None:
        raise ResourceMissingError("入口不存在", code="engine_entry_missing")
    return entry


def _validate_entry_config(entry: AiEngineEntry) -> None:
    """只校验会真正影响 Worker 调用的配置，不强制运营一次填完所有字段。"""
    if entry.protocol == EngineProtocol.DEEPSEEK_WEBSEARCH:
        if entry.entry_type.value != "web_user":
            raise AppError(
                "deepseek_websearch 只支持 web_user 类型的入口",
                code="protocol_entry_type_mismatch",
            )
        if not entry.is_active:
            return
        if not (entry.entry_url or "").strip():
            from app.core.config import settings

            if not settings.deepseek_websearch_bridge_url.strip():
                raise AppError(
                    "启用 deepseek_websearch 入口必须填写 entry_url（采集桥地址），"
                    "或设置 DEEPSEEK_WEBSEARCH_BRIDGE_URL",
                    code="entry_url_missing",
                )
        return
    if entry.protocol == EngineProtocol.YUANBAO_SEARCH:
        if entry.entry_type.value != "api":
            raise AppError(
                "yuanbao_search 只支持 api 类型的入口",
                code="protocol_entry_type_mismatch",
            )
        if not entry.is_active:
            return
        if not entry.entry_url:
            raise AppError(
                "启用 yuanbao_search 入口必须填写 entry_url（默认 https://wsa.tencentcloudapi.com）",
                code="entry_url_missing",
            )
        if not entry.credential_ref:
            raise AppError(
                "启用 yuanbao_search 入口必须填写 credential_ref（SecretId 环境变量名）",
                code="credential_ref_missing",
            )
        return
    if entry.protocol in (
        EngineProtocol.DOUBAO_SEARCH,
        EngineProtocol.DEEPSEEK_SEARCH,
        EngineProtocol.WENXIN_SEARCH,
    ):
        if entry.entry_type.value != "api":
            raise AppError(
                "搜索类协议只支持 api 类型的入口",
                code="protocol_entry_type_mismatch",
            )
        if not entry.is_active:
            return
        if entry.protocol == EngineProtocol.DOUBAO_SEARCH and not entry.model_name:
            raise AppError(
                "启用 doubao_search 入口必须填写 model_name（方舟模型 ID）",
                code="model_name_missing",
            )
        return
    if entry.protocol != EngineProtocol.OPENAI_COMPATIBLE:
        return
    if entry.entry_type.value != "api":
        raise AppError(
            "openai_compatible 只支持 api 类型的入口",
            code="protocol_entry_type_mismatch",
        )
    if not entry.is_active:
        return
    if not entry.entry_url:
        raise AppError("启用 openai_compatible 入口必须填写 entry_url", code="entry_url_missing")
    if not entry.model_name:
        raise AppError("启用 openai_compatible 入口必须填写 model_name", code="model_name_missing")


@router.get("", response_model=PagedEnvelope[EngineData])
def list_engines(
    user: User = Depends(require_engine_verification()),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    total = db.scalar(select(func.count()).select_from(AiEngine)) or 0
    rows = db.scalars(
        select(AiEngine).order_by(AiEngine.code).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ok_page(
        [_serialize(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=201, response_model=Envelope[EngineData])
def create_engine(
    payload: EngineCreate,
    user: User = Depends(require_system_permission("engine.manage")),
    db: Session = Depends(get_db),
) -> dict:
    if db.scalar(select(AiEngine).where(AiEngine.code == payload.code)) is not None:
        raise AppError("引擎 code 已存在", code="engine_code_exists")

    engine = AiEngine(
        code=payload.code,
        name=payload.name,
        vendor=payload.vendor,
        supports_search=payload.supports_search,
        supports_citation=payload.supports_citation,
        is_active=True,
    )
    db.add(engine)
    db.flush()
    record_audit(
        db,
        project_id=None,
        actor_id=user.id,
        action="engine.create",
        target_type="ai_engine",
        target_id=engine.id,
        payload={"code": engine.code},
    )
    db.commit()
    return ok(_serialize(engine))


@router.get(
    "/{engine_id}/entries",
    response_model=PagedEnvelope[EngineEntryData],
)
def list_engine_entries(
    engine_id: uuid.UUID,
    user: User = Depends(require_engine_verification()),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，上限 100"),
) -> dict:
    _get_engine(db, engine_id)
    stmt = select(AiEngineEntry).where(AiEngineEntry.engine_id == engine_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AiEngineEntry.created_at, AiEngineEntry.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok_page(
        [_serialize_entry(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/{engine_id}/entries",
    status_code=201,
    response_model=Envelope[EngineEntryData],
)
def create_engine_entry(
    engine_id: uuid.UUID,
    payload: EngineEntryCreate,
    user: User = Depends(require_system_permission("engine.manage")),
    db: Session = Depends(get_db),
) -> dict:
    _get_engine(db, engine_id)
    existing = db.scalar(
        select(AiEngineEntry).where(
            AiEngineEntry.engine_id == engine_id,
            AiEngineEntry.entry_type == payload.entry_type,
            AiEngineEntry.name == payload.name,
        )
    )
    if existing is not None:
        raise AppError("同一平台下入口类型和名称已存在", code="engine_entry_exists")

    entry = AiEngineEntry(
        engine_id=engine_id,
        entry_type=payload.entry_type,
        name=payload.name,
        entry_url=payload.entry_url,
        protocol=payload.protocol,
        model_name=payload.model_name,
        credential_ref=payload.credential_ref,
        supports_search=payload.supports_search,
        access_note=payload.access_note,
        is_active=payload.is_active,
    )
    _validate_entry_config(entry)
    db.add(entry)
    db.flush()
    record_audit(
        db,
        project_id=None,
        actor_id=user.id,
        action="engine.entry.create",
        target_type="ai_engine_entry",
        target_id=entry.id,
        payload={
            "engine_id": str(engine_id),
            "name": entry.name,
            "protocol": entry.protocol.value,
            "credential_ref": entry.credential_ref,
        },
    )
    db.commit()
    return ok(_serialize_entry(entry))


@router.patch(
    "/{engine_id}/entries/{entry_id}",
    response_model=Envelope[EngineEntryData],
)
def update_engine_entry(
    engine_id: uuid.UUID,
    entry_id: uuid.UUID,
    payload: EngineEntryUpdate,
    user: User = Depends(require_system_permission("engine.manage")),
    db: Session = Depends(get_db),
) -> dict:
    entry = _get_entry(db, engine_id, entry_id)
    changes = payload.model_dump(exclude_unset=True)
    nullable = {"entry_url", "model_name", "credential_ref", "access_note"}
    for field, value in changes.items():
        if value is None and field not in nullable:
            continue
        setattr(entry, field, value)
    _validate_entry_config(entry)
    record_audit(
        db,
        project_id=None,
        actor_id=user.id,
        action="engine.entry.update",
        target_type="ai_engine_entry",
        target_id=entry.id,
        payload={"engine_id": str(engine_id), "fields": sorted(changes.keys())},
    )
    db.commit()
    return ok(_serialize_entry(entry))


@router.post(
    "/{engine_id}/entries/{entry_id}/verify",
    response_model=Envelope[EngineEntryData],
)
def verify_engine_entry(
    engine_id: uuid.UUID,
    entry_id: uuid.UUID,
    payload: EngineEntryVerify,
    user: User = Depends(require_engine_verification()),
    db: Session = Depends(get_db),
) -> dict:
    """用户端 / 应用内搜索入口的人工核验：写最近核验时间，API 入口仍走连通性测试。"""
    entry = _get_entry(db, engine_id, entry_id)
    if entry.entry_type not in (EngineEntryType.WEB_USER, EngineEntryType.APP_SEARCH):
        raise AppError(
            "仅用户端 / 应用内搜索入口支持手动核验，API 入口请使用 test-connection",
            code="manual_verify_not_allowed",
        )

    verified_at = payload.verified_at or datetime.now(timezone.utc)
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=timezone.utc)
    else:
        verified_at = verified_at.astimezone(timezone.utc)
    entry.last_verified_at = verified_at

    note = (payload.note or "").strip()
    if note:
        line = f"人工核验 {verified_at.date().isoformat()}：{note}"
        entry.access_note = f"{entry.access_note}\n{line}" if entry.access_note else line

    record_audit(
        db,
        project_id=None,
        actor_id=user.id,
        action="engine.entry.manual_verify",
        target_type="ai_engine_entry",
        target_id=entry.id,
        payload={
            "engine_id": str(engine_id),
            "entry_type": entry.entry_type.value,
            "verified_at": verified_at.isoformat(),
            "has_note": bool(note),
        },
    )
    db.commit()
    return ok(_serialize_entry(entry))


@router.post(
    "/{engine_id}/entries/{entry_id}/test-connection",
    response_model=Envelope[EngineConnectionTestData],
)
def test_engine_entry_connection(
    engine_id: uuid.UUID,
    entry_id: uuid.UUID,
    user: User = Depends(require_system_permission("engine.manage")),
    db: Session = Depends(get_db),
) -> dict:
    entry = _get_entry(db, engine_id, entry_id)
    result = test_entry_connection(entry)
    if result["success"]:
        entry.last_verified_at = datetime.now(timezone.utc)
    record_audit(
        db,
        project_id=None,
        actor_id=user.id,
        action="engine.entry.test",
        target_type="ai_engine_entry",
        target_id=entry.id,
        payload={
            "engine_id": str(engine_id),
            "success": result["success"],
            "error_code": result["error_code"],
            "model_name": entry.model_name,
        },
    )
    db.commit()
    return ok(result)
