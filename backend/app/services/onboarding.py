"""开通向导与派生器：填 8 个字段，系统派生问题集/渠道/策略/首轮计划，人来确认。

设计纪律：
- **只派生草稿，不写内容**：问题、渠道、计划都标 `draft/candidate/planning`，人确认后才动；
- **不猜行业**：`industry_preset` 必填且必须存在，未选不给默认；
- **幂等**：同一份输入重复 apply，只补缺项，不重复建题目/渠道；
- **不引外部副作用**：只落库与审计，不发采集请求、不发布。
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    AiEngine,
    AiEngineEntry,
    BrandProfile,
    Channel,
    Competitor,
    MonitoringRound,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
)
from app.models.enums import (
    ChannelApprovalStatus,
    ChannelCategory,
    ChannelStatus,
    QuestionStatus,
    QuestionType,
    RoundStatus,
    SamplingMode,
    TaskStatus,
)
from app.services.industry_presets import load_preset_file, preset_config, upsert_strategy
from app.services.project_policy import DEFAULTS

PRODUCT_MIN, PRODUCT_MAX = 3, 8
COMPETITOR_MIN, COMPETITOR_MAX = 3, 5
QUESTION_MIN, QUESTION_MAX = 8, 12


def _error(message: str, code: str) -> AppError:
    return AppError(message, code=code)


def _clean_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise _error(f"{field} 必须是非空字符串数组", "onboarding_invalid_field")
    return [item.strip() for item in value]


def validate_profile(payload: dict) -> dict:
    brand = payload.get("brand") or {}
    if not isinstance(brand, dict):
        raise _error("brand 必须是对象", "onboarding_invalid_field")
    name = (brand.get("name") or "").strip()
    if not name:
        raise _error("品牌正式名必填", "onboarding_brand_name_required")
    aliases = _clean_list(brand.get("aliases") or [], "brand.aliases")
    domains = _clean_list(brand.get("domains") or [], "brand.domains")
    region = (brand.get("region") or "").strip()
    if not region:
        raise _error("地区/服务范围必填", "onboarding_region_required")

    products = _clean_list(payload.get("products") or [], "products")
    if not (PRODUCT_MIN <= len(products) <= PRODUCT_MAX):
        raise _error(f"产品线需要 {PRODUCT_MIN}–{PRODUCT_MAX} 条", "onboarding_products_range")

    competitors = payload.get("competitors") or []
    if not isinstance(competitors, list) or not (COMPETITOR_MIN <= len(competitors) <= COMPETITOR_MAX):
        raise _error(f"竞品需要 {COMPETITOR_MIN}–{COMPETITOR_MAX} 个", "onboarding_competitors_range")
    clean_competitors = []
    for item in competitors:
        if not isinstance(item, dict) or not (item.get("name") or "").strip():
            raise _error("竞品必须包含 name 与 domain", "onboarding_competitor_invalid")
        clean_competitors.append({
            "name": item["name"].strip(),
            "domain": (item.get("domain") or "").strip() or None,
        })

    preset_code = (payload.get("industry_preset") or "").strip()
    if not preset_code:
        raise _error("必须选择行业预设（不自动套用其他行业）", "onboarding_preset_required")
    try:
        preset = load_preset_file(preset_code)
    except FileNotFoundError as exc:
        raise _error(f"行业预设不存在：{preset_code}", "onboarding_preset_missing") from exc

    engines = payload.get("engines") or []
    if engines and (not isinstance(engines, list) or not all(isinstance(e, str) for e in engines)):
        raise _error("engines 必须是字符串数组", "onboarding_invalid_field")

    samples = payload.get("samples_per_cell", 1)
    if not isinstance(samples, int) or not (1 <= samples <= 5):
        raise _error("samples_per_cell 需要在 1–5", "onboarding_samples_range")

    return {
        "brand": {"name": name, "aliases": aliases, "domains": domains, "region": region},
        "products": products,
        "competitors": clean_competitors,
        "preset_code": preset_code,
        "preset": preset,
        "engines": [e.strip() for e in engines],
        "samples_per_cell": samples,
        "question_count": _question_count(payload.get("question_count")),
        "engines_declared": bool(engines),
    }


def _question_count(value: Any) -> int:
    if value is None:
        return 10
    if not isinstance(value, int) or not (QUESTION_MIN <= value <= QUESTION_MAX):
        raise _error(f"question_count 需要在 {QUESTION_MIN}–{QUESTION_MAX}", "onboarding_question_count")
    return value


def derive_questions(profile: dict) -> list[dict]:
    templates: list[str] = list(profile["preset"].get("question_templates") or [])
    if not templates:
        raise _error("行业预设缺少 question_templates", "onboarding_templates_missing")
    brand, region = profile["brand"]["name"], profile["brand"]["region"]
    candidates: list[tuple[str, QuestionType, str, str]] = []
    for template in templates:
        if "{product}" in template:
            for product in profile["products"]:
                candidates.append((template.format(brand=brand, region=region, product=product, competitor=""),
                                   QuestionType.GENERAL, product, f"评估 {product}"))
        elif "{competitor}" in template:
            for competitor in profile["competitors"][:3]:
                candidates.append((template.format(brand=brand, region=region, product=profile["products"][0],
                                                   competitor=competitor["name"]),
                                   QuestionType.GENERAL, competitor["name"], f"对比 {competitor['name']}"))
        else:
            candidates.append((template.format(brand=brand, region=region, product=profile["products"][0], competitor=""),
                               QuestionType.BRAND, "品牌认知", "核对品牌主体与入口"))

    seen: set[str] = set()
    questions: list[dict] = []
    brand_first = [item for item in candidates if item[1] == QuestionType.BRAND]
    rest = [item for item in candidates if item[1] != QuestionType.BRAND]
    for text, qtype, audience, intent in brand_first + rest:
        if text in seen:
            continue
        seen.add(text)
        questions.append({
            "code": f"Q{len(questions) + 1:02d}",
            "text": text,
            "question_type": qtype.value,
            "audience": audience,
            "intent": intent,
        })
        if len(questions) >= profile["question_count"]:
            break
    if len(questions) < QUESTION_MIN:
        raise _error("按当前字段只能生成过少问题，请补充产品线或竞品", "onboarding_questions_insufficient")
    return questions


def derive_channels(profile: dict) -> list[dict]:
    channels = profile["preset"].get("channels") or []
    if not channels:
        raise _error("行业预设缺少渠道清单", "onboarding_channels_missing")
    return [
        {
            "code": item["code"],
            "name": item["name"],
            "category": item["category"],
            "tier": item.get("tier"),
            "status": ChannelStatus.CANDIDATE.value,
            "approval_status": ChannelApprovalStatus.PENDING_REVIEW.value,
        }
        for item in channels
    ]


def derive_strategy(profile: dict) -> dict:
    return {
        "strategy_key": "industry",
        "preset_code": profile["preset_code"],
        "overrides": {},
        "thresholds": {
            "freshness.window_months": DEFAULTS["freshness.window_months"],
            "contract.target_streak": DEFAULTS["contract.target_streak"],
            "sentiment.min_report": DEFAULTS["sentiment.min_report"],
        },
        "status": "draft",
    }


def derive_plan(profile: dict, questions: list[dict]) -> dict:
    engines = profile["engines"]
    samples = profile["samples_per_cell"]
    cells = len(questions) * max(len(engines), 1) * samples
    planned_at = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)
    return {
        "round_name": "首轮基线",
        "is_baseline": True,
        "planned_at": planned_at.isoformat(),
        "engines": engines,
        "samples_per_cell": samples,
        "questions": len(questions),
        "cells": cells,
        "status": "planning",
        "note": "只生成计划；任务在 apply 且存在可用引擎入口时创建，不自动发起采集。",
    }


def preview(payload: dict) -> dict:
    profile = validate_profile(payload)
    questions = derive_questions(profile)
    channels = derive_channels(profile)
    strategy = derive_strategy(profile)
    plan = derive_plan(profile, questions)
    return {
        "brand": profile["brand"],
        "preset": {"code": profile["preset_code"], "name": profile["preset"].get("name")},
        "products": profile["products"],
        "competitors": profile["competitors"],
        "derived": {"questions": questions, "channels": channels, "strategy": strategy, "plan": plan},
        "warnings": ["问题与渠道为草稿，需人工确认后再启用"] if not profile["engines"] else [],
    }


def _upsert_brand(db: Session, project_id: uuid.UUID, brand: dict) -> int:
    row = db.scalar(
        select(BrandProfile).where(BrandProfile.project_id == project_id, BrandProfile.is_active.is_(True))
    )
    if row is None:
        row = BrandProfile(
            project_id=project_id,
            canonical_name=brand["name"],
            aliases=brand["aliases"],
            owned_domains=brand["domains"],
            identifiers=[],
            notes=f"开通向导录入；地区 {brand['region']}",
            is_active=True,
        )
        db.add(row)
        return 1
    row.canonical_name = brand["name"]
    row.aliases = brand["aliases"]
    row.owned_domains = brand["domains"]
    return 0


def _upsert_competitors(db: Session, project_id: uuid.UUID, competitors: list[dict]) -> int:
    existing = {
        row.name: row
        for row in db.scalars(select(Competitor).where(Competitor.project_id == project_id))
    }
    created = 0
    for item in competitors:
        row = existing.get(item["name"])
        if row is None:
            db.add(Competitor(project_id=project_id, name=item["name"], domain=item["domain"], is_active=True))
            created += 1
        else:
            row.domain = item["domain"] or row.domain
            row.is_active = True
    return created


def _upsert_questions(db: Session, project_id: uuid.UUID, questions: list[dict]) -> tuple[int, list[uuid.UUID]]:
    existing = {
        row.code: row
        for row in db.scalars(select(Question).where(Question.project_id == project_id))
    }
    created = 0
    version_ids: list[uuid.UUID] = []
    for item in questions:
        row = existing.get(item["code"])
        if row is None:
            row = Question(
                project_id=project_id,
                code=item["code"],
                title=item["text"],
                question_type=QuestionType(item["question_type"]),
                audience=item["audience"],
                intent=item["intent"],
                priority=100,
                status=QuestionStatus.DRAFT,
                current_version_no=1,
            )
            db.add(row)
            db.flush()
            version = QuestionVersion(
                project_id=project_id, question_id=row.id, version_no=1,
                text=item["text"], change_note="onboarding-draft",
            )
            db.add(version)
            db.flush()
            created += 1
        else:
            version = db.scalar(
                select(QuestionVersion).where(
                    QuestionVersion.question_id == row.id, QuestionVersion.version_no == row.current_version_no
                )
            )
        version_ids.append((version or db.scalar(
            select(QuestionVersion).where(QuestionVersion.question_id == row.id).order_by(QuestionVersion.version_no.desc())
        )).id)
    return created, version_ids


def _upsert_channels(db: Session, project_id: uuid.UUID, channels: list[dict]) -> int:
    existing = {row.code: row for row in db.scalars(select(Channel).where(Channel.project_id == project_id))}
    created = 0
    for item in channels:
        row = existing.get(item["code"])
        if row is None:
            db.add(
                Channel(
                    project_id=project_id, code=item["code"], name=item["name"],
                    category=ChannelCategory(item["category"]), status=ChannelStatus.CANDIDATE,
                    approval_status=ChannelApprovalStatus.PENDING_REVIEW, is_active=True,
                    notes=f"开通向导派生；信源档位 {item.get('tier')}",
                )
            )
            created += 1
    return created


def _ensure_round(db: Session, project: Project, plan: dict, actor_id: uuid.UUID | None) -> tuple[MonitoringRound, bool]:
    row = db.scalar(
        select(MonitoringRound).where(MonitoringRound.project_id == project.id, MonitoringRound.is_baseline.is_(True))
    )
    if row is not None:
        return row, False
    seq = int(
        db.scalar(select(func.max(MonitoringRound.seq)).where(MonitoringRound.project_id == project.id)) or 0
    ) + 1
    row = MonitoringRound(
        project_id=project.id, seq=seq, name=plan["round_name"], is_baseline=True,
        planned_at=datetime.fromisoformat(plan["planned_at"]), status=RoundStatus.PLANNING,
        created_by=actor_id,
    )
    db.add(row)
    db.flush()
    return row, True


def _engine_entries(db: Session, engine_codes: list[str]) -> list[AiEngineEntry]:
    if not engine_codes:
        return []
    engines = db.scalars(
        select(AiEngine).where(AiEngine.code.in_(engine_codes), AiEngine.is_active.is_(True))
    ).all()
    entries = []
    for engine in engines:
        entries.extend(
            db.scalars(
                select(AiEngineEntry).where(AiEngineEntry.engine_id == engine.id, AiEngineEntry.is_active.is_(True))
            ).all()
        )
    return entries


def _create_tasks(
    db: Session, project_id: uuid.UUID, round_row: MonitoringRound,
    version_ids: list[uuid.UUID], entries: list[AiEngineEntry], samples: int, actor_id: uuid.UUID | None,
) -> int:
    existing = int(
        db.scalar(select(func.count(MonitoringTask.id)).where(MonitoringTask.round_id == round_row.id)) or 0
    )
    created = 0
    for version_id in version_ids:
        for entry in entries:
            for sampling_no in range(1, samples + 1):
                db.add(
                    MonitoringTask(
                        project_id=project_id, round_id=round_row.id, question_version_id=version_id,
                        engine_entry_id=entry.id, sampling_no=sampling_no, trace_id=uuid.uuid4().hex,
                        sampling_mode=SamplingMode.SEARCH_ON, status=TaskStatus.PENDING, created_by=actor_id,
                    )
                )
                created += 1
    return created


def apply(db: Session, project_id: uuid.UUID, payload: dict, *, actor_id: uuid.UUID | None = None) -> dict:
    profile = validate_profile(payload)
    questions = derive_questions(profile)
    channels = derive_channels(profile)

    project = db.get(Project, project_id)
    if project is None:
        raise _error("项目不存在", "project_missing")

    brand_created = _upsert_brand(db, project_id, profile["brand"])
    competitors_created = _upsert_competitors(db, project_id, profile["competitors"])
    upsert_strategy(
        db, project_id, preset_code=profile["preset_code"], overrides={},
        note="开通向导：继承行业预设，阈值取通用默认",
    )
    question_created, version_ids = _upsert_questions(db, project_id, questions)
    channel_created = _upsert_channels(db, project_id, channels)

    entries = _engine_entries(db, profile["engines"])
    round_row = None
    tasks_created = 0
    plan = derive_plan(profile, questions)
    if version_ids:
        round_row, _ = _ensure_round(db, project, plan, actor_id)
        if entries:
            tasks_created = _create_tasks(
                db, project_id, round_row, version_ids, entries, profile["samples_per_cell"], actor_id
            )
    db.flush()

    result = {
        "brand": {"created": brand_created},
        "competitors": {"created": competitors_created, "total": len(profile["competitors"])},
        "questions": {"created": question_created, "total": len(questions), "status": "draft"},
        "channels": {"created": channel_created, "total": len(channels), "status": "candidate"},
        "strategy": {"preset_code": profile["preset_code"], "status": "active"},
        "plan": plan,
        "round_id": str(round_row.id) if round_row else None,
        "tasks_created": tasks_created,
        "engines_resolved": [entry.name for entry in entries],
        "warnings": [] if entries or not profile["engines"] else ["传入的引擎没有可用入口，首轮任务未创建"],
    }
    return result
