"""B5 体检引擎：逐项给达成率，不给总分。

规则表写死在代码里（`RULES`），每条规则只做一件事：从项目已有数据里数出分子和分母。
改规则 = 改代码 + 升 `RULESET_VERSION`，不做「后台可编辑规则」——
体检表的口径必须能被审计追溯到某个版本，运营改阈值会让历史两次体检不可比。

三类结论（与 `HealthCheckStatus` 对齐）：
- pass：分子/分母 ≥ 目标；
- fail：有分母，但没到目标；
- unknown：分母为 0。没有数据时给 0 分是错的，因为它把「还没做」和「做了没过」
  混成一件事，运营会以为自己做错了什么。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BrandProfile,
    Channel,
    CompanyProfile,
    Fact,
    Faq,
    HealthCheckItem,
    HealthCheckRun,
    Material,
    MonitoringCitation,
    MonitoringSample,
    PublishReceipt,
    PublishTask,
    PublishVisibilityCheck,
    Question,
    SiteSite,
    SiteModule,
)
from app.models.enums import (
    ChannelApprovalStatus,
    FactStatus,
    FaqStatus,
    HealthCheckStatus,
    MaterialCategory,
    PublishTaskStatus,
)
from app.services.stats import CONFIRMED_REVIEW_STATUS, _count, _valid_sample_scope

RULESET_VERSION = "1"

# 企业档案「必填段」：缺任何一段都不算把公司讲清楚。
# 注意：这里只判「有没有填」，不判文案好坏——文案质量不是机器能打分的。
COMPANY_REQUIRED_FIELDS = (
    ("legal_name", "公司全称"),
    ("description", "公司介绍"),
    ("highlights", "核心优势"),
    ("products", "产品/服务"),
    ("official_urls", "官网地址"),
    ("industries", "所属行业"),
)


@dataclass(frozen=True)
class Rule:
    key: str
    category: str
    label: str
    unit: str
    target_percent: int
    hint: str
    measure: Callable[[Session, uuid.UUID], tuple[int, int]]


def _now_window(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


# ---------------------------------------------------------------- 知识库


def _company_segments(db: Session, project_id: uuid.UUID) -> tuple[int, int]:
    profile = db.scalar(
        select(CompanyProfile).where(
            CompanyProfile.project_id == project_id, CompanyProfile.is_active.is_(True)
        )
    )
    total = len(COMPANY_REQUIRED_FIELDS)
    if profile is None:
        return 0, total
    filled = 0
    for field, _label in COMPANY_REQUIRED_FIELDS:
        value = getattr(profile, field)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        filled += 1
    return filled, total


def _brand_identity(db: Session, project_id: uuid.UUID) -> tuple[int, int]:
    profile = db.scalar(
        select(BrandProfile).where(
            BrandProfile.project_id == project_id, BrandProfile.is_active.is_(True)
        )
    )
    if profile is None:
        return 0, 2
    score = 0
    if profile.canonical_name and profile.canonical_name.strip():
        score += 1
    if profile.owned_domains:
        score += 1
    return score, 2


def _facts_approved(db: Session, project_id: uuid.UUID) -> tuple[int, int]:
    # 事实库要够用才能覆盖 AI 回答里的常见说法；5 条是起步门槛，不是质量门槛
    approved = _count(
        select(Fact).where(
            Fact.project_id == project_id, Fact.approval_status == FactStatus.APPROVED
        ),
        db,
    )
    return approved, 5


def _faq_published(db: Session, project_id: uuid.UUID) -> tuple[int, int]:
    published = _count(
        select(Faq).where(
            Faq.project_id == project_id,
            Faq.status == FaqStatus.PUBLISHED,
            Faq.deleted_at.is_(None),
        ),
        db,
    )
    return published, 10


def _material_coverage(db: Session, project_id: uuid.UUID) -> tuple[int, int]:
    rows = db.execute(
        select(Material.category, func.count())
        .where(Material.project_id == project_id)
        .group_by(Material.category)
    ).all()
    present = sum(1 for category, count in rows if count > 0 and category in {
        MaterialCategory.IMAGE,
        MaterialCategory.VIDEO,
        MaterialCategory.DOCUMENT,
    })
    return present, 3


# ---------------------------------------------------------------- 测量


def _question_coverage(db: Session, project_id: uuid.UUID) -> tuple[int, int]:
    return _count(select(Question).where(Question.project_id == project_id), db), 20


def _sample_volume(db: Session, project_id: uuid.UUID) -> tuple[int, int]:
    valid = _count(_valid_sample_scope(project_id, start_at=_now_window(30)), db)
    return valid, 100


def _mention_rate(db: Session, project_id: uuid.UUID) -> tuple[int, int]:
    scope = _valid_sample_scope(project_id, start_at=_now_window(30))
    valid = _count(scope, db)
    mentioned = _count(scope.where(MonitoringSample.brand_mentioned.is_(True)), db)
    return mentioned, valid


def _citation_review(db: Session, project_id: uuid.UUID) -> tuple[int, int]:
    total = _count(select(MonitoringCitation).where(MonitoringCitation.project_id == project_id), db)
    reviewed = _count(
        select(MonitoringCitation).where(
            MonitoringCitation.project_id == project_id,
            MonitoringCitation.review_status == CONFIRMED_REVIEW_STATUS,
        ),
        db,
    )
    return reviewed, total


# ---------------------------------------------------------------- 投放


def _channel_approval(db: Session, project_id: uuid.UUID) -> tuple[int, int]:
    total = _count(
        select(Channel).where(Channel.project_id == project_id, Channel.is_active.is_(True)), db
    )
    approved = _count(
        select(Channel).where(
            Channel.project_id == project_id,
            Channel.is_active.is_(True),
            Channel.approval_status == ChannelApprovalStatus.APPROVED,
        ),
        db,
    )
    return approved, total


def _publish_closure(db: Session, project_id: uuid.UUID) -> tuple[int, int]:
    total = _count(select(PublishTask).where(PublishTask.project_id == project_id), db)
    cancelled = _count(
        select(PublishTask).where(
            PublishTask.project_id == project_id,
            PublishTask.status == PublishTaskStatus.CANCELLED,
        ),
        db,
    )
    closed = _count(
        select(PublishTask.id)
        .join(PublishReceipt, PublishReceipt.task_id == PublishTask.id)
        .join(PublishVisibilityCheck, PublishVisibilityCheck.receipt_id == PublishReceipt.id)
        .where(
            PublishTask.project_id == project_id,
            PublishVisibilityCheck.error_code.is_(None),
            PublishVisibilityCheck.matched.is_(True),
        )
        .distinct(),
        db,
    )
    return closed, max(total - cancelled, 0)


# ---------------------------------------------------------------- 对外


def _site_published(db: Session, project_id: uuid.UUID) -> tuple[int, int]:
    site = db.scalar(select(SiteSite).where(SiteSite.project_id == project_id))
    if site is None:
        return 0, 1
    active_modules = _count(
        select(SiteModule).where(SiteModule.site_id == site.id, SiteModule.is_active.is_(True)),
        db,
    )
    # 发布但一个模块都没启用，等于对外是个空站，不算达成
    return (1 if site.is_published and active_modules > 0 else 0), 1


RULES: tuple[Rule, ...] = (
    Rule(
        key="company_profile_segments",
        category="知识库",
        label="企业档案必填段",
        unit="段",
        target_percent=100,
        hint="在「企业档案」补齐公司全称/介绍/优势/产品/官网/行业，或直接 PUT /company-profile 写入。",
        measure=_company_segments,
    ),
    Rule(
        key="brand_identity",
        category="知识库",
        label="品牌正式名与自有域名",
        unit="项",
        target_percent=100,
        hint="在「品牌设置」填对外正式名与自有域名，监测才知道该匹配什么。",
        measure=_brand_identity,
    ),
    Rule(
        key="facts_approved",
        category="知识库",
        label="已核验事实条数",
        unit="条",
        target_percent=100,
        hint="事实库至少要有 5 条已批准事实，否则纠错与生成都缺依据。",
        measure=_facts_approved,
    ),
    Rule(
        key="faq_published",
        category="知识库",
        label="已发布 FAQ",
        unit="条",
        target_percent=100,
        hint="把常见问题整理到 10 条并发布，FAQ 是 AI 回答最常引用的块。",
        measure=_faq_published,
    ),
    Rule(
        key="material_coverage",
        category="知识库",
        label="素材类目齐全",
        unit="类",
        target_percent=100,
        hint="图片、视频、文档各传至少一个，做微站与分发时才有素材可用。",
        measure=_material_coverage,
    ),
    Rule(
        key="question_coverage",
        category="测量",
        label="监测问题条数",
        unit="条",
        target_percent=100,
        hint="监测问题至少 20 条，覆盖「是谁/做什么/在哪/多少钱」四类意图。",
        measure=_question_coverage,
    ),
    Rule(
        key="sample_volume",
        category="测量",
        label="近 30 天有效样本",
        unit="条",
        target_percent=100,
        hint="有效样本不足 100 条时，提及率只能当参考，不能对外报。",
        measure=_sample_volume,
    ),
    Rule(
        key="mention_rate",
        category="测量",
        label="品牌提及率",
        unit="%",
        target_percent=30,
        hint="提及率低于 30% 时先补内容与信源，而不是加大投放。",
        measure=_mention_rate,
    ),
    Rule(
        key="citation_review",
        category="测量",
        label="引用人工复核率",
        unit="%",
        target_percent=80,
        hint="未复核的引用不能作为结论依据，复核率到 80% 再引用进报告。",
        measure=_citation_review,
    ),
    Rule(
        key="channel_approval",
        category="投放",
        label="渠道准入通过率",
        unit="%",
        target_percent=100,
        hint="待审核渠道不能建发布任务，先把渠道准入走完。",
        measure=_channel_approval,
    ),
    Rule(
        key="publish_closure",
        category="投放",
        label="发布闭环率",
        unit="%",
        target_percent=50,
        hint="闭环 = 回执 + 收录检测命中；断在哪一段就去补哪一段。",
        measure=_publish_closure,
    ),
    Rule(
        key="site_published",
        category="对外",
        label="微站已发布且有内容",
        unit="项",
        target_percent=100,
        hint="在「微站」启用至少一个内容模块并打开发布开关。",
        measure=_site_published,
    ),
)


def _status(numerator: int, denominator: int, target_percent: int) -> HealthCheckStatus:
    if denominator <= 0:
        return HealthCheckStatus.UNKNOWN
    return (
        HealthCheckStatus.PASS
        if numerator * 100 >= denominator * target_percent
        else HealthCheckStatus.FAIL
    )


def evaluate(db: Session, project_id: uuid.UUID) -> list[dict]:
    """现算一遍，不落库；落库由 `run_health_check` 做。"""
    items: list[dict] = []
    for index, rule in enumerate(RULES):
        numerator, denominator = rule.measure(db, project_id)
        items.append(
            {
                "check_key": rule.key,
                "category": rule.category,
                "label": rule.label,
                "numerator": numerator,
                "denominator": denominator,
                "unit": rule.unit,
                "target_percent": rule.target_percent,
                # 达成率只在有分母时给，避免前端把 0/0 画成 0%
                "ratio": round(numerator / denominator, 4) if denominator > 0 else None,
                "status": _status(numerator, denominator, rule.target_percent).value,
                "hint": rule.hint,
                "sort_order": index,
            }
        )
    return items


def run_health_check(db: Session, project_id: uuid.UUID, *, triggered_by: uuid.UUID | None = None) -> dict:
    items = evaluate(db, project_id)
    run = HealthCheckRun(
        project_id=project_id,
        ruleset_version=RULESET_VERSION,
        total_items=len(items),
        passed_items=sum(1 for item in items if item["status"] == HealthCheckStatus.PASS),
        failed_items=sum(1 for item in items if item["status"] == HealthCheckStatus.FAIL),
        unknown_items=sum(1 for item in items if item["status"] == HealthCheckStatus.UNKNOWN),
        triggered_by=triggered_by,
    )
    db.add(run)
    db.flush()
    for item in items:
        db.add(
            HealthCheckItem(
                project_id=project_id,
                run_id=run.id,
                check_key=item["check_key"],
                category=item["category"],
                label=item["label"],
                numerator=item["numerator"],
                denominator=item["denominator"],
                unit=item["unit"],
                target_percent=item["target_percent"],
                status=HealthCheckStatus(item["status"]),
                hint=item["hint"],
                sort_order=item["sort_order"],
            )
        )
    db.commit()
    return run_snapshot(db, run)


def run_snapshot(db: Session, run: HealthCheckRun) -> dict:
    items = db.scalars(
        select(HealthCheckItem)
        .where(HealthCheckItem.run_id == run.id)
        .order_by(HealthCheckItem.sort_order)
    ).all()
    return {
        "run_id": run.id,
        "ruleset_version": run.ruleset_version,
        "created_at": run.created_at,
        "totals": {
            "total": run.total_items,
            "passed": run.passed_items,
            "failed": run.failed_items,
            "unknown": run.unknown_items,
        },
        "items": [
            {
                "check_key": item.check_key,
                "category": item.category,
                "label": item.label,
                "numerator": item.numerator,
                "denominator": item.denominator,
                "unit": item.unit,
                "target_percent": item.target_percent,
                "ratio": round(item.numerator / item.denominator, 4) if item.denominator > 0 else None,
                "status": item.status.value,
                "hint": item.hint,
            }
            for item in items
        ],
        "disclaimer": "体检只逐项算达成率，不合成总分；分母为 0 的项标「无法计算」，不按 0 分处理。",
    }


def list_runs(db: Session, project_id: uuid.UUID, *, limit: int = 10) -> list[dict]:
    runs = db.scalars(
        select(HealthCheckRun)
        .where(HealthCheckRun.project_id == project_id)
        .order_by(HealthCheckRun.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "run_id": run.id,
            "ruleset_version": run.ruleset_version,
            "created_at": run.created_at,
            "totals": {
                "total": run.total_items,
                "passed": run.passed_items,
                "failed": run.failed_items,
                "unknown": run.unknown_items,
            },
        }
        for run in runs
    ]
