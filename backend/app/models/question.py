"""题库与关键词：监测任务引用固定的问题版本，历史记录不随题目修改而变义。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import (
    QuestionCandidateBucket,
    QuestionCandidateSource,
    QuestionCandidateStatus,
    QuestionStatus,
    QuestionType,
)


class Keyword(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """目标词：用于题目关联与品牌识别口径。"""

    __tablename__ = "keywords"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_keywords_project_name"),
        UniqueConstraint("project_id", "id", name="uq_keywords_project_id_id"),
        Index("ix_keywords_project_status", "project_id", "is_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    notes: Mapped[str | None] = mapped_column(Text)


class Question(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """标准问题：首期固定 6 道，区分品牌题与通用题。"""

    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_questions_project_code"),
        UniqueConstraint("project_id", "id", name="uq_questions_project_id_id"),
        Index("ix_questions_project_type_status", "project_id", "question_type", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    question_type: Mapped[QuestionType] = mapped_column(
        str_enum(QuestionType, "question_type"), nullable=False
    )
    audience: Mapped[str | None] = mapped_column(String(128))
    intent: Mapped[str | None] = mapped_column(String(128))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[QuestionStatus] = mapped_column(
        str_enum(QuestionStatus, "question_status"),
        nullable=False,
        default=QuestionStatus.DRAFT,
        server_default=QuestionStatus.DRAFT.value,
    )
    current_version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL")
    )


class QuestionVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """问题版本：不可覆盖改写，监测任务记录里锁定具体版本。

    除正文外，同时快照问题的测量语义（类型/受众/意图/优先级）。
    历史统计必须读取版本上的元数据，不能回读当前 Question 的字段，
    否则运营今天修改 intent/audience 会改变昨天样本的业务解释。
    """

    __tablename__ = "question_versions"
    __table_args__ = (
        UniqueConstraint("question_id", "version_no", name="uq_question_versions_question_version"),
        Index("ix_question_versions_project", "project_id"),
        UniqueConstraint("project_id", "id", name="uq_question_versions_project_id_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # 测量语义快照：新建版本时从 Question 复制，此后不随 Question 修改而变。
    question_type: Mapped[QuestionType | None] = mapped_column(
        str_enum(QuestionType, "question_version_type")
    )
    audience: Mapped[str | None] = mapped_column(String(128))
    intent: Mapped[str | None] = mapped_column(String(128))
    priority: Mapped[int | None] = mapped_column(Integer)
    change_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL")
    )


class QuestionVersionKeyword(UUIDPrimaryKeyMixin, Base):
    """问题版本与目标词的快照关联：历史样本按当时版本的关键词解释。"""

    __tablename__ = "question_version_keywords"
    __table_args__ = (
        UniqueConstraint(
            "question_version_id",
            "keyword_id",
            name="uq_question_version_keywords_version_keyword",
        ),
        Index("ix_question_version_keywords_project", "project_id"),
        Index("ix_question_version_keywords_version", "question_version_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    question_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="CASCADE"), nullable=False
    )
    keyword_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False)


class QuestionKeyword(UUIDPrimaryKeyMixin, Base):
    """题目与目标词的项目内关联；内容版本另用 content_version_keywords。"""

    __tablename__ = "question_keywords"
    __table_args__ = (
        UniqueConstraint("question_id", "keyword_id", name="uq_question_keywords_question_keyword"),
        Index("ix_question_keywords_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    keyword_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False)


class QuestionCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """问题候选池：先收集、后人工确认，绝不自动写入正式题库。

    `fingerprint` 是规范化文本的 SHA-256，用来挡住空格/标点差异导致的重复；
    只有 `status=accepted` 才代表已转成正式题目，并记录 `converted_question_id`。
    """

    __tablename__ = "question_candidates"
    __table_args__ = (
        UniqueConstraint("project_id", "fingerprint", name="uq_question_candidates_project_fingerprint"),
        Index("ix_question_candidates_project_status", "project_id", "status"),
        Index("ix_question_candidates_project_bucket", "project_id", "bucket"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    bucket: Mapped[QuestionCandidateBucket] = mapped_column(
        str_enum(QuestionCandidateBucket, "question_candidate_bucket"), nullable=False
    )
    question_type: Mapped[QuestionType] = mapped_column(
        str_enum(QuestionType, "question_candidate_type"), nullable=False
    )
    audience: Mapped[str | None] = mapped_column(String(128))
    intent: Mapped[str | None] = mapped_column(String(128))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    source: Mapped[QuestionCandidateSource] = mapped_column(
        str_enum(QuestionCandidateSource, "question_candidate_source"), nullable=False
    )
    source_ref: Mapped[str | None] = mapped_column(String(255))
    rationale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[QuestionCandidateStatus] = mapped_column(
        str_enum(QuestionCandidateStatus, "question_candidate_status"),
        nullable=False,
        default=QuestionCandidateStatus.PENDING,
        server_default=QuestionCandidateStatus.PENDING.value,
    )
    converted_question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
