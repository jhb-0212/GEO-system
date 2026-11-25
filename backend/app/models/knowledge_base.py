"""知识库：文档解析、切块检索与候选事实。

设计边界：
- 知识库不是把整份文档直接喂给生成模型，只提供可回查的 chunk 与已批准事实；
- 候选事实必须人工确认后才写 facts，候选本身不参与对外报告与内容生成；
- embedding 字段先留 JSONB，当前环境没有 pgvector 扩展时用词法/三元组检索降级。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import (
    FactType,
    KnowledgeCandidateStatus,
    KnowledgeParseStatus,
)


class KnowledgeDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一份已解析素材：同一项目同一素材只保留一份当前解析结果。"""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("project_id", "material_id", name="uq_knowledge_documents_project_material"),
        Index("ix_knowledge_documents_project_status", "project_id", "parse_status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    parse_status: Mapped[KnowledgeParseStatus] = mapped_column(
        str_enum(KnowledgeParseStatus, "knowledge_parse_status"),
        nullable=False,
        default=KnowledgeParseStatus.PENDING,
        server_default=KnowledgeParseStatus.PENDING.value,
    )
    parser_version: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(String(16))
    checksum: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class KnowledgeChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """文档切块：600–800 token，保留页码与章节，检索结果必须能回到原文。"""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_no", name="uq_knowledge_chunks_document_chunk"),
        Index("ix_knowledge_chunks_project_document", "project_id", "document_id"),
        Index(
            "ix_knowledge_chunks_embedding_hnsw",
            "embedding_vec",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding_vec": "vector_cosine_ops"},
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_no: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(255))
    # JSONB 保留给无 pgvector 的旧库降级；新库同时写 embedding_vec 走 HNSW。
    embedding: Mapped[list[float] | None] = mapped_column(JSONB)
    embedding_vec: Mapped[list[float] | None] = mapped_column(Vector(1024))
    embedding_model: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB)


class KnowledgeCandidateFact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """候选事实：只代表“文档里可能是一条事实”，人工采纳后才写 facts。"""

    __tablename__ = "knowledge_candidate_facts"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "document_id", "fingerprint",
            name="uq_knowledge_candidate_facts_project_document_fingerprint",
        ),
        Index("ix_knowledge_candidate_facts_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="CASCADE")
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255))
    predicate: Mapped[str | None] = mapped_column(String(128))
    object: Mapped[str | None] = mapped_column(Text)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_fact_type: Mapped[FactType] = mapped_column(
        str_enum(FactType, "fact_type"), nullable=False
    )
    suggested_fact_key: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5, server_default="0.5")
    source_page: Mapped[int | None] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[KnowledgeCandidateStatus] = mapped_column(
        str_enum(KnowledgeCandidateStatus, "knowledge_candidate_status"),
        nullable=False,
        default=KnowledgeCandidateStatus.SUGGESTED,
        server_default=KnowledgeCandidateStatus.SUGGESTED.value,
    )
    fact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facts.id", ondelete="SET NULL"))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
