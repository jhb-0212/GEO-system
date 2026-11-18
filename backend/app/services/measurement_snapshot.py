"""轮次测量快照：把"这一轮按什么口径测量"固定成不可变事实。

背景：执行任务时若每次重新读取当前 BrandProfile / Competitor，运营在轮次
中途补一个别名或加一个竞品，就会让同一轮前半段和后半段使用不同的判定规则。
本模块在轮次创建时生成快照，写入 monitoring_rounds.analysis_config_snapshot，
执行侧只读快照；新配置仅在下一轮生效。

快照内容（全部为可 JSON 序列化的纯数据）：
- brand：品牌词表（mention/identifier/owned_domains）+ 是否来自显式配置；
- competitors：本轮跟踪的竞品名称与域名；
- question_versions：当前版本及其测量语义（类型/意图/受众）；
- rules：匹配器与 URL 归一化规则版本；
- engine_entries：本轮参与测量的入口清单（审计用，任务唯一键已含入口）。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AiEngine, AiEngineEntry, Competitor, Question, QuestionVersion
from app.models.monitoring import MonitoringRound
from app.services.brand_profile import BrandVocabulary, build_vocabulary

SNAPSHOT_VERSION = "measurement-v1"
MENTION_MATCHER_VERSION = "substring-casefold-v1"
IDENTIFIER_MATCHER_VERSION = "substring-casefold-v1"
URL_NORMALIZE_VERSION = "normalize-url-v1"


def build_measurement_snapshot(db: Session, *, project_id: uuid.UUID) -> dict:
    """按项目当前配置生成一份测量快照（不写库）。"""
    vocabulary = build_vocabulary(db, project_id)
    competitors = db.scalars(
        select(Competitor)
        .where(Competitor.project_id == project_id, Competitor.is_active.is_(True))
        .order_by(Competitor.name)
    ).all()
    versions = db.execute(
        select(Question, QuestionVersion)
        .join(
            QuestionVersion,
            (QuestionVersion.question_id == Question.id)
            & (QuestionVersion.version_no == Question.current_version_no),
        )
        .where(Question.project_id == project_id)
        .order_by(Question.code)
    ).all()
    entries = db.execute(
        select(AiEngine, AiEngineEntry)
        .join(AiEngineEntry, AiEngineEntry.engine_id == AiEngine.id)
        .where(AiEngine.is_active.is_(True), AiEngineEntry.is_active.is_(True))
        .order_by(AiEngine.code, AiEngineEntry.created_at, AiEngineEntry.id)
    ).all()

    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "brand": {
            "mention_terms": list(vocabulary.mention_terms),
            "identifier_terms": list(vocabulary.identifier_terms),
            "owned_domains": list(vocabulary.owned_domains),
            "configured": vocabulary.configured,
        },
        "competitors": [
            {"id": str(row.id), "name": row.name, "domain": row.domain}
            for row in competitors
        ],
        "question_versions": [
            {
                "question_id": str(question.id),
                "question_code": question.code,
                "question_version_id": str(version.id),
                "version_no": version.version_no,
                "text": version.text,
                "question_type": (
                    version.question_type.value
                    if version.question_type is not None
                    else question.question_type.value
                ),
                "intent": version.intent if version.intent is not None else question.intent,
                "audience": (
                    version.audience if version.audience is not None else question.audience
                ),
            }
            for question, version in versions
        ],
        "engine_entries": [
            {
                "engine_id": str(engine.id),
                "engine_code": engine.code,
                "entry_id": str(entry.id),
                "entry_type": entry.entry_type.value,
            }
            for engine, entry in entries
        ],
        "rules": {
            "mention_matcher": MENTION_MATCHER_VERSION,
            "identifier_matcher": IDENTIFIER_MATCHER_VERSION,
            "url_normalize": URL_NORMALIZE_VERSION,
        },
    }


def snapshot_hash(snapshot: dict) -> str:
    """稳定哈希：按 key 排序的紧凑 JSON，用于核对快照是否被改写。"""
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def attach_measurement_snapshot(row: MonitoringRound, snapshot: dict) -> None:
    """把快照写到轮次上；已存在快照时不覆盖（轮次快照是不可变事实）。"""
    if row.analysis_config_snapshot is not None:
        return
    row.analysis_config_snapshot = snapshot
    row.analysis_config_hash = snapshot_hash(snapshot)
    row.analysis_config_version = str(snapshot.get("snapshot_version") or SNAPSHOT_VERSION)
    row.analysis_config_captured_at = datetime.now(timezone.utc)


def vocabulary_from_snapshot(snapshot: dict | None) -> BrandVocabulary | None:
    """从轮次快照还原品牌词表；快照缺失或结构损坏时返回 None，由调用方回退。"""
    if not isinstance(snapshot, dict):
        return None
    brand = snapshot.get("brand")
    if not isinstance(brand, dict):
        return None
    mention_terms = brand.get("mention_terms")
    if not isinstance(mention_terms, list):
        return None
    identifier_terms = brand.get("identifier_terms")
    owned_domains = brand.get("owned_domains")
    return BrandVocabulary(
        mention_terms=[str(term) for term in mention_terms if str(term).strip()],
        identifier_terms=[
            str(term) for term in identifier_terms if str(term).strip()
        ]
        if isinstance(identifier_terms, list)
        else [],
        owned_domains=[str(term) for term in owned_domains if str(term).strip()]
        if isinstance(owned_domains, list)
        else [],
        configured=bool(brand.get("configured")),
    )


def snapshot_rules_version(snapshot: dict | None) -> str:
    """规则版本：快照里的匹配器版本；无快照时用当前常量。"""
    if isinstance(snapshot, dict):
        rules = snapshot.get("rules")
        if isinstance(rules, dict):
            value = rules.get("mention_matcher")
            if isinstance(value, str) and value:
                return value
    return MENTION_MATCHER_VERSION
