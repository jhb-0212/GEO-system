"""知识库检索：当前没有 pgvector，先用中文二元组 + 英文词的词法检索。

返回结果必须带文档、页码与原文，前端不把整份文档塞给模型；后续接入 embedding
时，在这个函数里增加向量召回并做 RRF 融合即可。
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument, Material
from app.models.enums import KnowledgeParseStatus
from app.services import knowledge_embedding

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-z0-9]+", re.I)
_STOP = {"的", "了", "是", "在", "和", "与", "及", "或", "有", "为", "对", "从", "到", "把", "被"}
SIMILARITY_FLOOR = 0.08


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def query_terms(query: str) -> list[str]:
    terms: list[str] = []
    normalized = query.lower()
    for word in _WORD.findall(normalized):
        if len(word) >= 2:
            terms.append(word)
    for run in _CJK_RUN.findall(normalized):
        if len(run) == 1:
            terms.append(run)
        for index in range(len(run) - 1):
            gram = run[index:index + 2]
            if gram not in _STOP:
                terms.append(gram)
    return list(dict.fromkeys(terms))


def _score(query: str, terms: list[str], text: str, title: str) -> tuple[float, list[str]]:
    normalized_text = _normalize(text)
    normalized_title = _normalize(title)
    normalized_query = _normalize(query)
    hits = [term for term in terms if term in normalized_text]
    if not terms or not hits:
        return 0.0, []
    coverage = len(hits) / len(terms)
    score = coverage * 2.0
    if normalized_query and normalized_query in normalized_text:
        score += 2.0
    title_hits = [term for term in terms if term in normalized_title]
    if title_hits:
        score += min(0.8, 0.2 * len(title_hits))
    # 同一段里出现越多不同查询词，越可能是答案段。
    score += min(1.0, 0.1 * len(hits))
    return round(score, 4), hits[:8]


def search_chunks(
    db: Session,
    *,
    project_id: uuid.UUID,
    query: str,
    top_k: int = 8,
) -> dict:
    normalized_query = query.strip()
    if not normalized_query:
        return {"query": query, "search_mode": "lexical_trigram", "items": [], "total_scanned": 0}
    if len(normalized_query) > 200:
        normalized_query = normalized_query[:200]
    terms = query_terms(normalized_query)
    query_vector = None
    embedding_status = "not_configured"
    if knowledge_embedding.embedding_configured():
        vectors = knowledge_embedding.embed_texts([normalized_query])
        if vectors:
            query_vector = vectors[0]
            embedding_status = "ready"
        else:
            embedding_status = "failed"

    vector_distances: dict[str, float] = {}
    if query_vector:
        try:
            with db.begin_nested():
                vector_rows = db.execute(
                    select(
                        KnowledgeChunk.id,
                        KnowledgeChunk.embedding_vec.cosine_distance(query_vector).label("distance"),
                    )
                    .where(
                        KnowledgeChunk.project_id == project_id,
                        KnowledgeChunk.embedding_vec.isnot(None),
                    )
                    .order_by(KnowledgeChunk.embedding_vec.cosine_distance(query_vector))
                    .limit(50)
                ).all()
                vector_distances = {
                    str(row.id): max(0.0, 1.0 - float(row.distance))
                    for row in vector_rows
                    if row.distance is not None
                }
        except Exception:
            vector_distances = {}

    rows = db.execute(
        select(KnowledgeChunk, KnowledgeDocument, Material)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .join(Material, Material.id == KnowledgeDocument.material_id)
        .where(
            KnowledgeChunk.project_id == project_id,
            KnowledgeDocument.parse_status == KnowledgeParseStatus.READY.value,
        )
        .order_by(KnowledgeChunk.chunk_no)
        .limit(2000)
    ).all()

    scored: list[tuple[float, float, KnowledgeChunk, KnowledgeDocument, Material, list[str]]] = []
    vector_hits = 0
    for chunk, document, material in rows:
        lexical_score, hits = _score(normalized_query, terms, chunk.text, material.title)
        lexical_similarity = min(1.0, lexical_score / 3.0)
        vector_similarity = 0.0
        has_vector = bool(chunk.embedding or chunk.embedding_vec)
        if query_vector and has_vector:
            vector_similarity = vector_distances.get(str(chunk.id))
            if vector_similarity is None and chunk.embedding:
                vector_similarity = knowledge_embedding.cosine_similarity(query_vector, chunk.embedding)
            if vector_similarity is None:
                vector_similarity = 0.0
            if vector_similarity >= 0.45:
                vector_hits += 1
        if query_vector and has_vector:
            if vector_similarity < 0.45 and lexical_similarity < SIMILARITY_FLOOR:
                continue
            combined = round(0.55 * vector_similarity + 0.45 * lexical_similarity, 4)
            scored.append((combined, vector_similarity, chunk, document, material, hits))
        elif lexical_score >= SIMILARITY_FLOOR:
            scored.append((round(lexical_similarity, 4), 0.0, chunk, document, material, hits))
    scored.sort(key=lambda item: item[0], reverse=True)

    items = []
    for combined, vector_similarity, chunk, document, material, hits in scored[: max(1, min(top_k, 20))]:
        items.append(
            {
                "chunk_id": str(chunk.id),
                "document_id": str(chunk.document_id),
                "document_title": material.title,
                "file_name": material.file_name,
                "chunk_no": chunk.chunk_no,
                "page_from": chunk.page_from,
                "page_to": chunk.page_to,
                "section": chunk.section,
                "text": chunk.text,
                "score": round(combined * 3.0, 4),
                "similarity": round(combined, 4),
                "vector_similarity": round(vector_similarity, 4),
                "matched_terms": hits,
            }
        )
    search_mode = "hybrid_vector" if vector_hits else "lexical_trigram"
    if query_vector and vector_hits == 0:
        embedding_status = "missing_vectors"
    return {
        "query": normalized_query,
        "search_mode": search_mode,
        "embedding_status": embedding_status,
        "items": items,
        "total_scanned": len(rows),
    }
