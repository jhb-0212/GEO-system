"""清理 AI 引用来源审核队列：只处理「规则也判不出」的 other，不猜具体类别。

默认把 `suggested_source_category=other` 的待判项标为 ignored，并写明
「规则无法判断，忽略提醒，不改引用」。不把未知域名强行归到 gov/media 等类别。
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("GEO_API_BASE", "http://127.0.0.1:8000")


def call(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path} -> {exc.code}: {exc.read().decode(errors='replace')}") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--username", default="geo_admin")
    parser.add_argument("--password", default="geo-admin-dev")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = call("POST", "/api/v1/auth/login", token="", body={
        "username": args.username, "password": args.password,
    })["data"]["access_token"]

    reviews: list[dict] = []
    page = 1
    while True:
        result = call(
            "GET",
            f"/api/v1/projects/{args.project_id}/citations/source-reviews?status=pending&page={page}&page_size=100",
            token,
        )
        reviews.extend(result["data"])
        if page * 100 >= result["meta"]["total"]:
            break
        page += 1

    candidates = [row for row in reviews if row.get("suggested_source_category") == "other"]
    print(f"待判 {len(reviews)}，其中规则判 other 可忽略 {len(candidates)}")
    if args.dry_run:
        return
    ignored = 0
    for row in candidates:
        call("POST", f"/api/v1/projects/{args.project_id}/citations/source-reviews/{row['review_id']}/ignore", token)
        ignored += 1
    print(json.dumps({"ignored": ignored, "remaining_pending": len(reviews) - ignored}, ensure_ascii=False))


if __name__ == "__main__":
    main()
