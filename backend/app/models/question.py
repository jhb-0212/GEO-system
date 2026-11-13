"""题库与关键词：监测任务引用固定的问题版本，历史记录不随题目修改而变义。"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.models.enums import QuestionStatus, QuestionType


class Keyword(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """目标词：用于题目关联与品牌识别口径。"""

    __tablename__ = "keywords"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_keywords_project_name"),
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
    """问题版本：不可覆盖改写，监测任务记录里锁定具体版本。"""

    __tablename__ = "question_versions"
    __table_args__ = (
        UniqueConstraint("question_id", "version_no", name="uq_question_versions_question_version"),
        Index("ix_question_versions_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL")
    )


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
