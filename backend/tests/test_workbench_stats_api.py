"""Dashboard APIs preserve null metrics when no valid answer exists."""

import uuid

from app.core.security import create_access_token
from app.models.enums import RoleCode


def test_dashboard_endpoints_empty_project(client, project_factory, user_factory, member_factory):
    suffix = uuid.uuid4().hex[:6]
    project = project_factory(f"stats-ui-{suffix}")
    viewer = user_factory(f"stats-viewer-{suffix}")
    member_factory(project, viewer, RoleCode.VIEWER)
    headers = {"Authorization": f"Bearer {create_access_token(viewer.id, token_version=viewer.token_version)}"}
    base = f"/api/v1/projects/{project.id}/stats"

    overview = client.get(f"{base}/overview", headers=headers)
    assert overview.status_code == 200
    assert overview.json()["data"]["valid_answers"] == 0
    assert overview.json()["data"]["brand_mention_rate"] is None
    assert client.get(f"{base}/by-engine", headers=headers).json()["data"] == []
    assert client.get(f"{base}/by-question", headers=headers).json()["data"] == []
    health = client.get(f"{base}/engine-health", headers=headers)
    assert health.status_code == 200
    assert isinstance(health.json()["data"], list)
    for item in health.json()["data"]:
        assert item["availability"] in {
            "disabled", "no_endpoint", "no_credentials", "untested", "healthy", "degraded", "failing"
        }
    trend = client.get(f"{base}/trend", headers=headers)
    assert trend.status_code == 200
    assert len(trend.json()["data"]) == 12
    assert all(point["brand_mention_rate"] is None for point in trend.json()["data"])
    daily = client.get(f"{base}/trend/daily?days=14", headers=headers)
    assert daily.status_code == 200
    assert len(daily.json()["data"]) == 14
    assert all(point["brand_mention_rate"] is None for point in daily.json()["data"])
    assert all(point["date"] for point in daily.json()["data"])
    assert client.get(f"{base}/task-distribution", headers=headers).json()["data"] == []
