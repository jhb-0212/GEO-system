"""C2 夹具工具的安全闸门：库身份 fail-closed、manifest 精确清理。

这些是纯单元测试，不碰数据库；对应审查提出的 P1
“验收工具不得误对生产库执行、不得按前缀扩大清理范围”。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_DIR / "scripts" / "c2_live_fixture.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("c2_live_fixture_guard", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass/注解解析需要模块已注册
    spec.loader.exec_module(module)
    return module


fixture = _load_module()


def test_database_name_uses_url_parser_not_string_split() -> None:
    url = "postgresql+psycopg://geo:geo_dev@localhost:5433/geo_dev_migrated?sslmode=disable"
    assert fixture.database_name(url) == "geo_dev_migrated"
    # 密码里带斜杠时，按字符串切分会切出错误段
    assert fixture.database_name("postgresql+psycopg://geo:p/a%2Fss@db:5432/geo_dev_migrated") == "geo_dev_migrated"


def test_unlisted_database_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(fixture.ALLOW_ENV, raising=False)
    with pytest.raises(SystemExit):
        fixture.assert_database_allowed("geo")
    with pytest.raises(SystemExit):
        fixture.assert_database_allowed("prod_main")


def test_allowlist_can_be_extended_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(fixture.ALLOW_ENV, "geo,geo_c2_accept")
    fixture.assert_database_allowed("geo_c2_accept")
    assert "geo_dev_migrated" in fixture.allowed_databases()


def test_manifest_file_is_required(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        fixture._load_manifest(tmp_path / "missing.json")


def test_manifest_without_required_fields_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"fixture_run_id": "abc", "projects": []}), encoding="utf-8")
    with pytest.raises(SystemExit):
        fixture._load_manifest(path)


def test_cleanup_refuses_manifest_from_other_database() -> None:
    manifest = {
        "fixture_run_id": "run1",
        "database": "geo_dev_migrated",
        "projects": [{"project_id": "x", "user_id": "y", "project_code": "c2live-run1-sh-x"}],
    }
    with pytest.raises(SystemExit):
        fixture.cleanup(None, manifest, "geo")


def test_cleanup_refuses_project_outside_the_run() -> None:
    manifest = {
        "fixture_run_id": "run1",
        "database": "geo_dev_migrated",
        "projects": [{"project_id": "x", "user_id": "y", "project_code": "c2live-run2-sh-x"}],
    }
    with pytest.raises(SystemExit):
        fixture.cleanup(None, manifest, "geo_dev_migrated")


def test_cleanup_refuses_non_uuid_ids() -> None:
    manifest = {
        "fixture_run_id": "run1",
        "database": "geo_dev_migrated",
        "projects": [{"project_id": "not-a-uuid", "user_id": "y", "project_code": "c2live-run1-sh-x"}],
    }
    with pytest.raises(SystemExit):
        fixture.cleanup(None, manifest, "geo_dev_migrated")
