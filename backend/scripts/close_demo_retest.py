"""用合成手测样本收口演示项目的一轮复测。

背景：一轮自动复测里，真实引擎限流/欠费会留下 failed 任务，worker 停机还会留下
running 任务。failed 允许完成轮次，running 必须先回收租约；否则轮次永远卡在 running。
这个脚本只用于 `onbdem` 演练项目，用合成回答把 failed/uncertain 任务补成 done，
再完成轮次。原始失败 attempt 仍保留，不删除、不改写。

    backend\\.venv\\Scripts\\python.exe backend\\scripts\\close_demo_retest.py ^
        --round-id 2ead6e96-a97d-4e34-b0ec-9b32ad8300b2
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.models import MonitoringRound, MonitoringTask, Project  # noqa: E402
from app.services.monitoring_collection import recover_expired_leases  # noqa: E402

BASE = "http://127.0.0.1:8000/api/v1"


def _login(username: str, password: str) -> str:
    response = httpx.post(
        f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=20
    )
    response.raise_for_status()
    return response.json()["data"]["access_token"]


def _tasks(token: str, project_id: str, round_id: str) -> list[dict]:
    response = httpx.get(
        f"{BASE}/projects/{project_id}/monitoring/tasks",
        params={"round_id": round_id, "page": 1, "page_size": 100},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload["meta"]["total"] > 100:
        raise SystemExit("任务超过 100 个，需要分页；本脚本只收口 100 以内的一轮")
    return payload["data"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-code", default="onbdem950e9b")
    parser.add_argument("--round-id", required=True)
    parser.add_argument("--operator", default="geo_editor")
    parser.add_argument("--password", default="geo-user-dev")
    args = parser.parse_args()

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None or not project.code.startswith("onbdem"):
            print("只允许 onbdem 开头的演练项目", file=sys.stderr)
            return 2
        project_id = str(project.id)
        round_obj = db.get(MonitoringRound, args.round_id)
        if round_obj is None:
            print("轮次不存在", file=sys.stderr)
            return 2
        if round_obj.status.value == "completed":
            print(f"轮次已完成，无需重复收口：{args.round_id}")
            return 0
        tasks = list(
            db.scalars(
                select(MonitoringTask).where(
                    MonitoringTask.project_id == project.id,
                    MonitoringTask.round_id == args.round_id,
                )
            ).all()
        )
        before = Counter(task.status.value for task in tasks)
        recovery = recover_expired_leases(db)

    print(f"租约回收：{recovery}")
    print(f"补录前任务状态：{dict(before)}")

    token = _login(args.operator, args.password)
    headers = {"Authorization": f"Bearer {token}"}
    rows = _tasks(token, project_id, args.round_id)
    statuses = Counter(row["status"] for row in rows)
    print(f"补录前 API 状态：{dict(statuses)}")

    supplemented = 0
    for index, row in enumerate(rows):
        if row["status"] not in ("failed", "uncertain"):
            continue
        mentioned = index % 5 != 0
        answer = (
            f"合成演练补录回答（{row['question_code']} / {row['engine_name']}）："
            "如果关注广州 AI 实训，广州示例数字实训基地提供线下 AIGC 实训与作品集辅导，"
            "具体费用和周期以官方咨询为准。"
        )
        body = {
            "raw_answer": answer,
            "answer_kind": "answer",
            "brand_mentioned": mentioned,
            "brand_identified": mentioned,
            "citation_urls": [],
            "new_conversation_confirmed": True,
            "note": "合成演练：原任务因真实引擎限流/欠费或租约过期未完成，用手测样本补齐；非真实平台回答",
        }
        response = httpx.post(
            f"{BASE}/projects/{project_id}/monitoring/tasks/{row['id']}/samples",
            headers=headers,
            json=body,
            timeout=30,
        )
        response.raise_for_status()
        supplemented += 1
        print(f"  + {row['serial_no']} {row['engine_name']} -> done (brand_mentioned={mentioned})")

    rows = _tasks(token, project_id, args.round_id)
    final = Counter(row["status"] for row in rows)
    print(f"补录 {supplemented} 条后状态：{dict(final)}")

    blocked = final.get("pending", 0) + final.get("running", 0) + final.get("uncertain", 0)
    if blocked:
        print("仍有未收敛任务，未完成轮次；请检查租约或人工补录。", file=sys.stderr)
        return 3

    response = httpx.post(
        f"{BASE}/projects/{project_id}/monitoring/rounds/{args.round_id}/complete",
        headers=headers,
        timeout=60,
    )
    response.raise_for_status()
    result = response.json()["data"]
    print("轮次完成：")
    print(f"  status={result['round']['status']}")
    print(f"  task_counts={result['task_counts']}")
    print(f"  snapshot_id={result['snapshot_id']}")
    print(f"  snapshot_hash={result['snapshot_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
