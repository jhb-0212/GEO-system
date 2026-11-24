"""结构级测试：逐表核对 project_id、外键、索引与枚举约束，防止文档与库脱节。"""

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# 系统级表白名单：不带项目归属的业务数据只允许这些（含权限矩阵这类系统级配置表）
SYSTEM_LEVEL_TABLES = {
    "users",
    "roles",
    "permissions",
    "role_permissions",
    "projects",
    "ai_engines",
    "ai_engine_entries",
    # 客户主体与行业预设是跨项目配置：不属于任何单个项目
    "organizations",
    "industry_presets",
    "organization_members",
    "organization_usage_snapshots",
}
# audit_logs 允许 project_id 为空（记录系统级操作），其余项目表必须 NOT NULL
# project_id 允许为空的例外：audit_logs 记录系统级审计；outbox_events 承载 system.* 系统级事件
PROJECT_ID_NULLABLE_ALLOWED = {"audit_logs", "outbox_events"}


def _fetch_all(engine, sql: str) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql))]


def test_every_business_table_has_project_id(engine):
    tables = {row[0] for row in _fetch_all(engine, "select tablename from pg_tables where schemaname='public'")}
    with_project = {
        row[0]
        for row in _fetch_all(
            engine,
            "select table_name from information_schema.columns "
            "where table_schema='public' and column_name='project_id'",
        )
    }
    missing = tables - with_project - SYSTEM_LEVEL_TABLES - {"alembic_version"}
    assert missing == set(), f"缺少 project_id 的业务表：{sorted(missing)}"


def test_project_id_not_null(engine):
    rows = _fetch_all(
        engine,
        "select table_name, is_nullable from information_schema.columns "
        "where table_schema='public' and column_name='project_id'",
    )
    nullable = {name for name, is_nullable in rows if is_nullable == "YES"} - PROJECT_ID_NULLABLE_ALLOWED
    assert nullable == set(), f"project_id 允许为空的表：{sorted(nullable)}"


def test_project_foreign_keys_restrict(engine):
    rows = _fetch_all(
        engine,
        """
        select c.conrelid::regclass::text as table_name, c.confdeltype
        from pg_constraint c
        join pg_class t on t.oid = c.conrelid
        join pg_namespace n on n.oid = t.relnamespace
        join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
        where n.nspname = 'public'
          and c.contype = 'f'
          and a.attname = 'project_id'
          and array_length(c.conkey, 1) = 1
        """,
    )
    assert rows, "没有任何 project_id 外键"
    # confdeltype: r=RESTRICT, c=CASCADE, n=SET NULL, d=SET DEFAULT, a=NO ACTION
    wrong = [t for t, rule in rows if rule != "r" and not t.endswith("audit_logs")]
    assert wrong == [], f"project_id 外键不是 RESTRICT 的表：{sorted(wrong)}"


def test_enum_check_constraints_present(engine):
    count = _fetch_all(
        engine,
        """
        select count(*) from pg_constraint c
        join pg_class t on t.oid = c.conrelid
        join pg_namespace n on n.oid = t.relnamespace
        where n.nspname='public' and c.contype='c'
        """,
    )[0][0]
    assert count >= 30, f"枚举 CHECK 约束只有 {count} 条，疑似未建"


def test_enum_value_rejected_by_database(engine):
    """角色 code 只允许 6 个枚举值，写非法值必须被数据库拒绝。"""
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "insert into roles (id, code, name, created_at, updated_at) "
                    "values (gen_random_uuid(), 'bogus_role', '非法角色', now(), now())"
                )
            )
            conn.rollback()
            raise AssertionError("数据库接受了非法枚举值，CHECK 约束未生效")
        except IntegrityError:
            conn.rollback()


def test_required_indexes_exist(engine):
    indexes = {row[0] for row in _fetch_all(engine, "select indexname from pg_indexes where schemaname='public'")}
    required = {
        "ix_monitoring_tasks_project_round_status",
        "ix_monitoring_samples_task_status",
        "ix_monitoring_citations_project_domain_review",
        "ix_audit_logs_project_created",
        "ix_leads_project_created",
        "uq_monitoring_tasks_round_question_entry_sampling",
        "uq_publish_tasks_idempotency",
        "uq_publish_tasks_idempotency_key",
        "uq_content_versions_item_version",
        "uq_questions_project_code",
    }
    assert required - indexes == set(), f"缺少索引：{sorted(required - indexes)}"


def test_question_profile_columns_exist(engine):
    """第 3 节 P0：题库必须能保存人群、意图、优先级，缺一列就无法落库。"""
    columns = {
        row[0]
        for row in _fetch_all(
            engine,
            "select column_name from information_schema.columns "
            "where table_schema='public' and table_name='questions'",
        )
    }
    assert {"audience", "intent", "priority"} <= columns, (
        f"questions 缺少画像字段：{sorted({'audience', 'intent', 'priority'} - columns)}"
    )


def test_lead_attribution_columns_exist(engine):
    """转化闭环：线索必须能归因到题目、渠道、引擎和落地页。"""
    columns = {
        row[0]
        for row in _fetch_all(
            engine,
            "select column_name from information_schema.columns "
            "where table_schema='public' and table_name='leads'",
        )
    }
    required = {
        "source_question_id",
        "source_channel_id",
        "source_engine_id",
        "landing_url",
        "utm_campaign",
    }
    assert required <= columns, f"leads 缺少归因字段：{sorted(required - columns)}"


