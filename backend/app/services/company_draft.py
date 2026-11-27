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
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.credentials import read_credential_env
from app.core.secrets_box import decrypt_secret, encrypt_secret, has_encrypted_secret
from app.models import BrandProfile, CompanyDraftModel, CompanyProfile, Fact, KnowledgeChunk, Question
from app.models.enums import FactStatus, FactType
from app.models.engine import AiEngineEntry
from app.models.enums import EngineProtocol, QuestionStatus
from app.schemas.company import CompanyProfileDraftFields
from app.services.engine_credentials import resolve_entry_secret

# 起草是一次性的短任务，超时给够一次「读证据 + 写两段长文案」，但不要长到把页面卡住。
DRAFT_TIMEOUT_SECONDS = 45.0

# 默认模型：DeepSeek 官方接口（key 取 `.env` 的 DEEPSEEK_API_KEY）。
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_KEY_REF = "DEEPSEEK_API_KEY"


@dataclass(frozen=True)
class ChatTarget:
    """一次起草要用的模型身份：地址 + 型号 + Key，只在内存里存在。"""

    base_url: str
    model: str
    secret: str

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
            "aliases": list(brand.aliases or []) if brand else [],
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


def brand_name_candidate(evidence: dict[str, Any], legal_name: str | None) -> str | None:
    """挑「公司品牌」的候选值：品牌设置里的规范名/别名，但不能是工商全称。

    品牌设置里的 canonical_name 常常就是工商主体名（用于提及判定），
    直接搬进「公司品牌」会出现「公司名称」与「公司品牌」完全相同的荒唐结果。
    """

    values: list[str] = []
    brand = evidence.get("brand") or {}
    for raw in [brand.get("canonical_name"), *(brand.get("aliases") or [])]:
        clean = (raw or "").strip() if isinstance(raw, str) else ""
        if clean and clean not in values:
            values.append(clean)
    target = (legal_name or "").strip()
    for value in values:
        if target and value == target:
            continue
        return value
    return None


def _drop_legal_name_as_brand(fields: dict[str, Any], evidence: dict[str, Any]) -> None:
    """模型或规则把工商全称填进「公司品牌」时，换成真正的品牌名；换不到就留空。"""

    legal = fields.get("legal_name")
    brand = fields.get("brand_name")
    if not isinstance(brand, str):
        return
    if not isinstance(legal, str) or not legal.strip() or brand.strip() != legal.strip():
        return
    replacement = brand_name_candidate(evidence, legal)
    if replacement:
        fields["brand_name"] = replacement
    else:
        fields.pop("brand_name", None)


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

    brand_name = brand_name_candidate(evidence, fields.get("legal_name"))
    if brand_name and not fields.get("brand_name"):
        fields["brand_name"] = brand_name
        basis["brand_name"] = "品牌设置 · 品牌名/别名"

    return fields, basis


def pick_chat_target(db: Session, project_id=None) -> ChatTarget | None:
    """选一个能写字的模型，顺序：项目配置 > DeepSeek 环境变量 > 引擎入口。

    项目配置排第一，是为了让运营在界面上填的 Key 立刻生效——不必改 `.env`、
    不必重启后端。没配过的项目继续走环境变量，老部署不受影响。
    """

    if project_id is not None:
        setting = db.scalar(
            select(CompanyDraftModel).where(CompanyDraftModel.project_id == project_id)
        )
        if setting is not None and setting.is_active:
            secret = decrypt_secret(setting.encrypted_secret)
            if secret and setting.base_url and setting.model:
                return ChatTarget(setting.base_url, setting.model, secret)

    deepseek_key = read_credential_env(DEEPSEEK_KEY_REF)
    if deepseek_key:
        return ChatTarget(DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, deepseek_key)

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
            secret = resolve_entry_secret(entry)
        except Exception:  # 凭据缺失只影响 AI 路径，不该让整个接口失败
            continue
        if secret:
            return ChatTarget(entry.entry_url, entry.model_name, secret)
    return None


def load_model_setting(db: Session, project_id) -> CompanyDraftModel | None:
    return db.scalar(select(CompanyDraftModel).where(CompanyDraftModel.project_id == project_id))


