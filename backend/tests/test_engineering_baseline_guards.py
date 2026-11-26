import importlib.util
import sys
from pathlib import Path

from app.core.permissions import PERMISSION_CATALOG


def _load_script(name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"baseline_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # 必须先登记到 sys.modules：脚本用了 `from __future__ import annotations` + dataclass，
    # dataclass 解析字符串注解时要按模块名回查 sys.modules，未登记会直接崩在 exec_module。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_doc_baseline_flags_current_manual_number(tmp_path, monkeypatch):
    module = _load_script("check_doc_baseline")
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(module, "CURRENT_DOCS", ["README.md"])
    doc = tmp_path / "README.md"
    doc.write_text("# x\n当前 786 passed\n", encoding="utf-8")
    errors = module.scan()
    assert errors and "当前" in errors[0]


def test_doc_baseline_allows_explicit_history_snapshot(tmp_path, monkeypatch):
    module = _load_script("check_doc_baseline")
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(module, "CURRENT_DOCS", ["README.md"])
    doc = tmp_path / "README.md"
    doc.write_text("# x\n历史快照：786 passed；当前值以 CI 为准\n", encoding="utf-8")
    assert module.scan() == []


def test_schema_ddl_normalization_ignores_header_and_restrict_tokens():
    module = _load_script("check_schema_ddl")
    left = (
        "\\restrict abc\n"
        "SET transaction_timeout = 0;\n"
        "SELECT pg_catalog.set_config('search_path', '', false);\n"
        "-- header\n"
        "CREATE TABLE public.x (id int);\n"
    )
    right = "CREATE TABLE public.x (id int);\n"
    assert module.normalize_dump(left) == module.normalize_dump(right)


def test_permission_doc_rejects_wrong_semantic_code(tmp_path):
    module = _load_script("check_permission_drift")
    doc = tmp_path / "权限矩阵.md"
    doc.write_text("| 项目资料确认/优先级 | `project.member.manage` |\n", encoding="utf-8")
    catalog = {code for code, *_ in PERMISSION_CATALOG}
    prefixes = {code.split(".", 1)[0] for code in catalog}
    errors = module.check_doc(doc, catalog, prefixes)
    assert any("project.confirm" in error for error in errors)


def test_permission_doc_accepts_correct_semantic_code(tmp_path):
    module = _load_script("check_permission_drift")
    doc = tmp_path / "权限矩阵.md"
    doc.write_text("| 项目资料确认/优先级 | `project.confirm` |\n", encoding="utf-8")
    catalog = {code for code, *_ in PERMISSION_CATALOG}
    prefixes = {code.split(".", 1)[0] for code in catalog}
    assert module.check_doc(doc, catalog, prefixes) == []


# --- 结构语义对账（check_schema_ddl） ---
# R-01 已确认两条合法建表路径会产生不同 attnum：模型元数据建表把新列放在模型定义位置，
# 历史迁移 ADD COLUMN 把新列追加在末尾。结构对账必须按列名比较，而不是按文本行比较。


def _ddl_compare(left: str, right: str, *, strict: bool = False):
    module = _load_script("check_schema_ddl")
    expected = module.build_model(left)
    actual = module.build_model(right)
    return module.compare_models(expected, actual, strict_column_order=strict)


def test_schema_ddl_ignores_column_physical_order():
    module_ddl = (
        "CREATE TABLE public.knowledge_candidate_facts (\n"
        "    claim_text text NOT NULL,\n"
        "    reviewed_at timestamp with time zone,\n"
        "    id uuid NOT NULL,\n"
        "    created_at timestamp with time zone DEFAULT now() NOT NULL,\n"
        "    entered_todo_at timestamp with time zone\n"
        ");\n"
    )
    # 迁移路径：entered_todo_at 由 ADD COLUMN 追加，物理位置在 reviewed_at 之后、id 之前
    migrated_ddl = (
        "CREATE TABLE public.knowledge_candidate_facts (\n"
        "    claim_text text NOT NULL,\n"
        "    reviewed_at timestamp with time zone,\n"
        "    entered_todo_at timestamp with time zone,\n"
        "    id uuid NOT NULL,\n"
        "    created_at timestamp with time zone DEFAULT now() NOT NULL\n"
        ");\n"
    )
    diffs, order_only = _ddl_compare(module_ddl, migrated_ddl)
    assert diffs == []
    assert "public.knowledge_candidate_facts" in order_only


def test_schema_ddl_strict_order_mode_reports_order_difference():
    model_ddl = "CREATE TABLE public.t (a int, b int);\n"
    migrated_ddl = "CREATE TABLE public.t (b int, a int);\n"
    diffs, order_only = _ddl_compare(model_ddl, migrated_ddl, strict=True)
    assert order_only == {}
    assert diffs and "列物理顺序不同" in diffs[0]


def test_schema_ddl_flags_column_type_change():
    left = "CREATE TABLE public.t (a integer NOT NULL);\n"
    right = "CREATE TABLE public.t (a bigint NOT NULL);\n"
    diffs, _ = _ddl_compare(left, right)
    assert diffs and "t.a" in diffs[0] and "列定义不同" in diffs[0]


def test_schema_ddl_flags_missing_column():
    left = "CREATE TABLE public.t (a int, b int);\n"
    right = "CREATE TABLE public.t (a int);\n"
    diffs, _ = _ddl_compare(left, right)
    assert any("目标库缺少列 b" in diff for diff in diffs)


def test_schema_ddl_flags_extra_table():
    left = "CREATE TABLE public.t (a int);\n"
    right = "CREATE TABLE public.t (a int);\nCREATE TABLE public.t_extra (a int);\n"
    diffs, _ = _ddl_compare(left, right)
    assert any("多余表：public.t_extra" in diff for diff in diffs)


def test_schema_ddl_flags_check_constraint_change():
    left = (
        "CREATE TABLE public.t (\n"
        "    status character varying(32) NOT NULL,\n"
        "    CONSTRAINT ck_t_status CHECK (((status)::text = ANY ((ARRAY['suggested'::character varying])::text[])))\n"
        ");\n"
    )
    right = (
        "CREATE TABLE public.t (\n"
        "    status character varying(32) NOT NULL,\n"
        "    CONSTRAINT ck_t_status CHECK (((status)::text = ANY ((ARRAY['suggested'::character varying, 'accepted'::character varying])::text[])))\n"
        ");\n"
    )
    diffs, _ = _ddl_compare(left, right)
    assert any("约束 ck_t_status 定义不同" in diff for diff in diffs)


def test_schema_ddl_flags_missing_and_extra_index():
    left = "CREATE TABLE public.t (a int);\nCREATE UNIQUE INDEX uq_t_a ON public.t USING btree (a);\n"
    right = "CREATE TABLE public.t (a int);\n"
    diffs, _ = _ddl_compare(left, right)
    assert any("目标库缺少语句" in diff and "uq_t_a" in diff for diff in diffs)

    leftover, _ = _ddl_compare(right, left)
    assert any("目标库多出语句" in diff and "uq_t_a" in diff for diff in leftover)


def test_schema_ddl_parses_commas_inside_check_expression():
    sql = (
        "CREATE TABLE public.t (\n"
        "    a int,\n"
        "    CONSTRAINT ck_t_a CHECK ((a = ANY ((ARRAY[1, 2, 3])::integer[])))\n"
        ");\n"
    )
    module = _load_script("check_schema_ddl")
    model = module.build_model(sql)
    table = model.tables["public.t"]
    assert list(table.columns) == ["a"]
    assert list(table.constraints) == ["ck_t_a"]

