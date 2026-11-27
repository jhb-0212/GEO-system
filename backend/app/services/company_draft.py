"""企业档案「一键填表」：把项目里已有的证据整理成表单字段。

证据只取四类，都在项目内、都已落库：

- `facts` 已批准的事实（电话、地址、课程、师资、合作方……）；
- `knowledge_chunks` 已解析素材的正文片段（用于写公司介绍/卖点，不用于可核验值）；
- `brand_profile` 品牌名与自有域名；
- 目标词（本项目在监测的提问文本），用来判断「这群人关心什么」。

两条路径，返回里明确写 `mode`，前端不许把规则整理说成 AI 生成：

- `ai`：系统里配了可用的 OpenAI 兼容入口（有 model + 凭据）时，把证据交给模型起草；
- `rule`：没有可用模型时只做事实到字段的 1:1 映射，不创作任何文案。

三条硬边界：

1. 证据里没有的字段一律留空——缺口比编造好；
2. 不猜数字：成立时间、员工规模、电话只从事实搬，不从正文摘；
3. 调用失败不影响页面：模型不可达/返回不合法时退回 `rule`，并在 `note` 里说明原因。
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BrandProfile, CompanyProfile, Fact, KnowledgeChunk, Question
from app.models.enums import FactStatus, FactType
from app.models.engine import AiEngineEntry
from app.models.enums import EngineProtocol, QuestionStatus
from app.schemas.company import CompanyProfileDraftFields
from app.services.engine_credentials import resolve_entry_secret

# 起草是一次性的短任务，超时给够一次 「读证据 + 写两段长文案」，但不要长到把页面卡住。
DRAFT_TIMEOUT_SECONDS = 45.0

EVIDENCE_FACT_LIMIT = 60
EVIDENCE_CHUNK_LIMIT = 8
EVIDENCE_CHUNK_CHARS = 300
EVIDENCE_QUESTION_LIMIT = 12

# 事实 → 字段的映射全部写死在这里：新增一类事实要显式决定它落到哪个字段，
# 不做「按关键词猜」的模糊匹配，否则一条「合作方是某某学院」会被塞进公司介绍。
PHONE_KEY_HINTS = ("电话", "热线", "手机", "phone", "tel")
EMAIL_KEY_HINTS = ("邮箱", "邮件", "email", "mail")
NAME_KEY_HINTS = ("名称", "全称", "简称", "name")
ADDRESS_KEY_HINTS = ("地址", "位置", "address", "adress")
COPY_FACT_TYPES = (
    FactType.TRAINING_RESULT,
    FactType.EMPLOYMENT_SERVICE,
    FactType.PARTNER,
    FactType.CERTIFICATION,
    FactType.FACULTY,
)

DRAFT_FIELD_LABELS = {
    "legal_name": "公司名称",
    "brand_name": "公司品牌",
    "slogan": "品牌 slogan",
    "province": "所在省份",
    "business_phone": "业务电话",
    "service_hotline": "售后热线",
    "contact_email": "企业邮箱",
    "industries": "行业类别",
    "regions": "覆盖地区",
    "stores": "线下网点",
    "products": "产品/服务",
    "description": "公司介绍",
    "founder_intro": "创始人介绍",
    "highlights": "产品/服务特点",
    "pain_points": "用户痛点",
    "story": "品牌故事",
}


def _has_key(key: str, hints: tuple[str, ...]) -> bool:
    low = key.lower()
    return any(hint.lower() in low for hint in hints)


def gather_evidence(db: Session, project_id) -> dict[str, Any]:
    """只读地收集四类证据，供规则映射和模型提示词共用一份。"""

    facts = list(
        db.scalars(
            select(Fact)
            .where(Fact.project_id == project_id, Fact.approval_status == FactStatus.APPROVED)
            .order_by(Fact.fact_key)
            .limit(EVIDENCE_FACT_LIMIT)
        )
    )
    chunks = list(
        db.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.project_id == project_id)
            .order_by(KnowledgeChunk.created_at.desc())
            .limit(EVIDENCE_CHUNK_LIMIT)
        )
    )
    questions = list(
        db.scalars(
            select(Question)
            .where(Question.project_id == project_id, Question.status == QuestionStatus.ACTIVE)
            .order_by(Question.priority.asc(), Question.created_at.asc())
            .limit(EVIDENCE_QUESTION_LIMIT)
        )
    )
    brand = db.scalar(select(BrandProfile).where(BrandProfile.project_id == project_id))
    profile = db.scalar(select(CompanyProfile).where(CompanyProfile.project_id == project_id))

    return {
        "facts": [
            {
                "type": getattr(item.fact_type, "value", str(item.fact_type)),
                "key": item.fact_key,
                "value": item.fact_value.strip(),
            }
            for item in facts
        ],
        "chunks": [item.text.strip()[:EVIDENCE_CHUNK_CHARS] for item in chunks if item.text.strip()],
        "questions": [item.title.strip() for item in questions if item.title.strip()],
        "brand": {
            "canonical_name": brand.canonical_name if brand else None,
            "owned_domains": list(brand.owned_domains or []) if brand else [],
        },
        "current": {
            "legal_name": profile.legal_name if profile else None,
            "brand_name": profile.brand_name if profile else None,
            "slogan": profile.slogan if profile else None,
            "province": profile.province if profile else None,
            "business_phone": profile.business_phone if profile else None,
            "service_hotline": profile.service_hotline if profile else None,
            "contact_email": profile.contact_email if profile else None,
            "industries": list(profile.industries or []) if profile else [],
            "regions": list(profile.regions or []) if profile else [],
            "stores": list(profile.stores or []) if profile else [],
            "description": profile.description if profile else None,
            "founder_intro": profile.founder_intro if profile else None,
            "highlights": profile.highlights if profile else None,
            "pain_points": profile.pain_points if profile else None,
            "story": profile.story if profile else None,
        },
    }


def evidence_counts(evidence: dict[str, Any]) -> dict[str, int]:
    return {
        "facts": len(evidence["facts"]),
        "knowledge_chunks": len(evidence["chunks"]),
        "questions": len(evidence["questions"]),
        "owned_domains": len(evidence["brand"]["owned_domains"]),
    }


def rule_fields(evidence: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """事实到字段的 1:1 映射；只搬已批准事实，不写任何新句子。"""

    fields: dict[str, Any] = {}
    basis: dict[str, str] = {}
    products: list[dict[str, Any]] = []
    copy_lines: list[str] = []

    for fact in evidence["facts"]:
        fact_type = fact["type"]
        key = fact["key"]
        value = fact["value"]
        if not value:
            continue

        if fact_type == FactType.ORGANIZATION.value and _has_key(key, NAME_KEY_HINTS):
            if not fields.get("legal_name"):
                fields["legal_name"] = value
                basis["legal_name"] = f"事实库 · {key}"
        elif fact_type == FactType.BASE_ADDRESS.value and _has_key(key, ADDRESS_KEY_HINTS):
            stores = fields.setdefault("stores", [])
            if value not in stores and len(stores) < 10:
                stores.append(value)
                basis["stores"] = f"事实库 · {key}"
        elif fact_type == FactType.CONTACT.value:
            if _has_key(key, EMAIL_KEY_HINTS):
                if not fields.get("contact_email"):
                    fields["contact_email"] = value
                    basis["contact_email"] = f"事实库 · {key}"
            elif _has_key(key, PHONE_KEY_HINTS):
                target = "service_hotline" if ("售后" in key or "热" in key) else "business_phone"
                if not fields.get(target):
                    fields[target] = value
                    basis[target] = f"事实库 · {key}"
        elif fact_type == FactType.COURSE_NAME.value:
            if value not in {item["name"] for item in products} and len(products) < 8:
                products.append({"name": value, "summary": None, "highlights": None})
                basis["products"] = "事实库 · 课程名称"
        elif fact_type in {item.value for item in COPY_FACT_TYPES}:
            line = f"{key}：{value}"
            if line not in copy_lines and len(copy_lines) < 8:
                copy_lines.append(line)

    if products:
        fields["products"] = products
    if copy_lines:
        fields["highlights"] = "；".join(copy_lines)[:500]
        basis["highlights"] = "事实库 · 培训结果/就业服务/合作方/资质/师资"

    brand_name = evidence["brand"]["canonical_name"]
    if brand_name and not fields.get("brand_name"):
        fields["brand_name"] = brand_name
        basis["brand_name"] = "品牌设置 · 规范名称"

    return fields, basis


def pick_chat_entry(db: Session) -> AiEngineEntry | None:
    """挑一个能聊天的入口：OpenAI 兼容协议 + 有 model_name + 凭据齐全。

    这里只借用「已有模型能力」，不新建引擎，也不改 `ai_engines` 基线口径。
    """

    entries = list(
        db.scalars(
            select(AiEngineEntry).where(
                AiEngineEntry.protocol == EngineProtocol.OPENAI_COMPATIBLE,
                AiEngineEntry.is_active.is_(True),
            )
        )
    )
    for entry in entries:
        if not entry.entry_url or not entry.model_name:
            continue
        try:
            if resolve_entry_secret(entry):
                return entry
        except Exception:  # 凭据缺失只影响 AI 路径，不该让整个接口失败
            continue
    return None


SYSTEM_PROMPT = "你是中文 B2B 企业档案编辑，只根据给定证据写作，绝不补编事实。"

USER_PROMPT = """下面是一个项目的证据。请把它整理成企业档案字段，只输出 JSON 对象，不要任何解释。