def serialize_model_setting(db: Session, project_id) -> dict[str, Any]:
    """给界面看的配置快照：只回显「有没有 Key」，不回显 Key 本身。"""

    setting = load_model_setting(db, project_id)
    project_secret = decrypt_secret(setting.encrypted_secret) if setting else ""
    env_key = read_credential_env(DEEPSEEK_KEY_REF)

    if setting is not None and project_secret and setting.is_active:
        source = "project"
    elif env_key:
        source = "env"
    else:
        source = "none"

    return {
        "configured": source != "none",
        "source": source,
        "base_url": setting.base_url if setting else DEEPSEEK_BASE_URL,
        "model": setting.model if setting else DEEPSEEK_MODEL,
        "has_secret": has_encrypted_secret(setting.encrypted_secret) if setting else False,
        "is_active": setting.is_active if setting else True,
        # 环境变量里那把 Key 的指纹，用来确认「现在生效的是哪把」而不泄露内容
        "env_key_hint": _key_hint(env_key),
        "updated_at": setting.updated_at if setting else None,
    }


def _key_hint(secret: str) -> str | None:
    """Key 指纹：只留前 6 位和后 4 位，够核对身份，不够复原。"""

    value = (secret or "").strip()
    if len(value) < 12:
        return None
    return f"{value[:6]}…{value[-4:]}"


def save_model_setting(
    db: Session,
    project_id,
    *,
    base_url: str | None,
    model: str | None,
    api_key: str | None,
    clear_key: bool = False,
    is_active: bool | None = None,
    actor_id=None,
) -> CompanyDraftModel:
    """写入项目级起草模型配置；`api_key` 为空表示不修改已存的 Key。"""

    setting = load_model_setting(db, project_id)
    if setting is None:
        setting = CompanyDraftModel(project_id=project_id)
        db.add(setting)

    if base_url is not None:
        clean_url = base_url.strip().rstrip("/")
        setting.base_url = clean_url or DEEPSEEK_BASE_URL
    if model is not None:
        setting.model = model.strip() or DEEPSEEK_MODEL
    if clear_key:
        setting.encrypted_secret = None
    elif api_key:
        setting.encrypted_secret = encrypt_secret(api_key)
    if is_active is not None:
        setting.is_active = is_active
    setting.updated_by = actor_id

    db.flush()
    return setting


def test_chat_target(target: ChatTarget) -> tuple[bool, str]:
    """用一句最小请求验证 Key/地址/型号三件套是否真的能用。"""

    endpoint = target.base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"
    body = {
        "model": target.model,
        "messages": [{"role": "user", "content": "只回复两个字符：OK"}],
        "temperature": 0,
        "max_tokens": 16,
    }
    headers = {"Content-Type": "application/json"}
    if target.secret:
        headers["Authorization"] = f"Bearer {target.secret}"
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(endpoint, headers=headers, json=body)
    except httpx.HTTPError as exc:
        return False, f"连不上 {endpoint}：{type(exc).__name__}"
    if response.status_code >= 400:
        detail = ""
        try:
            payload = response.json()
            detail = str(payload.get("error") or payload)[:120]
        except ValueError:
            detail = response.text[:120]
        return False, f"HTTP {response.status_code}：{detail}"
    try:
        reply = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return False, "返回结构不是 chat/completions 格式"
    actual_model = ""
    try:
        actual_model = str(response.json().get("model") or "")
    except ValueError:
        actual_model = ""
    suffix = f"（接口回显模型 {actual_model}）" if actual_model and actual_model != target.model else ""
    return True, f"连接正常，模型可用{suffix}：{(reply or '').strip()[:40]}"



SYSTEM_PROMPT = "你是中文 B2B 企业档案编辑，只根据给定证据写作，绝不补编事实。"

