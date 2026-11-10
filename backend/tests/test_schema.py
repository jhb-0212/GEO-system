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
}
# audit_logs 允许 project_id 为空（记录系统级操作），其余项目表必须 NOT NULL
PROJECT_ID_NULLABLE_ALLOWED = {"audit_logs"}


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
    """角色 code 只允许 5 个枚举值，写非法值必须被数据库拒绝。"""
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
