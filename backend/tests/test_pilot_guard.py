"""真实采集边界：库白名单、连接串脱敏、显式执行授权。"""

import pytest

from app.services.pilot_guard import (
    PilotGuardError,
    database_name,
    ensure_execution_authorized,
    ensure_pilot_database,
    redacted_database_label,
)


def test_only_geo_pilot_is_allowed():
    assert ensure_pilot_database("postgresql+psycopg://geo:secret@localhost:5433/geo_pilot?sslmode=disable") == "geo_pilot"
    for url in (
        "postgresql+psycopg://geo:secret@localhost:5433/geo",
        "postgresql+psycopg://geo:secret@localhost:5433/geo_pilot_smoke",
        "postgresql+psycopg://geo:secret@localhost:5433/geo_r2r3_test",
    ):
        with pytest.raises(PilotGuardError, match="不在试点白名单"):
            ensure_pilot_database(url)


def test_database_label_redacts_credentials_and_query():
    label = redacted_database_label(
        "postgresql+psycopg://geo:super-secret@db.example:5433/geo_pilot?sslmode=disable"
    )
    assert "super-secret" not in label
    assert "geo:" not in label
    assert "sslmode" not in label
    assert "库=geo_pilot" in label
    assert "主机=db.example" in label


def test_real_execution_requires_explicit_flag():
    ensure_execution_authorized(check_only=True, execute=False)
    with pytest.raises(PilotGuardError, match="--execute"):
        ensure_execution_authorized(check_only=False, execute=False)
    ensure_execution_authorized(check_only=False, execute=True)


def test_database_name_from_url():
    assert database_name("postgresql://geo:geo_dev@127.0.0.1:5433/geo_pilot") == "geo_pilot"
