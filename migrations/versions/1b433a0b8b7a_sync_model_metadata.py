"""sync model metadata

Revision ID: 1b433a0b8b7a
Revises: u5f6a7b8c9d0
Create Date: 2026-11-25 17:32:19.204203

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b433a0b8b7a'
down_revision: Union[str, None] = 'u5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _drop_check(table: str, *names: str) -> None:
    """Alter 成 Enum 会重建 CHECK；旧迁移已建过同名约束，先删干净。"""
    for name in names:
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"')


def upgrade() -> None:
    # 旧索引已不再由模型声明：两个查询型索引保留在数据库中由迁移维护
    op.drop_index('ix_content_plans_project_published', table_name='content_plans')
    _drop_check(
        'distribution_batches',
        'ck_distribution_batches_distribution_batch_status',
    )
    op.alter_column('distribution_batches', 'status',
               existing_type=sa.VARCHAR(length=16),
               type_=sa.Enum('blocked', 'ready', 'dispatched', name='distribution_batch_status', native_enum=False, create_constraint=True, length=32),
               existing_nullable=False,
               existing_server_default=sa.text("'blocked'::character varying"))
    _drop_check(
        'encyclopedia_entries',
        'ck_encyclopedia_entries_ck_encyclopedia_entries_status',
        'ck_encyclopedia_entries_encyclopedia_status',
    )
    op.alter_column('encyclopedia_entries', 'status',
               existing_type=sa.VARCHAR(length=16),
               type_=sa.Enum('draft', 'pending_review', 'published', 'rejected', name='encyclopedia_status', native_enum=False, create_constraint=True, length=32),
               existing_nullable=False,
               existing_server_default=sa.text("'draft'::character varying"))
    _drop_check(
        'generation_batches',
        'ck_generation_batches_ck_generation_batches_status',
        'ck_generation_batches_generation_batch_status',
    )
    op.alter_column('generation_batches', 'status',
               existing_type=sa.VARCHAR(length=16),
               type_=sa.Enum('queued', 'running', 'completed', 'failed', name='generation_batch_status', native_enum=False, create_constraint=True, length=32),
               existing_nullable=False,
               existing_server_default=sa.text("'queued'::character varying"))
    _drop_check(
        'generation_items',
        'ck_generation_items_ck_generation_items_status',
        'ck_generation_items_generation_item_status',
    )
    op.alter_column('generation_items', 'status',
               existing_type=sa.VARCHAR(length=16),
               type_=sa.Enum('pending', 'drafted', 'failed', name='generation_item_status', native_enum=False, create_constraint=True, length=32),
               existing_nullable=False,
               existing_server_default=sa.text("'pending'::character varying"))
    _drop_check(
        'generation_items',
        'ck_generation_items_ck_generation_items_mode',
        'ck_generation_items_generation_mode',
    )
    op.alter_column('generation_items', 'generation_mode',
               existing_type=sa.VARCHAR(length=16),
               type_=sa.Enum('template', 'model', name='generation_mode', native_enum=False, create_constraint=True, length=32),
               existing_nullable=False,
               existing_server_default=sa.text("'template'::character varying"))
    _drop_check(
        'health_check_items',
        'ck_health_check_items_ck_health_check_items_status',
        'ck_health_check_items_health_check_status',
    )
    op.alter_column('health_check_items', 'status',
               existing_type=sa.VARCHAR(length=16),
               type_=sa.Enum('pass', 'fail', 'unknown', name='health_check_status', native_enum=False, create_constraint=True, length=32),
               existing_nullable=False)
    # 线索去重需要 project_id + ip_hash 组合查询，索引已在旧迁移建好，保留不动
    op.add_column('monitoring_samples', sa.Column('brand_recommendation', sa.Boolean(), nullable=True))
    op.add_column('monitoring_samples', sa.Column('recommendation_reason', sa.String(length=64), nullable=True))
    op.add_column('monitoring_samples', sa.Column('entity_mention_count', sa.Integer(), nullable=True))
    op.alter_column('projects', 'organization_id',
               existing_type=sa.UUID(),
               nullable=True)
    op.drop_index('ix_publish_tasks_source_batch', table_name='publish_tasks')
    op.create_index(op.f('ix_publish_tasks_source_batch_id'), 'publish_tasks', ['source_batch_id'], unique=False)
    _drop_check(
        'sentiment_labels',
        'ck_sentiment_labels_sentiment_polarity',
    )
    op.alter_column('sentiment_labels', 'polarity',
               existing_type=sa.VARCHAR(length=16),
               type_=sa.Enum('positive', 'neutral', 'negative', name='sentiment_polarity', native_enum=False, create_constraint=True, length=32),
               existing_nullable=False)
    _drop_check(
        'site_modules',
        'ck_site_modules_ck_site_modules_type',
        'ck_site_modules_site_module_type',
    )
    op.alter_column('site_modules', 'module_type',
               existing_type=sa.VARCHAR(length=16),
               type_=sa.Enum('home', 'services', 'news', 'download', 'poster', 'card', name='site_module_type', native_enum=False, create_constraint=True, length=32),
               existing_nullable=False)


def downgrade() -> None:
    _drop_check(
        'site_modules',
        'ck_site_modules_site_module_type',
    )
    op.alter_column('site_modules', 'module_type',
               existing_type=sa.Enum('home', 'services', 'news', 'download', 'poster', 'card', name='site_module_type', native_enum=False, create_constraint=True, length=32),
               type_=sa.VARCHAR(length=16),
               existing_nullable=False)
    _drop_check(
        'sentiment_labels',
        'ck_sentiment_labels_sentiment_polarity',
    )
    op.alter_column('sentiment_labels', 'polarity',
               existing_type=sa.Enum('positive', 'neutral', 'negative', name='sentiment_polarity', native_enum=False, create_constraint=True, length=32),
               type_=sa.VARCHAR(length=16),
               existing_nullable=False)
    op.drop_index(op.f('ix_publish_tasks_source_batch_id'), table_name='publish_tasks')
    op.create_index('ix_publish_tasks_source_batch', 'publish_tasks', ['source_batch_id'], unique=False)
    op.alter_column('projects', 'organization_id',
               existing_type=sa.UUID(),
               nullable=False)
    op.drop_column('monitoring_samples', 'entity_mention_count')
    op.drop_column('monitoring_samples', 'recommendation_reason')
    op.drop_column('monitoring_samples', 'brand_recommendation')
    _drop_check(
        'health_check_items',
        'ck_health_check_items_health_check_status',
    )
    op.alter_column('health_check_items', 'status',
               existing_type=sa.Enum('pass', 'fail', 'unknown', name='health_check_status', native_enum=False, create_constraint=True, length=32),
               type_=sa.VARCHAR(length=16),
               existing_nullable=False)
    _drop_check(
        'generation_items',
        'ck_generation_items_generation_mode',
    )
    op.alter_column('generation_items', 'generation_mode',
               existing_type=sa.Enum('template', 'model', name='generation_mode', native_enum=False, create_constraint=True, length=32),
               type_=sa.VARCHAR(length=16),
               existing_nullable=False,
               existing_server_default=sa.text("'template'::character varying"))
    _drop_check(
        'generation_items',
        'ck_generation_items_generation_item_status',
    )
    op.alter_column('generation_items', 'status',
               existing_type=sa.Enum('pending', 'drafted', 'failed', name='generation_item_status', native_enum=False, create_constraint=True, length=32),
               type_=sa.VARCHAR(length=16),
               existing_nullable=False,
               existing_server_default=sa.text("'pending'::character varying"))
    _drop_check(
        'generation_batches',
        'ck_generation_batches_generation_batch_status',
    )
    op.alter_column('generation_batches', 'status',
               existing_type=sa.Enum('queued', 'running', 'completed', 'failed', name='generation_batch_status', native_enum=False, create_constraint=True, length=32),
               type_=sa.VARCHAR(length=16),
               existing_nullable=False,
               existing_server_default=sa.text("'queued'::character varying"))
    _drop_check(
        'encyclopedia_entries',
        'ck_encyclopedia_entries_encyclopedia_status',
    )
    op.alter_column('encyclopedia_entries', 'status',
               existing_type=sa.Enum('draft', 'pending_review', 'published', 'rejected', name='encyclopedia_status', native_enum=False, create_constraint=True, length=32),
               type_=sa.VARCHAR(length=16),
               existing_nullable=False,
               existing_server_default=sa.text("'draft'::character varying"))
    _drop_check(
        'distribution_batches',
        'ck_distribution_batches_distribution_batch_status',
    )
    op.alter_column('distribution_batches', 'status',
               existing_type=sa.Enum('blocked', 'ready', 'dispatched', name='distribution_batch_status', native_enum=False, create_constraint=True, length=32),
               type_=sa.VARCHAR(length=16),
               existing_nullable=False,
               existing_server_default=sa.text("'blocked'::character varying"))
    op.create_index('ix_content_plans_project_published', 'content_plans', ['project_id', 'is_published'], unique=False)