def test_import_batch_traceability(engine):
    """历史数据导入必须有批次表，且目标表能标记来源批次。"""
    tables = {row[0] for row in _fetch_all(engine, "select tablename from pg_tables where schemaname='public'")}
    assert "import_batches" in tables
    for table in ("questions", "question_versions", "content_items", "content_versions", "channels", "leads"):
        columns = {
            row[0]
            for row in _fetch_all(
                engine,
                f"select column_name from information_schema.columns "
                f"where table_schema='public' and table_name='{table}'",
            )
        }
        assert "import_batch_id" in columns, f"{table} 缺少 import_batch_id，旧数据无法追溯"


def test_system_admin_flag_exists(engine):
    columns = {
        row[0]
        for row in _fetch_all(
            engine,
            "select column_name from information_schema.columns "
            "where table_schema='public' and table_name='users'",
        )
    }
    assert "is_system_admin" in columns


def test_baseline_round_unique_index(engine):
    """一个项目只允许一条基线轮次，库层用部分唯一索引兜底。"""
    rows = _fetch_all(
        engine,
        "select indexdef from pg_indexes "
        "where schemaname='public' and tablename='monitoring_rounds' "
        "and indexname='uq_monitoring_rounds_project_baseline'",
    )
    assert rows, "缺少基线轮次部分唯一索引"
    definition = rows[0][0]
    assert "UNIQUE INDEX" in definition
    assert "is_baseline IS TRUE" in definition


def test_answer_and_citation_dimensions_exist(engine):
    """头部 GEO 口径：答案要能按引擎型号/国家/语言算，引用要能区分 used/cited。"""
    sample_columns = {
        row[0]
        for row in _fetch_all(
            engine,
            "select column_name from information_schema.columns "
            "where table_schema='public' and table_name='monitoring_samples'",
        )
    }
    required_sample = {"engine_model", "model_version", "country_code", "language"}
    assert required_sample <= sample_columns, (
        f"monitoring_samples 缺少答案维度：{sorted(required_sample - sample_columns)}"
    )

    citation_columns = {
        row[0]
        for row in _fetch_all(
            engine,
            "select column_name from information_schema.columns "
            "where table_schema='public' and table_name='monitoring_citations'",
        )
    }
    required_citation = {"citation_usage", "competitor_id"}
    assert required_citation <= citation_columns, (
        f"monitoring_citations 缺少引用维度：{sorted(required_citation - citation_columns)}"
    )

    usage_constraint = _fetch_all(
        engine,
        "select pg_get_constraintdef(c.oid) from pg_constraint c "
        "join pg_class t on t.oid = c.conrelid "
        "join pg_namespace n on n.oid = t.relnamespace "
        "where n.nspname='public' and t.relname='monitoring_citations' "
        "and c.conname='ck_monitoring_citations_citation_usage'",
    )
    assert usage_constraint, "缺少 citation_usage 的枚举 CHECK 约束"
    definition = usage_constraint[0][0]
    assert "used" in definition and "cited" in definition


def test_engine_entry_protocol_columns_exist(engine):
    """运营自助接入需要协议、模型名和密钥引用字段；不能只靠 access_note 自由文本。"""
    columns = {
        row[0]
        for row in _fetch_all(
            engine,
            "select column_name from information_schema.columns "
            "where table_schema='public' and table_name='ai_engine_entries'",
        )
    }
    required = {"protocol", "model_name", "credential_ref"}
    assert required <= columns, f"ai_engine_entries 缺少接入字段：{sorted(required - columns)}"

    constraint = _fetch_all(
        engine,
        "select pg_get_constraintdef(c.oid) from pg_constraint c "
        "join pg_class t on t.oid = c.conrelid "
        "join pg_namespace n on n.oid = t.relnamespace "
        "where n.nspname='public' and t.relname='ai_engine_entries' "
        "and c.conname='ck_ai_engine_entries_engine_protocol'",
    )
    assert constraint, "缺少 engine_protocol 的枚举 CHECK 约束"
    definition = constraint[0][0]
    assert "openai_compatible" in definition and "custom" in definition


def test_competitor_mention_model_exists(engine):
    """竞品要能按样本多次提及，SOV 不能只靠一个 competitor_id 字段。"""
    tables = {row[0] for row in _fetch_all(engine, "select tablename from pg_tables where schemaname='public'")}
    assert {"competitors", "monitoring_competitor_mentions"} <= tables

    competitor_columns = {
        row[0]
        for row in _fetch_all(
            engine,
            "select column_name from information_schema.columns "
            "where table_schema='public' and table_name='competitors'",
        )
    }
    assert {"project_id", "name", "domain", "is_active"} <= competitor_columns

    mention_columns = {
        row[0]
        for row in _fetch_all(
            engine,
            "select column_name from information_schema.columns "
            "where table_schema='public' and table_name='monitoring_competitor_mentions'",
        )
    }
    assert {"project_id", "sample_id", "competitor_id", "position"} <= mention_columns

    indexes = {row[0] for row in _fetch_all(engine, "select indexname from pg_indexes where schemaname='public'")}
    assert "uq_monitoring_competitor_mentions_sample_competitor" in indexes
    assert "ix_monitoring_samples_project_engine_model_sampled_at" in indexes
    assert "ix_monitoring_samples_project_country_sampled_at" in indexes
    assert "ix_monitoring_citations_project_usage_domain" in indexes

