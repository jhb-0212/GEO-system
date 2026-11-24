"""在演练项目上跑双人情感盲评 + 引用人工确认。

步骤：
1. 管理员把 auto 引用逐条确认（带合成演练备注），引用率因此有分子；
2. 把第二标注账号加成本项目 editor；
3. 两个账号对同一批已确认引用各标一次，同档位形成共识；
4. 输出标注覆盖、三档计数、抽样共识与阈值是否达到。

只对演练项目运行；标注备注一律带「合成演练」，不冒充真实评审。
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("GEO_API_BASE", "http://127.0.0.1:8000")
PROJECT = os.environ.get("GEO_TEST_PROJECT_ID", "cefcae3f-d9f5-4f4f-a5fe-6cc548aa3119")


def call(method: str, path: str, token: str | None = None, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path} -> {exc.code}: {exc.read().decode(errors='replace')}") from exc


def login(username: str, password: str) -> str:
    return call("POST", "/api/v1/auth/login", body={"username": username, "password": password})["data"]["access_token"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin", default="geo_admin")
    parser.add_argument("--admin-password", default="geo-admin-dev")
    parser.add_argument("--reviewer-a", default="geo_editor")
    parser.add_argument("--reviewer-b", default="geo_lead_ops")
    parser.add_argument("--password", default="geo-user-dev")
    args = parser.parse_args()

    admin = login(args.admin, args.admin_password)
    citations = call("GET", f"/api/v1/projects/{PROJECT}/citations?page_size=100", admin)["data"]
    confirmed = [row for row in citations if row["review_status"] == "manual_confirmed"]
    for row in citations:
        if row["review_status"] != "manual_confirmed":
            call("PATCH", f"/api/v1/projects/{PROJECT}/citations/{row['citation_id']}", admin, {
                "review_status": "manual_confirmed",
                "review_note": "合成演练：人工确认，仅验证引用率口径",
            })
    print(f"引用确认：新增 {len(citations) - len(confirmed)} 条，累计 {len(citations)} 条")

    members = call("GET", f"/api/v1/projects/{PROJECT}/members?page_size=100", admin)["data"]
    if not any(row["username"] == args.reviewer_b and row["is_active"] for row in members):
        candidates = call("GET", f"/api/v1/projects/{PROJECT}/members/candidates?q={args.reviewer_b}", admin)["data"]
        target = next(row for row in candidates if row["username"] == args.reviewer_b)
        call("POST", f"/api/v1/projects/{PROJECT}/members", admin, {"user_id": target["id"], "role_code": "editor"})
        print(f"已加入第二标注账号：{args.reviewer_b}（editor）")

    token_a = login(args.reviewer_a, args.password)
    token_b = login(args.reviewer_b, args.password)
    items = call("GET", f"/api/v1/projects/{PROJECT}/sentiment/items?page_size=100", token_a)["data"]
    polarities = ("positive", "neutral", "neutral", "neutral", "negative")
    for index, item in enumerate(items):
        polarity = polarities[index % len(polarities)]
        for token in (token_a, token_b):
            call("POST", f"/api/v1/projects/{PROJECT}/sentiment/{item['citation_id']}/label", token, {
                "polarity": polarity,
                "note": "合成演练标注，两位账号同档",
            })
    print(f"双人标注：{len(items)} 条引用 × 2 人次 = {len(items) * 2} 条标签")

    summary = call("GET", f"/api/v1/projects/{PROJECT}/sentiment/summary", token_a)["data"]
    sampling = call("GET", f"/api/v1/projects/{PROJECT}/sentiment/sampling?size=60", token_a)["data"]
    consensus = call(
        "GET",
        f"/api/v1/projects/{PROJECT}/sentiment/consensus?size=60&round_no=5&cumulative=true",
        token_a,
    )["data"]
    print("summary：" + json.dumps(summary, ensure_ascii=False))
    print("sampling：" + json.dumps({"pool": sampling["pool"], "sample": len(sampling["sample"]), "widened": sampling["widened"]}, ensure_ascii=False))
    print("consensus：" + json.dumps({
        "sampled": consensus["sampled"],
        "consensus_total": consensus["consensus_total"],
        "counts": consensus["counts"],
        "disputed": consensus["disputed"],
        "pending_second": consensus["pending_second"],
        "reportable": consensus["reportable"],
        "positive_rate": consensus["positive_rate"],
    }, ensure_ascii=False))

    citation_stats = call("GET", f"/api/v1/projects/{PROJECT}/stats/overview", token_a)["data"]
    print("引用率：" + json.dumps({"citation_rate": citation_stats.get("citation_rate"), "valid_answers": citation_stats.get("valid_answers")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
