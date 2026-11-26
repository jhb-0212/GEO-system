"""知识库解析：把素材文档解析为可回查的切块与候选事实。

当前环境没有 pgvector，embedding 只保留字段，检索走词法/三元组降级；
解析与切块逻辑不依赖向量库，后续切换 pgvector 不需要重写解析链。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader
from pptx import Presentation
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, BusinessValidationError, PathEscapeError
from app.models import Fact, KnowledgeCandidateFact, KnowledgeChunk, KnowledgeDocument, Material
from app.models.enums import (
    FactStatus,
    FactType,
    FactVersionAction,
    KnowledgeCandidateStatus,
    KnowledgeParseStatus,
)
from app.services.audit import record_audit
from app.services.fact_library import append_fact_version
from app.services.todo_clock import apply_candidate_status, apply_parse_status
from app.services import knowledge_embedding

PARSER_VERSION = "kb-parser-v1"
TARGET_TOKENS = 720
MIN_TOKENS = 600
MAX_TOKENS = 800
OVERLAP_TOKENS = 100
MAX_CANDIDATES_PER_DOCUMENT = 60

SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".pptx",
    ".txt",
    ".md",
    ".csv",
    ".html",
    ".htm",
}

_HEADING_PATTERN = re.compile(
    r"^(?:第[一二三四五六七八九十百]+[章节部分]|[0-9一二三四五六七八九十]+[、.．]\s*|#+)"
)
_FACT_SIGNAL = re.compile(
    r"(\d|是|为|位于|坐落|成立|创办|提供|包括|拥有|获得|认证|资质|合作|伙伴|电话|地址|官网|邮箱|课程|讲师|教师|就业|学员)"
)
_SENTENCE_SPLIT = re.compile(r"([。！？!?；;]\s*|\n+)")
_SENTENCE_JOIN = "。"
_CJK = re.compile(r"[\u4e00-\u9fff]")
_WORD = re.compile(r"[A-Za-z0-9]+")


@dataclass
class ParsedPage:
    page_no: int
    text: str


@dataclass
class TextUnit:
    text: str
    page_no: int
    section: str | None


def estimate_tokens(text: str) -> int:
    """中文按字、英文/数字按词估算；只用于切块，不冒充真实 tokenizer。"""
    return len(_CJK.findall(text)) + len(_WORD.findall(text))


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_repeated_lines(pages: list[ParsedPage]) -> list[ParsedPage]:
    """去掉页眉页脚与重复行：在多数页面出现的首尾短行不进入正文。"""
    if len(pages) < 3:
        return pages
    candidates: dict[str, int] = {}
    for page in pages:
        lines = [line.strip() for line in page.text.splitlines() if line.strip()]
        for line in lines[:2] + lines[-2:]:
            if len(line) <= 40:
                candidates[line] = candidates.get(line, 0) + 1
    repeated = {line for line, count in candidates.items() if count >= max(3, len(pages) // 3)}
    if not repeated:
        return pages
    cleaned = []
    for page in pages:
        kept = [line for line in page.text.splitlines() if line.strip() not in repeated]
        cleaned.append(ParsedPage(page.page_no, _normalize("\n".join(kept))))
    return cleaned


def _detect_language(text: str) -> str:
    cjk = len(_CJK.findall(text))
    letters = len(re.findall(r"[A-Za-z]", text))
    if cjk == 0 and letters == 0:
        return "unknown"
    return "zh" if cjk >= max(1, letters // 3) else "en"


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BusinessValidationError("文本编码无法识别", code="knowledge_encoding_unsupported")


def _parse_pdf(path: Path) -> list[ParsedPage]:
    reader = PdfReader(str(path))
    pages: list[ParsedPage] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append(ParsedPage(index, _normalize(text)))
    if not any(page.text.strip() for page in pages):
        raise BusinessValidationError(
            "该 PDF 没有可提取文本，可能是扫描件；当前未接入 OCR",
            code="unsupported_scan",
        )
    return pages


def _parse_docx(path: Path) -> list[ParsedPage]:
    document = Document(str(path))
    lines: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            lines.append(text)
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                lines.append(" | ".join(cells))
    return [ParsedPage(1, _normalize("\n".join(lines)))]


def _parse_pptx(path: Path) -> list[ParsedPage]:
    presentation = Presentation(str(path))
    pages: list[ParsedPage] = []
    for index, slide in enumerate(presentation.slides, start=1):
        lines: list[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                text = shape.text_frame.text.strip()
                if text:
                    lines.append(text)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if cells:
                        lines.append(" | ".join(cells))
        pages.append(ParsedPage(index, _normalize("\n".join(lines))))
    return pages


def _parse_html(path: Path) -> list[ParsedPage]:
    soup = BeautifulSoup(_read_text_file(path), "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    text = soup.get_text("\n")
    return [ParsedPage(1, _normalize(text))]


def _read_pages(path: Path, suffix: str) -> list[ParsedPage]:
    if suffix == ".pdf":
        pages = _parse_pdf(path)
    elif suffix == ".docx":
        pages = _parse_docx(path)
    elif suffix == ".pptx":
        pages = _parse_pptx(path)
    elif suffix in {".html", ".htm"}:
        pages = _parse_html(path)
    elif suffix in {".txt", ".md", ".csv"}:
        text = _read_text_file(path)
        if suffix == ".csv":
            text = text.replace(",", "，")
        pages = [ParsedPage(1, _normalize(text))]
    elif suffix == ".doc":
        raise BusinessValidationError(
            "旧版 .doc 暂不支持，请另存为 .docx 后再上传",
            code="knowledge_doc_unsupported",
        )
    else:
        raise BusinessValidationError(
            f"不支持的文档类型：{suffix or '未知'}",
            code="knowledge_unsupported",
        )
    return _strip_repeated_lines(pages)


def _looks_like_heading(text: str) -> bool:
    line = text.strip()
    return bool(line) and len(line) <= 40 and not line.endswith(("。", "！", "？", ".", "!", "?")) and (
        bool(_HEADING_PATTERN.match(line)) or " " not in line
    )


def _split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(text)]
    return [part for part in parts if part and part not in {"。", "！", "？", "；", ";", "!", "?"}]


def _to_units(pages: list[ParsedPage]) -> list[TextUnit]:
    units: list[TextUnit] = []
    section: str | None = None
    for page in pages:
        for block in re.split(r"\n{2,}", page.text):
            block = block.strip()
            if not block:
                continue
            for line in block.splitlines():
                line = line.strip()
                if not line:
                    continue
                if _looks_like_heading(line):
                    section = line[:255]
                    continue
                for sentence in _split_sentences(line) or [line]:
                    units.append(TextUnit(sentence, page.page_no, section))
    return units


def _hard_split(text: str, limit: int = TARGET_TOKENS) -> list[str]:
    """超长句按字符硬切，避免单块远超上限。"""
    pieces: list[str] = []
    rest = text
    while rest:
        if estimate_tokens(rest) <= limit:
            pieces.append(rest)
            break
        low, high = 1, len(rest)
        while low < high:
            mid = (low + high + 1) // 2
            if estimate_tokens(rest[:mid]) <= limit:
                low = mid
            else:
                high = mid - 1
        pieces.append(rest[:low])
        rest = rest[low:]
    return pieces


def chunk_pages(pages: list[ParsedPage]) -> list[dict]:
    units = _to_units(pages)
    chunks: list[dict] = []
    buffer: list[TextUnit] = []
    tokens = 0
    pending_new = False

    def flush() -> None:
        nonlocal buffer, tokens, pending_new
        if not buffer:
            return
        text = "\n".join(unit.text for unit in buffer).strip()
        if not text:
            buffer, tokens = [], 0
            return
        chunk_tokens = estimate_tokens(text)
        chunks.append(
            {
                "text": text,
                "token_count": chunk_tokens,
                "page_from": min(unit.page_no for unit in buffer),
                "page_to": max(unit.page_no for unit in buffer),
                "section": next((unit.section for unit in reversed(buffer) if unit.section), None),
            }
        )
        tail: list[TextUnit] = []
        tail_tokens = 0
        for unit in reversed(buffer):
            unit_tokens = estimate_tokens(unit.text)
            if tail_tokens + unit_tokens > OVERLAP_TOKENS:
                break
            tail.insert(0, unit)
            tail_tokens += unit_tokens
        buffer, tokens = tail, tail_tokens
        pending_new = False

    for unit in units:
        unit_tokens = estimate_tokens(unit.text)
        if unit_tokens > MAX_TOKENS:
            if buffer:
                flush()
            for piece in _hard_split(unit.text):
                piece_tokens = estimate_tokens(piece)
                chunks.append(
                    {
                        "text": piece,
                        "token_count": piece_tokens,
                        "page_from": unit.page_no,
                        "page_to": unit.page_no,
                        "section": unit.section,
                    }
                )
            buffer, tokens = [], 0
            pending_new = False
            continue
        if buffer and tokens + unit_tokens > MAX_TOKENS:
            flush()
        buffer.append(unit)
        tokens += unit_tokens
        pending_new = True
        if tokens >= TARGET_TOKENS:
            flush()

    if buffer and pending_new:
        flush()
    # 去掉只有重叠、没有新增内容的尾块。
    deduped: list[dict] = []
    for chunk in chunks:
        if deduped and chunk["text"] == deduped[-1]["text"]:
            continue
        if chunk["text"].strip():
            deduped.append(chunk)
    return deduped


def _infer_fact_type(claim: str) -> FactType:
    if re.search(r"(电话|手机|邮箱|微信|公众号|联系人)", claim):
        return FactType.CONTACT
    if re.search(r"(地址|位于|坐落|园区|号楼|Road|Street)", claim):
        return FactType.BASE_ADDRESS
    if re.search(r"(认证|资质|证书|牌照|许可)", claim):
        return FactType.CERTIFICATION
    if re.search(r"(合作|伙伴|联合|共建)", claim):
        return FactType.PARTNER
    if re.search(r"(讲师|教师|师资|导师|教授)", claim):
        return FactType.FACULTY
    if re.search(r"(课程|班型|课时|学费|培训)", claim):
        return FactType.COURSE_CONTENT
    if re.search(r"(就业|学员|毕业|入职|薪资|offer)", claim, re.I):
        return FactType.EMPLOYMENT_SERVICE
    return FactType.ORGANIZATION


def _split_claim(claim: str) -> tuple[str, str, str]:
    for delimiter in ("是", "为", "位于", "坐落于", "成立于", "提供", "包括", "拥有"):
        if delimiter in claim:
            left, right = claim.split(delimiter, 1)
            if left.strip() and right.strip():
                return left.strip()[:120], delimiter, right.strip()[:200]
    return claim[:60], "", ""


def _fact_key(claim: str) -> str:
    key = re.sub(r"[\s“”\"'，。！？；：、]+", " ", claim).strip()
    return key[:60] or "知识库事实"


def _fingerprint(claim: str) -> str:
    normalized = re.sub(r"\s+", "", claim)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_candidates(chunks: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    seen: set[str] = set()
    for chunk in chunks:
        for sentence in _split_sentences(chunk["text"]):
            claim = sentence.strip()
            if not (12 <= len(claim) <= 300):
                continue
            if not _FACT_SIGNAL.search(claim):
                continue
            fingerprint = _fingerprint(claim)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            subject, predicate, object_text = _split_claim(claim)
            fact_type = _infer_fact_type(claim)
            confidence = 0.5
            if re.search(r"\d", claim):
                confidence += 0.15
            if fact_type in {FactType.BASE_ADDRESS, FactType.CONTACT, FactType.CERTIFICATION}:
                confidence += 0.1
            candidates.append(
                {
                    "claim_text": claim,
                    "subject": subject,
                    "predicate": predicate,
                    "object": object_text,
                    "evidence_text": claim,
                    "suggested_fact_type": fact_type,
                    "suggested_fact_key": _fact_key(claim),
                    "confidence": min(round(confidence, 2), 0.9),
                    "source_page": chunk.get("page_from"),
                    "fingerprint": fingerprint,
                }
            )
            if len(candidates) >= MAX_CANDIDATES_PER_DOCUMENT:
                return candidates
    return candidates


def _material_path(material: Material) -> tuple[Path, Path]:
    root = settings.evidence_root.resolve()
    target = (root / material.storage_key).resolve()
    if root not in target.parents:
        raise PathEscapeError("素材路径非法")
    if not target.is_file():
        raise BusinessValidationError("素材文件不存在，请重新上传", code="knowledge_material_missing")
    return root, target


def parse_material(
    db: Session,
    *,
    project_id: uuid.UUID,
    material: Material,
    actor_id: uuid.UUID,
) -> dict:
    suffix = Path(material.file_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise BusinessValidationError(
            f"该素材不支持知识库解析：{suffix or '未知类型'}",
            code="knowledge_unsupported",
        )
    _, path = _material_path(material)

    existing = db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.project_id == project_id,
            KnowledgeDocument.material_id == material.id,
        )
    )
    if existing is not None and existing.parse_status == KnowledgeParseStatus.READY and existing.checksum == material.checksum:
        return document_payload(db, existing, material)

    if existing is None:
        document = KnowledgeDocument(
            project_id=project_id,
            material_id=material.id,
            parse_status=KnowledgeParseStatus.PARSING,
            # 首次解析直接创建即 parsing，成员资格自素材创建起就成立：
            # 继承素材进入待办的时间，避免今日待办被虚增（ADR-01）
            entered_todo_at=material.created_at,
            parser_version=PARSER_VERSION,
            checksum=material.checksum,
            created_by=actor_id,
        )
        db.add(document)
        db.flush()
    else:
        document = existing
        apply_parse_status(document, KnowledgeParseStatus.PARSING)
        document.parser_version = PARSER_VERSION
        document.checksum = material.checksum
        document.error = None
        document.parsed_at = None
        db.execute(delete(KnowledgeCandidateFact).where(KnowledgeCandidateFact.document_id == document.id))
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
        db.flush()

    try:
        pages = _read_pages(path, suffix)
        chunks = chunk_pages(pages)
        if not chunks:
            raise BusinessValidationError("文档没有可切分的正文", code="knowledge_empty_document")
        candidates = extract_candidates(chunks)
        full_text = "\n".join(page.text for page in pages)

        chunk_rows: list[KnowledgeChunk] = []
        for index, chunk in enumerate(chunks, start=1):
            row = KnowledgeChunk(
                project_id=project_id,
                document_id=document.id,
                chunk_no=index,
                text=chunk["text"],
                token_count=chunk["token_count"],
                page_from=chunk["page_from"],
                page_to=chunk["page_to"],
                section=chunk["section"],
                metadata_json={"parser_version": PARSER_VERSION},
            )
            db.add(row)
            chunk_rows.append(row)
        db.flush()

        embedding_status = "not_configured"
        if knowledge_embedding.embedding_configured():
            vectors = knowledge_embedding.embed_texts([row.text for row in chunk_rows])
            if vectors:
                for row, vector in zip(chunk_rows, vectors):
                    row.embedding = vector
                    row.embedding_vec = vector
                    row.embedding_model = knowledge_embedding.embedding_model()
                embedding_status = "ready"
            else:
                embedding_status = "failed"

        for candidate, chunk_index in zip(candidates, _candidate_chunk_indexes(candidates, chunk_rows)):
            chunk_row = chunk_rows[chunk_index]
            db.add(
                KnowledgeCandidateFact(
                    project_id=project_id,
                    document_id=document.id,
                    chunk_id=chunk_row.id,
                    claim_text=candidate["claim_text"],
                    subject=candidate["subject"],
                    predicate=candidate["predicate"],
                    object=candidate["object"],
                    evidence_text=candidate["evidence_text"],
                    suggested_fact_type=candidate["suggested_fact_type"],
                    suggested_fact_key=candidate["suggested_fact_key"],
                    confidence=candidate["confidence"],
                    source_page=candidate["source_page"],
                    fingerprint=candidate["fingerprint"],
                    # 候选创建即 suggested，进入待办时间即创建时间（ADR-01）
                    entered_todo_at=datetime.now(timezone.utc),
                )
            )

        apply_parse_status(document, KnowledgeParseStatus.READY)
        document.page_count = len(pages)
        document.language = _detect_language(full_text)
        document.char_count = len(full_text)
        document.chunk_count = len(chunk_rows)
        document.candidate_count = len(candidates)
        document.parsed_at = datetime.now(timezone.utc)
        document.metadata_json = {
            "parser_version": PARSER_VERSION,
            "suffix": suffix,
            "embedding_status": embedding_status,
            "embedding_model": knowledge_embedding.embedding_model() if embedding_status == "ready" else None,
            "search_mode": "hybrid_vector" if embedding_status == "ready" else "lexical_trigram",
        }
        db.flush()
    except BusinessValidationError as error:
        apply_parse_status(document, KnowledgeParseStatus.UNSUPPORTED)
        document.error = str(error)
        document.page_count = 0
        document.char_count = 0
        document.chunk_count = 0
        document.candidate_count = 0
        db.flush()
        record_audit(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action="knowledge.parse",
            target_type="material",
            target_id=material.id,
            payload={"status": "unsupported", "code": error.code},
        )
        db.commit()
        return document_payload(db, document, material)
    except Exception as error:
        apply_parse_status(document, KnowledgeParseStatus.FAILED)
        document.error = f"{type(error).__name__}: {error}"[:500]
        document.chunk_count = 0
        document.candidate_count = 0
        db.flush()
        record_audit(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action="knowledge.parse",
            target_type="material",
            target_id=material.id,
            payload={"status": "failed"},
        )
        db.commit()
        raise AppError("文档解析失败，请检查文件格式后重试", code="knowledge_parse_failed") from error

    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="knowledge.parse",
        target_type="material",
        target_id=material.id,
        payload={
            "status": "ready",
            "pages": document.page_count,
            "chunks": document.chunk_count,
            "candidates": document.candidate_count,
        },
    )
    db.commit()
    db.refresh(document)
    return document_payload(db, document, material)


def _candidate_chunk_indexes(candidates: list[dict], chunks: list[KnowledgeChunk]) -> list[int]:
    """候选事实按原文片段反查所属 chunk；找不到时回落到首块。"""
    indexes: list[int] = []
    for candidate in candidates:
        claim = candidate["claim_text"]
        for index, chunk in enumerate(chunks):
            if claim and claim in chunk.text:
                indexes.append(index)
                break
        else:
            indexes.append(0)
    return indexes


def document_payload(db: Session, document: KnowledgeDocument, material: Material | None = None) -> dict:
    material = material or db.get(Material, document.material_id)
    return {
        "id": str(document.id),
        "project_id": str(document.project_id),
        "material_id": str(document.material_id),
        "material_title": material.title if material else None,
        "file_name": material.file_name if material else None,
        "category": material.category.value if material else None,
        "parse_status": document.parse_status.value,
        "parser_version": document.parser_version,
        "page_count": document.page_count,
        "language": document.language,
        "checksum": document.checksum,
        "error": document.error,
        "char_count": document.char_count,
        "chunk_count": document.chunk_count,
        "candidate_count": document.candidate_count,
        "embedding_status": (document.metadata_json or {}).get("embedding_status", "not_configured"),
        "search_mode": (document.metadata_json or {}).get("search_mode", "lexical_trigram"),
        "parsed_at": document.parsed_at.isoformat() if document.parsed_at else None,
        "created_at": document.created_at.isoformat() if document.created_at else None,
    }


def chunk_payload(chunk: KnowledgeChunk) -> dict:
    return {
        "id": str(chunk.id),
        "document_id": str(chunk.document_id),
        "chunk_no": chunk.chunk_no,
        "text": chunk.text,
        "token_count": chunk.token_count,
        "page_from": chunk.page_from,
        "page_to": chunk.page_to,
        "section": chunk.section,
    }


def candidate_payload(
    candidate: KnowledgeCandidateFact,
    document: KnowledgeDocument | None = None,
    material: Material | None = None,
) -> dict:
    return {
        "id": str(candidate.id),
        "document_id": str(candidate.document_id),
        "document_title": material.title if material else None,
        "chunk_id": str(candidate.chunk_id) if candidate.chunk_id else None,
        "claim_text": candidate.claim_text,
        "subject": candidate.subject,
        "predicate": candidate.predicate,
        "object": candidate.object,
        "evidence_text": candidate.evidence_text,
        "suggested_fact_type": candidate.suggested_fact_type.value,
        "suggested_fact_key": candidate.suggested_fact_key,
        "confidence": candidate.confidence,
        "source_page": candidate.source_page,
        "status": candidate.status.value,
        "fact_id": str(candidate.fact_id) if candidate.fact_id else None,
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        "review_note": candidate.review_note,
        "reviewed_at": candidate.reviewed_at.isoformat() if candidate.reviewed_at else None,
    }


def list_documents(db: Session, project_id: uuid.UUID, *, page: int, page_size: int) -> tuple[list[dict], int]:
    total = db.scalar(
        select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.project_id == project_id)
    ) or 0
    rows = db.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.project_id == project_id)
        .order_by(KnowledgeDocument.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [document_payload(db, row) for row in rows], int(total)


def list_chunks(
    db: Session, project_id: uuid.UUID, document_id: uuid.UUID, *, page: int, page_size: int
) -> tuple[list[dict], int]:
    filters = [KnowledgeChunk.project_id == project_id, KnowledgeChunk.document_id == document_id]
    total = db.scalar(select(func.count()).select_from(KnowledgeChunk).where(*filters)) or 0
    rows = db.scalars(
        select(KnowledgeChunk)
        .where(*filters)
        .order_by(KnowledgeChunk.chunk_no)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [chunk_payload(row) for row in rows], int(total)


def list_candidates(
    db: Session,
    project_id: uuid.UUID,
    *,
    status: KnowledgeCandidateStatus | None,
    document_id: uuid.UUID | None,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    filters = [KnowledgeCandidateFact.project_id == project_id]
    if status is not None:
        filters.append(KnowledgeCandidateFact.status == status)
    if document_id is not None:
        filters.append(KnowledgeCandidateFact.document_id == document_id)
    total = db.scalar(select(func.count()).select_from(KnowledgeCandidateFact).where(*filters)) or 0
    rows = db.execute(
        select(KnowledgeCandidateFact, KnowledgeDocument, Material)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeCandidateFact.document_id)
        .join(Material, Material.id == KnowledgeDocument.material_id)
        .where(*filters)
        .order_by(KnowledgeCandidateFact.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [candidate_payload(row[0], row[1], row[2]) for row in rows], int(total)


def accept_candidate(
    db: Session,
    *,
    project_id: uuid.UUID,
    candidate: KnowledgeCandidateFact,
    actor_id: uuid.UUID,
    fact_type: FactType | None,
    fact_key: str | None,
    fact_value: str | None,
    change_note: str | None,
) -> dict:
    if candidate.status != KnowledgeCandidateStatus.SUGGESTED:
        raise BusinessValidationError("该候选事实已处理", code="knowledge_candidate_reviewed")
    document = db.get(KnowledgeDocument, candidate.document_id)
    material = db.get(Material, document.material_id) if document else None
    resolved_type = fact_type or candidate.suggested_fact_type
    resolved_key = (fact_key or candidate.suggested_fact_key).strip()
    resolved_value = (fact_value or candidate.claim_text).strip()
    if not resolved_key or not resolved_value:
        raise BusinessValidationError("事实标识与内容不能为空", code="knowledge_candidate_empty")

    fact = Fact(
        project_id=project_id,
        fact_type=resolved_type,
        fact_key=resolved_key,
        fact_value=resolved_value,
        source_document=material.file_name if material else None,
        version_no=1,
        # 采纳创建的事实是 draft，属于待办集合（ADR-01）
        entered_todo_at=datetime.now(timezone.utc),
        created_by=actor_id,
    )
    db.add(fact)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise AppError("同一事实类型下该标识已存在，请修改事实标识后再采纳", code="fact_duplicate") from error
    append_fact_version(
        db,
        fact,
        action=FactVersionAction.CREATED,
        actor_id=actor_id,
        change_note=change_note or "知识库候选事实人工采纳",
    )
    apply_candidate_status(candidate, KnowledgeCandidateStatus.ACCEPTED)
    candidate.fact_id = fact.id
    candidate.review_note = change_note
    candidate.reviewed_by = actor_id
    candidate.reviewed_at = datetime.now(timezone.utc)
    db.flush()
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="knowledge.candidate.accept",
        target_type="knowledge_candidate_fact",
        target_id=candidate.id,
        payload={"fact_id": str(fact.id), "fact_type": resolved_type.value, "status": FactStatus.DRAFT.value},
    )
    db.commit()
    db.refresh(candidate)
    db.refresh(fact)
    return {"candidate": candidate_payload(candidate, document, material), "fact_id": str(fact.id), "fact_status": fact.approval_status.value}


def reject_candidate(
    db: Session,
    *,
    project_id: uuid.UUID,
    candidate: KnowledgeCandidateFact,
    actor_id: uuid.UUID,
    note: str | None,
) -> dict:
    if candidate.status != KnowledgeCandidateStatus.SUGGESTED:
        raise BusinessValidationError("该候选事实已处理", code="knowledge_candidate_reviewed")
    apply_candidate_status(candidate, KnowledgeCandidateStatus.REJECTED)
    candidate.review_note = note
    candidate.reviewed_by = actor_id
    candidate.reviewed_at = datetime.now(timezone.utc)
    record_audit(
        db,
        project_id=project_id,
        actor_id=actor_id,
        action="knowledge.candidate.reject",
        target_type="knowledge_candidate_fact",
        target_id=candidate.id,
        payload={"note": note},
    )
    db.commit()
    db.refresh(candidate)
    return candidate_payload(candidate)
