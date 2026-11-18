"""测量事实层：问题版本语义快照、轮次测量快照、无答案面状态

Revision ID: q9a0b1c2d3e4
Revises: p8e9f0a1b2c3

说明：
- `monitoring_rounds` 增加 analysis_config_snapshot / hash / version / captured_at：
  轮次创建时固定品牌词表、竞品与规则版本，执行只读快照。
- `question_versions` 增加 question_type / audience / intent / priority，并在
  `question_version_keywords` 保存关键词快照：历史统计不再回读当前 Question。
- `monitoring_samples` 增加 analysis_version / analysis_config_hash / analyzed_at：
  记录每条样本使用的分析规则版本，规则升级后可重算而不改原始回答。
- `monitoring_samples.status` 的 CHECK 增加 no_answer_surface：入口可用但无答案面，
  不进入有效分母，也不计入技术失败率。

本迁移自带存在性判断：若环境中已有同名快照列（并行开发的前置迁移），
只补缺失部分，不重复建列。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "q9a0b1c2d3e4"
down_revision = "p8e9f0a1b2c3"
branch_labels = None
depends_on = None

SAMPLE_STATUS_CONSTRAINT = "sample_status"
SAMPLE_STATUS_VALUES = (
    "pending",
    "running",
    "hit",
    "miss",
    "no_answer_surface",
    "failed",
    "manual_review",
)
OLD_SAMPLE_STATUS_VALUES = ("pending", "running", "hit", "miss", "failed", "manual_review")


def _status_check(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"status IN ({quoted})"


def _column_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def _table_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    # 1. 问题版本的测量语义快照
    columns = _column_names("question_versions")
    if "question_type" not in columns:
        op.add_column(
            "question_versions", sa.Column("question_type", sa.String(length=32), nullable=True)
        )
    if "audience" not in columns:
        op.add_column(
            "question_versions", sa.Column("audience", sa.String(length=128), nullable=True)
        )
    if "intent" not in columns:
        op.add_column(
            "question_versions", sa.Column("intent", sa.String(length=128), nullable=True)
        )
    if "priority" not in columns:
        op.add_column("question_versions", sa.Column("priority", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "question_version_type",
        "question_versions",
        "question_type IN ('brand', 'general')",
    )
    op.execute(
        """
        UPDATE question_versions AS v
        SET question_type = q.question_type,
            audience = q.audience,
            intent = q.intent,
            priority = q.priority
        FROM questions AS q
        WHERE v.question_id = q.id
        """
    )

    # 2. 版本级关键词快照
    if "question_version_keywords" not in _table_names():
        op.create_table(
            "question_version_keywords",
            sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("question_version_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("keyword_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["question_version_id"], ["question_versions.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["keyword_id"], ["keywords.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "question_version_id",
                "keyword_id",
                name="uq_question_version_keywords_version_keyword",
            ),
        )
        op.create_index(
            "ix_question_version_keywords_project", "question_version_keywords", ["project_id"]
        )
        op.create_index(
            "ix_question_version_keywords_version",
            "question_version_keywords",
            ["question_version_id"],
        )
        op.execute(
            """
            INSERT INTO question_version_keywords (id, project_id, question_version_id, keyword_id)
            SELECT gen_random_uuid(), v.project_id, v.id, qk.keyword_id
            FROM question_versions AS v
            JOIN question_keywords AS qk ON qk.question_id = v.question_id
            ON CONFLICT (question_version_id, keyword_id) DO NOTHING
            """
        )

    # 3. 轮次测量快照（若并行迁移已建同名列，只补缺失项）
    round_columns = _column_names("monitoring_rounds")
    if "analysis_config_snapshot" not in round_columns:
        op.add_column(
            "monitoring_rounds",
            sa.Column(
                "analysis_config_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )
    if "analysis_config_hash" not in round_columns:
        op.add_column(
            "monitoring_rounds",
            sa.Column("analysis_config_hash", sa.String(length=64), nullable=True),
        )
    if "analysis_config_version" not in round_columns:
        op.add_column(
            "monitoring_rounds",
            sa.Column("analysis_config_version", sa.String(length=32), nullable=True),
        )
    if "analysis_config_captured_at" not in round_columns:
        op.add_column(
            "monitoring_rounds",
            sa.Column("analysis_config_captured_at", sa.DateTime(timezone=True), nullable=True),
        )

    # 4. 样本分析版本戳
    sample_columns = _column_names("monitoring_samples")
    if "analysis_version" not in sample_columns:
        op.add_column(
            "monitoring_samples",
            sa.Column("analysis_version", sa.String(length=32), nullable=True),
        )
    if "analysis_config_hash" not in sample_columns:
        op.add_column(
            "monitoring_samples",
            sa.Column("analysis_config_hash", sa.String(length=64), nullable=True),
        )
    if "analyzed_at" not in sample_columns:
        op.add_column(
            "monitoring_samples",
            sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        )

    # 5. 样本状态 CHECK 扩值（VARCHAR + CHECK，不涉及类型重建）
    op.drop_constraint(SAMPLE_STATUS_CONSTRAINT, "monitoring_samples", type_="check")
    op.create_check_constraint(
        SAMPLE_STATUS_CONSTRAINT,
        "monitoring_samples",
        _status_check(SAMPLE_STATUS_VALUES),
    )


def downgrade() -> None:
    op.drop_constraint(SAMPLE_STATUS_CONSTRAINT, "monitoring_samples", type_="check")
    op.create_check_constraint(
        SAMPLE_STATUS_CONSTRAINT,
        "monitoring_samples",
        _status_check(OLD_SAMPLE_STATUS_VALUES),
    )

    sample_columns = _column_names("monitoring_samples")
    if "analyzed_at" in sample_columns:
        op.drop_column("monitoring_samples", "analyzed_at")
    if "analysis_config_hash" in sample_columns:
        op.drop_column("monitoring_samples", "analysis_config_hash")
    if "analysis_version" in sample_columns:
        op.drop_column("monitoring_samples", "analysis_version")

    # 轮次快照列可能来自并行迁移，本迁移只回滚自己保证存在的 version 列
    round_columns = _column_names("monitoring_rounds")
    if "analysis_config_version" in round_columns:
        op.drop_column("monitoring_rounds", "analysis_config_version")

    if "question_version_keywords" in _table_names():
        op.drop_index(
            "ix_question_version_keywords_version", table_name="question_version_keywords"
        )
        op.drop_index(
            "ix_question_version_keywords_project", table_name="question_version_keywords"
        )
        op.drop_table("question_version_keywords")

    op.drop_constraint("question_version_type", "question_versions", type_="check")
    op.drop_column("question_versions", "priority")
    op.drop_column("question_versions", "intent")
    op.drop_column("question_versions", "audience")
    op.drop_column("question_versions", "question_type")
