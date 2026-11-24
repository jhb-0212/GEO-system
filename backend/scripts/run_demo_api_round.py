"""用假引擎跑一轮 API 入口任务，验证「生成 → 执行 → 落样本 → 冻结」。

只允许演练项目；脚本进程内强制 `MONITORING_FAKE_ENGINE_ENABLED=1`，
不会改后端常驻配置，也不会发起任何外部请求。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MONITORING_FAKE_ENGINE_ENABLED"] = "1"

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import MonitoringTask  # noqa: E402
from app.services.monitoring_collection import execute_task  # noqa: E402

BASE = os.environ.get("GEO_API_BASE", "http://127.0.0.1:8000")
PROJECT = os.environ.get("GEO_TEST_PROJECT_ID", "cefcae3f-d9f5-4f4f-a5fe-6cc548aa3119")


def call(method: str, path: str, token: str | None = None, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path} -> {exc.code}: {exc.read().decode(errors='replace')}") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="geo_editor")
    parser.add_argument("--password", default="geo-user-dev")
    args = parser.parse_args()
    token = call("POST", "/api/v1/auth/login", body={"username": args.username, "password": args.password})["data"]["access_token"]

    rounds = call("GET", f"/api/v1/projects/{PROJECT}/monitoring/rounds?page_size=100", token)["data"]
    target = next((row for row in rounds if row["name"] == "API 假引擎验证"), None)
    if target is None:
        target = call("POST", f"/api/v1/projects/{PROJECT}/monitoring/rounds", token, {
            "name": "API 假引擎验证",
            "is_baseline": False,
        })["data"]
    if target["status"] in ("completed", "closed"):
        print("该轮已完成，跳过")
        return
    call("POST", f"/api/v1/projects/{PROJECT}/monitoring/rounds/{target['id']}/tasks/batch", token, {
        "entry_types": ["api"],
        "samples_per_cell": 1,
    })

    with SessionLocal() as db:
        tasks = db.scalars(
            select(MonitoringTask).where(
                MonitoringTask.project_id == uuid.UUID(PROJECT),
                MonitoringTask.round_id == uuid.UUID(target["id"]),
            )
        ).all()
        pending = [task for task in tasks if task.status.value in ("pending", "failed")]
        print(f"API 任务 {len(tasks)} 条，待执行 {len(pending)} 条")
        for task in pending:
            result = execute_task(
                db,
                project_id=task.project_id,
                task_id=task.id,
                retry_on_failure=False,
            )
            if result.get("status") not in ("hit", "miss", "done"):
                print("跳过/失败：", result)
        db.commit()

    remaining = call("GET", f"/api/v1/projects/{PROJECT}/monitoring/tasks?round_id={target['id']}&page_size=100", token)["data"]
    if any(row["status"] != "done" for row in remaining):
        raise SystemExit("仍有未完成任务，未冻结快照")
    done = call("POST", f"/api/v1/projects/{PROJECT}/monitoring/rounds/{target['id']}/complete", token)["data"]
    print("冻结快照：" + json.dumps({"snapshot_id": done["snapshot_id"], "task_counts": done["task_counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