硬规则：
1. 只使用证据里出现的信息；证据没有的字段输出 null（数组字段输出空数组）。
2. 不许编造数字（成立时间、员工数、电话、资质、奖项、排名）。
3. 公司介绍 100–1000 字，第三人称，写清「做什么、为谁做、凭什么可信」；证据不足 100 字就输出 null。
4. 创始人介绍 100–1000 字；没有创始人/校长相关信息就输出 null。
5. 产品最多 6 条，name 必填；summary/highlights 没有证据就 null。
6. 不要写「行业领先」「第一」「官方认证」这类没有证据的话。

输出字段：legal_name, brand_name, slogan, province, business_phone, service_hotline, contact_email,
industries(数组), regions(数组), stores(数组), products(数组: name/summary/highlights),
description, founder_intro, highlights, pain_points, story

证据（JSON）：
{evidence}
"""


def _evidence_prompt(evidence: dict[str, Any]) -> str:
    payload = {
        "facts": evidence["facts"],
        "knowledge_excerpts": evidence["chunks"],
        "monitored_questions": evidence["questions"],
        "brand": evidence["brand"],
        "current_profile": evidence["current"],
    }
    return USER_PROMPT.replace(
        "{evidence}", json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """模型常给 ```json 包一层，这里取第一个平衡的大括号块。"""

    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(cleaned[start : index + 1])
                except ValueError:
                    return None
                return data if isinstance(data, dict) else None
    return None


def draft_with_model(entry: AiEngineEntry, evidence: dict[str, Any]) -> dict[str, Any] | None:
    """调用模型起草；任何异常都返回 None，由调用方退回规则路径。"""

    endpoint = entry.entry_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"
    headers = {"Content-Type": "application/json"}
    secret = ""
    try:
        secret = resolve_entry_secret(entry)
    except Exception:
        pass
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    body = {
        "model": entry.model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _evidence_prompt(evidence)},
        ],
        "temperature": 0.1,
        "max_tokens": 1500,
        "stream": False,
    }
    try:
        with httpx.Client(timeout=DRAFT_TIMEOUT_SECONDS) as client:
            response = client.post(endpoint, headers=headers, json=body)
    except httpx.HTTPError:
        return None
    if response.status_code >= 400:
        return None
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    if not isinstance(content, str) or not content.strip():
        return None
    return _extract_json_object(content)


def _normalize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """用请求模型的宽松版收口：超长截断、短文案丢弃、产品去空名。

    模型返回什么格式都不可信，这一层是唯一的形状闸门。
    """

    allowed = set(CompanyProfileDraftFields.model_fields)
    payload = {key: value for key, value in fields.items() if key in allowed}
    products = payload.get("products")
    if isinstance(products, list):
        payload["products"] = [
            item
            for item in products
            if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip()
        ]
    elif products is not None:
        payload.pop("products", None)
    try:
        model = CompanyProfileDraftFields(**payload)
    except ValidationError:
        return {}
    dumped = model.model_dump(exclude_none=True)
    # 空数组不进响应：前端只关心「有哪些项可填」，空壳会让来源列表显示一堆空标签。
    return {key: value for key, value in dumped.items() if value not in ([], "")}


def build_draft(db: Session, project_id, *, prefer: str = "auto") -> dict[str, Any]:
    evidence = gather_evidence(db, project_id)
    counts = evidence_counts(evidence)
    fields, basis = rule_fields(evidence)

    entry = None if prefer == "rule" else pick_chat_entry(db)
    mode = "rule"
    note = None
    if entry is not None:
        drafted = draft_with_model(entry, evidence)
        if drafted:
            mode = "ai"
            for key, value in drafted.items():
                if key not in DRAFT_FIELD_LABELS or value in (None, "", [], {}):
                    continue
                # 模型只补事实没有覆盖的字段，事实永远是第一优先
                fields.setdefault(key, value)
                basis.setdefault(key, f"模型起草 · {entry.model_name}")
        else:
            note = f"模型 {entry.model_name} 没有返回可用结果，已退回事实整理"
    else:
        note = "项目内还没有可用的 OpenAI 兼容模型，本次只做事实整理，不是 AI 生成"

    if not fields:
        note = "事实库还没有已批准的事实、知识库也没有解析内容，先补数据再来一键填表"

    normalized = _normalize_fields(fields)
    basis = {key: value for key, value in basis.items() if key in normalized}
    return {
        "mode": mode,
        "model": entry.model_name if mode == "ai" else None,
        "fields": normalized,
        "basis": basis,
        "note": note,
        "evidence": counts,
    }