USER_PROMPT = """下面是一个项目的证据。请把它整理成企业档案字段，只输出 JSON 对象，不要任何解释。

硬规则：
1. 只使用证据里出现的信息；证据没有的字段输出 null（数组字段输出空数组）。
2. 不许编造数字（成立时间、员工数、电话、资质、奖项、排名）。
3. 公司介绍 100–1000 字，第三人称，写清「做什么、为谁做、凭什么可信」；证据不足 100 字就输出 null。
4. 创始人介绍 100–1000 字；没有创始人/校长相关信息就输出 null。
5. 产品最多 6 条，name 必填；summary/highlights 没有证据就 null。
6. 不要写「行业领先」「第一」「官方认证」这类没有证据的话。
7. brand_name 是对外品牌名/字号，不能填工商全称（等于 legal_name 就输出 null）；
   证据里没有独立品牌名就 null，绝不用公司名称顶替。

输出字段：legal_name, brand_name, slogan, province, business_phone, service_hotline, contact_email,
industries(数组), regions(数组), stores(数组), products(数组: name/summary/highlights),
description, founder_intro, highlights, pain_points, story

数组格式：industries / regions / stores 的每个元素都是**字符串**，不要写成对象
（stores 写成「番山创业中心1号楼2区207」这种，不要 name/address 字段）。
products 的每个元素是对象，name 必填。

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


def draft_with_model(target: ChatTarget, evidence: dict[str, Any]) -> dict[str, Any] | None:
    """调用模型起草；任何异常都返回 None，由调用方退回规则路径。"""

    endpoint = target.base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if target.secret:
        headers["Authorization"] = f"Bearer {target.secret}"

    body: dict[str, Any] = {
        "model": target.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _evidence_prompt(evidence)},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
        "stream": False,
    }
    # DeepSeek 支持 json_object 模式；其他兼容端不一定认这个字段，所以只对官方域名加。
    if "api.deepseek.com" in endpoint:
        body["response_format"] = {"type": "json_object"}
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


def _coerce_string_list(value: Any) -> list[str]:
    """数组字段容错：模型偶尔把 stores 写成 `{name, address}`，这里取第一个像样的字符串。

    一个字段形状不对不该让整批建议作废——这是「逐字段校验」存在的理由。
    """

    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            clean = item.strip()
        elif isinstance(item, dict):
            clean = ""
            for key in ("name", "address", "title", "value", "label"):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    clean = candidate.strip()
                    break
        else:
            clean = ""
        if clean and clean not in result:
            result.append(clean)
    return result[:10]


def _normalize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """逐字段收口：超长截断、短文案丢弃、产品去空名、数组形状容错。

    模型返回的 JSON 不可信，这里逐项用请求模型校验；单字段不合法只丢该字段，
    不整批作废（此前一段 description 不足 100 字会让公司名称、电话一起消失）。
    """

    allowed = set(CompanyProfileDraftFields.model_fields)
    result: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in allowed or value in (None, "", [], {}):
            continue
        if key in ("industries", "regions", "stores"):
            clean_list = _coerce_string_list(value)
            if clean_list:
                result[key] = clean_list
            continue
        if key == "products":
            if not isinstance(value, list):
                continue
            products = [
                item
                for item in value
                if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip()
            ]
            if products:
                result[key] = products[:6]
            continue
        if not isinstance(value, str):
            continue
        try:
            single = CompanyProfileDraftFields(**{key: value})
        except ValidationError:
            continue
        dumped = single.model_dump(exclude_none=True)
        clean = dumped.get(key)
        if clean:
            result[key] = clean
    return result


def build_draft(db: Session, project_id, *, prefer: str = "auto") -> dict[str, Any]:
    evidence = gather_evidence(db, project_id)
    counts = evidence_counts(evidence)
    fields, basis = rule_fields(evidence)

    target = None if prefer == "rule" else pick_chat_target(db, project_id)
    mode = "rule"
    note = None
    if target is not None:
        drafted = draft_with_model(target, evidence)
        if drafted:
            mode = "ai"
            for key, value in drafted.items():
                if key not in DRAFT_FIELD_LABELS or value in (None, "", [], {}):
                    continue
                # 模型只补事实没有覆盖的字段，事实永远是第一优先
                fields.setdefault(key, value)
                basis.setdefault(key, f"模型起草 · {target.model}")
        else:
            note = f"模型 {target.model} 没有返回可用结果，已退回事实整理"
    else:
        note = "没有可用的起草模型：在档案页「起草模型」里填 Key，或配 DEEPSEEK_API_KEY、加一个 OpenAI 兼容入口"

    _drop_legal_name_as_brand(fields, evidence)

    if not fields:
        note = "事实库还没有已批准的事实、知识库也没有解析内容，先补数据再来一键填表"

    normalized = _normalize_fields(fields)
    basis = {key: value for key, value in basis.items() if key in normalized}
    return {
        "mode": mode,
        "model": target.model if mode == "ai" else None,
        "fields": normalized,
        "basis": basis,
        "note": note,
        "evidence": counts,
    }
