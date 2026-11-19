"""P16：原型/模拟状态与历史本地数据清点。"""

import uuid
from datetime import datetime, timezone

from app.core.security import create_access_token
from app.models import ImportBatch
from app.models.enums import ImportBatchStatus


def _headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, token_version=user.token_version)}"}


def _batch(project_id, *, status: ImportBatchStatus, delta: dict[str, int], source_rows: int) -> ImportBatch:
    return ImportBatch(
        project_id=project_id,
        source_system="legacy_local",
        mapping_version="v1",
        status=status,
        counts={"delta": delta, "source_rows": source_rows},
        started_at=datetime(2026, 11, 11, 7, 34, tzinfo=timezone.utc),
        finished_at=datetime(2026, 11, 11, 7, 35, tzinfo=timezone.utc),
    )


def test_data_provenance_classifies_projects_users_and_legacy_batches(
    client, db, user_factory, project_factory
):
    admin = user_factory(f"admin-{uuid.uuid4().hex[:6]}", is_system_admin=True)
    baseline = client.get("/api/v1/system/data-provenance", headers=_headers(admin)).json()["data"]["summary"]

    normal = project_factory(f"gz-base-{uuid.uuid4().hex[:6]}", "广州基地")
    prototype = project_factory(f"demo-{uuid.uuid4().hex[:6]}", "演示项目")

    seed_user = user_factory(f"seed-{uuid.uuid4().hex[:6]}")
    seed_user.display_name = "运营编辑（seed）"
    demo_user = user_factory(f"demo-{uuid.uuid4().hex[:6]}")
    demo_user.display_name = "演示账号"
    probe_user = user_factory(f"probe-{uuid.uuid4().hex[:6]}")

    completed = _batch(
        normal.id,
        status=ImportBatchStatus.COMPLETED,
        delta={"questions": 3, "channels": 2, "leads": 0},
        source_rows=219,
    )
    rolled_back = _batch(
        normal.id,
        status=ImportBatchStatus.ROLLED_BACK,
        delta={"questions": 5, "channels": 4, "leads": 9},
        source_rows=219,
    )
    db.add_all([completed, rolled_back])
    db.flush()

    response = client.get("/api/v1/system/data-provenance", headers=_headers(admin))
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    project_by_code = {row["code"]: row for row in data["projects"]}
    assert project_by_code[normal.code]["classification"] == "production"
    assert project_by_code[prototype.code]["classification"] == "test_or_prototype"
    assert set(project_by_code[prototype.code]["markers"]) == {"demo", "演示"}

    user_by_name = {row["username"]: row for row in data["users"]}
    assert user_by_name[seed_user.username]["classification"] == "seed"
    assert user_by_name[demo_user.username]["classification"] == "demo"
    assert user_by_name[probe_user.username]["classification"] == "probe"

    assert data["summary"]["projects_total"] == baseline["projects_total"] + 2
    assert data["summary"]["prototype_projects"] == baseline["prototype_projects"] + 1
    assert data["summary"]["seed_accounts"] == baseline["seed_accounts"] + 1
    assert data["summary"]["probe_accounts"] == baseline["probe_accounts"] + 1
    assert data["summary"]["demo_accounts"] == baseline["demo_accounts"] + 1
    assert data["summary"]["legacy_batches_total"] == baseline["legacy_batches_total"] + 2
    assert data["summary"]["legacy_batches_retained"] == baseline["legacy_batches_retained"] + 1
    expected_retained = dict(baseline["retained_legacy_rows"])
    for table, value in {"questions": 3, "channels": 2}.items():
        expected_retained[table] = expected_retained.get(table, 0) + value
    assert data["summary"]["retained_legacy_rows"] == expected_retained

    by_status = {row["status"]: row for row in data["legacy_imports"]}
    assert by_status["completed"]["retained"] is True
    assert by_status["rolled_back"]["retained"] is False
    assert by_status["rolled_back"]["delta"] == {"questions": 5, "channels": 4, "leads": 9}


def test_data_provenance_requires_system_admin(client, db, user_factory):
    normal = user_factory(f"viewer-{uuid.uuid4().hex[:6]}")
    response = client.get("/api/v1/system/data-provenance", headers=_headers(normal))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "system_admin_only"
