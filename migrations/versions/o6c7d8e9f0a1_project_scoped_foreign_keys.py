"""项目归属复合外键：跨表关联必须在同一 project_id 内

Revision ID: o6c7d8e9f0a1
Revises: n5a6b7c8d9e0

说明：
- 每张父表补 (project_id, id) 唯一键，作为复合外键被引用目标；
- 子表加 (project_id, xxx_id) 复合外键，数据库层拒绝跨项目关联；
- 全局共享资源（ai_engines / ai_engine_entries / channels）不套项目约束。
"""

from alembic import op

revision = "o6c7d8e9f0a1"
down_revision = "n5a6b7c8d9e0"
branch_labels = None
depends_on = None

UNIQUES = [
    ("uq_monitoring_rounds_project_id_id", "monitoring_rounds"),
    ("uq_question_versions_project_id_id", "question_versions"),
    ("uq_questions_project_id_id", "questions"),
    ("uq_keywords_project_id_id", "keywords"),
    ("uq_monitoring_tasks_project_id_id", "monitoring_tasks"),
    ("uq_monitoring_samples_project_id_id", "monitoring_samples"),
    ("uq_monitoring_citations_project_id_id", "monitoring_citations"),
    ("uq_content_versions_project_id_id", "content_versions"),
]

FKS = [
    (
        "fk_monitoring_tasks_project_round",
        "monitoring_tasks",
        ["project_id", "round_id"],
        "monitoring_rounds",
        ["project_id", "id"],
        "RESTRICT",
    ),
    (
        "fk_monitoring_tasks_project_question_version",
        "monitoring_tasks",
        ["project_id", "question_version_id"],
        "question_versions",
        ["project_id", "id"],
        "RESTRICT",
    ),
    (
        "fk_monitoring_samples_project_task",
        "monitoring_samples",
        ["project_id", "task_id"],
        "monitoring_tasks",
        ["project_id", "id"],
        "CASCADE",
    ),
    (
        "fk_monitoring_citations_project_sample",
        "monitoring_citations",
        ["project_id", "sample_id"],
        "monitoring_samples",
        ["project_id", "id"],
        "CASCADE",
    ),
    (
        "fk_content_version_questions_project_version",
        "content_version_questions",
        ["project_id", "version_id"],
        "content_versions",
        ["project_id", "id"],
        "CASCADE",
    ),
    (
        "fk_content_version_questions_project_question",
        "content_version_questions",
        ["project_id", "question_id"],
        "questions",
        ["project_id", "id"],
        "CASCADE",
    ),
    (
        "fk_content_version_keywords_project_version",
        "content_version_keywords",
        ["project_id", "version_id"],
        "content_versions",
        ["project_id", "id"],
        "CASCADE",
    ),
    (
        "fk_content_version_keywords_project_keyword",
        "content_version_keywords",
        ["project_id", "keyword_id"],
        "keywords",
        ["project_id", "id"],
        "CASCADE",
    ),
    (
        "fk_content_version_citations_project_version",
        "content_version_citations",
        ["project_id", "version_id"],
        "content_versions",
        ["project_id", "id"],
        "CASCADE",
    ),
    (
        "fk_content_version_citations_project_citation",
        "content_version_citations",
        ["project_id", "citation_id"],
        "monitoring_citations",
        ["project_id", "id"],
        "CASCADE",
    ),
]


def upgrade() -> None:
    for name, table in UNIQUES:
        op.create_unique_constraint(name, table, ["project_id", "id"])
    for name, table, local_cols, referent, remote_cols, ondelete in FKS:
        op.create_foreign_key(
            name,
            table,
            referent,
            local_cols,
            remote_cols,
            ondelete=ondelete,
        )


def downgrade() -> None:
    for name, table, _local_cols, _referent, _remote_cols, _ondelete in reversed(FKS):
        op.drop_constraint(name, table, type_="foreignkey")
    for name, table in reversed(UNIQUES):
        op.drop_constraint(name, table, type_="unique")
