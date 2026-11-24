"""演示项目渠道状态流转：一条走完发布回执，一条标记为观测。

边界：
- `wechat-mp` 走真实接口链路：渠道准入 → 发布账号 → 内容版本审批 → 发布任务 →
  成功尝试 → 回填回执；回执 payload 明确写 `synthetic=true`，不是平台真实回执。
- `zhihu` 只做“已观测”状态标记并写审计，不伪造引用、样本或平台回执。
- 仅允许 `onbdem` 开头的演练项目。
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.models import AuditLog, Channel, Project  # noqa: E402
from app.models.enums import ChannelStatus  # noqa: E402

BASE = "http://127.0.0.1:8000/api/v1"


def _login(username: str, password: str) -> tuple[str, dict]:
    response = httpx.post(
        f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=20
    )
    response.raise_for_status()
    token = response.json()["data"]["access_token"]
    me = httpx.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=20)
    me.raise_for_status()
    return token, me.json()["data"]


def _call(method: str, path: str, token: str, **kwargs):
    response = httpx.request(
        method,
        f"{BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
        **kwargs,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:500]}")
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-code", default="onbdem950e9b")
    args = parser.parse_args()

    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None or not project.code.startswith("onbdem"):
            print("只允许 onbdem 开头的演练项目", file=sys.stderr)
            return 2
        project_id = str(project.id)

    admin_token, admin = _login("geo_admin", "geo-admin-dev")
    editor_token, editor = _login("geo_editor", "geo-user-dev")
    reviewer_token, reviewer = _login("geo_reviewer", "geo-user-dev")

    # 审核人加入项目；角色只授予 reviewer。
    members = _call("GET", f"/projects/{project_id}/members?page_size=100", admin_token)["data"]
    if not any(row["user_id"] == reviewer["id"] for row in members):
        _call(
            "POST",
            f"/projects/{project_id}/members",
            admin_token,
            json={"user_id": reviewer["id"], "role_code": "reviewer"},
        )
        print("added reviewer")

    channels = _call("GET", f"/projects/{project_id}/channels?page_size=100", admin_token)["data"]
    by_code = {row["code"]: row for row in channels}
    publish_channel = by_code.get("wechat-mp")
    observed_channel = by_code.get("zhihu")
    if not publish_channel or not observed_channel:
        raise RuntimeError("演示项目缺少 wechat-mp / zhihu 渠道")

    for code in ("wechat-mp", "zhihu"):
        row = by_code[code]
        if row["approval_status"] != "approved":
            _call(
                "POST",
                f"/projects/{project_id}/channels/{row['id']}/review",
                admin_token,
                json={"decision": "approved", "comment": "合成演练：仅用于渠道状态流转验证"},
            )
            print("approved", code)

    # 发布账号
    accounts = _call("GET", f"/projects/{project_id}/publish/accounts?page_size=100", editor_token)["data"]
    account = next((row for row in accounts if row["channel_id"] == publish_channel["id"]), None)
    if account is None:
        account = _call(
            "POST",
            f"/projects/{project_id}/publish/accounts",
            editor_token,
            json={
                "channel_id": publish_channel["id"],
                "account_name": "演练发布账号（合成）",
                "credential_ref": "DEMO_PUBLISH_API_KEY",
                "notes": "合成演练账号，不连接真实平台；credential_ref 仅为受控变量名占位。",
            },
        )["data"]

    suffix = uuid.uuid4().hex[:6]
    parent = _call(
        "POST", f"/projects/{project_id}/contents", editor_token,
        json={"title": f"合成演练母稿-{suffix}", "kind": "master"},
    )["data"]
    item = _call(
        "POST", f"/projects/{project_id}/contents", editor_token,
        json={
            "title": f"合成演练渠道稿-{suffix}",
            "kind": "channel",
            "parent_id": parent["item_id"],
            "channel_id": publish_channel["id"],
        },
    )["data"]
    version = _call(
        "POST", f"/projects/{project_id}/contents/{item['item_id']}/versions", editor_token,
        json={"body": "这是一篇标注为合成演练的渠道稿正文，不对外发布。", "change_note": "合成演练初稿"},
    )["data"]
    _call("POST", f"/projects/{project_id}/content-versions/{version['version_id']}/submit", editor_token)
    _call(
        "POST", f"/projects/{project_id}/content-versions/{version['version_id']}/review", reviewer_token,
        json={"decision": "approved", "comment": "合成演练审阅通过，不对外发布"},
    )
    print("content approved")

    task = _call(
        "POST", f"/projects/{project_id}/publish/tasks", editor_token,
        json={
            "version_id": version["version_id"],
            "channel_id": publish_channel["id"],
            "account_id": account["id"],
            "task_key": f"synthetic-demo-{suffix}",
        },
    )["data"]
    attempt = _call(
        "POST", f"/projects/{project_id}/publish/tasks/{task['task_id']}/attempts", editor_token,
        json={"result": "success", "mode": "manual"},
    )["data"]
    published_url = f"https://example.com/synthetic-demo/{suffix}"
    receipt = _call(
        "POST", f"/projects/{project_id}/publish/tasks/{task['task_id']}/receipts", editor_token,
        json={
            "published_url": published_url,
            "attempt_id": attempt["attempt_id"],
            "receipt_payload": {
                "synthetic": True,
                "label": "合成演练回执，非平台真实回执",
                "operator": "run_demo_channel_flow.py",
                "task_key": task.get("task_key"),
            },
        },
    )["data"]
    print("receipt", json.dumps(receipt, ensure_ascii=False))

    # 已观测只做状态标记与审计，不伪造引用或样本。
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        channel = db.get(Channel, uuid.UUID(observed_channel["id"]))
        if channel is not None and channel.status in {ChannelStatus.CANDIDATE, ChannelStatus.REVIEW_PENDING}:
            before = channel.status.value
            channel.status = ChannelStatus.OBSERVED
            db.add(
                AuditLog(
                    project_id=channel.project_id,
                    actor_id=uuid.UUID(editor["id"]),
                    action="demo.channel_synthetic_observed",
                    target_type="channel",
                    target_id=channel.id,
                    payload={
                        "before": before,
                        "after": "observed",
                        "synthetic": True,
                        "label": "合成演练状态，不来自真实引用观测",
                    },
                )
            )
            db.commit()
            print("observed", observed_channel["code"])
        else:
            print("observed skipped", channel.status.value if channel else "missing")

    with SessionLocal() as db:
        for row in db.scalars(
            select(Channel).where(Channel.project_id == uuid.UUID(project_id)).order_by(Channel.code)
        ).all():
            print(row.code, row.status.value, row.approval_status.value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
