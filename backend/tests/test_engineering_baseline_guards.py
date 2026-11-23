import importlib.util
from pathlib import Path

from app.core.permissions import PERMISSION_CATALOG


def _load_script(name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"baseline_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
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
