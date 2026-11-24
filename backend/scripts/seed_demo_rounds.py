"""在演练项目上跑两轮合成数据，验证基线冻结、复测与 SoV。

只面向测试项目；所有样本都通过手测录入接口写入，并标注 note=合成演练，
不伪造“真实采集”。脚本可重复执行：已完成的轮次跳过，未完成任务补录。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any

BASE = os.environ.get("GEO_API_BASE", "http://127.0.0.1:8000")
PROJECT = os.environ.get("GEO_TEST_PROJECT_ID", "cefcae3f-d9f5-4f4f-a5fe-6cc548aa3119")
COMPETITORS = [
    {"name": "学而思", "domain": "https://www.xueersi.com", "notes": "合成演练竞品"},
    {"name": "新东方", "domain": "https://www.xdf.cn", "notes": "合成演练竞品"},
]


def call(method: str, path: str, token: str | None = None, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {path} -> {exc.code}: {detail}") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default=os.environ.get("GEO_ADMIN_USER", "geo_admin"))
    parser.add_argument("--password", default=os.environ.get("GEO_ADMIN_PASSWORD", "geo-admin-dev"))
    parser.add_argument("--operator", default=os.environ.get("GEO_OPERATOR_USER", "geo_editor"))
    parser.add_argument("--operator-password", default=os.environ.get("GEO_OPERATOR_PASSWORD", "geo-user-dev"))
    args = parser.parse_args()

    token = call("POST", "/api/v1/auth/login", body={"username": args.username, "password": args.password})["data"]["access_token"]
    admin_token = token
    project = next(
        row for row in call("GET", "/api/v1/projects?page_size=100", token)["data"] if row["id"] == PROJECT
    )
    print(f"项目：{project['code']} {project['name']}")

    # 项目管理员缺 monitoring.execute/question.write，演练项目需补一名运营/编辑成员
    members = call("GET", f"/api/v1/projects/{PROJECT}/members?page_size=100", token)["data"]
    if not any(row["username"] == args.operator and row["is_active"] for row in members):
        candidates = call("GET", f"/api/v1/projects/{PROJECT}/members/candidates?q={args.operator}", token)["data"]
        target = next(row for row in candidates if row["username"] == args.operator)
        call("POST", f"/api/v1/projects/{PROJECT}/members", token, {"user_id": target["id"], "role_code": "editor"})
        print(f"已加入成员：{args.operator}（运营/编辑）")
    operator_token = call("POST", "/api/v1/auth/login", body={"username": args.operator, "password": args.operator_password})["data"]["access_token"]
    token = operator_token

    # 1) 草稿题目转 active，否则基线分母为 0
    questions = call("GET", f"/api/v1/projects/{PROJECT}/questions?page_size=100", token)["data"]
    for row in questions:
        if row["status"] != "active":
            call("PATCH", f"/api/v1/projects/{PROJECT}/questions/{row['id']}", token, {"status": "active"})
    active = call("GET", f"/api/v1/projects/{PROJECT}/questions?page_size=100", token)["data"]
    qmap = {row["code"]: row["title"] for row in active}
    print(f"题目：{len(active)} 条 active")

    # 2) 竞品（SOV 分母）
    existing = call("GET", f"/api/v1/projects/{PROJECT}/competitors?page_size=100", token)["data"]
    names = {row["name"] for row in existing}
    for item in COMPETITORS:
        if item["name"] not in names:
            call("POST", f"/api/v1/projects/{PROJECT}/competitors", token, item)
    print(f"竞品：{len(existing) + sum(1 for item in COMPETITORS if item['name'] not in names)} 个")

    rounds = call("GET", f"/api/v1/projects/{PROJECT}/monitoring/rounds?page_size=100", token)["data"]
    baseline = next((row for row in rounds if row["is_baseline"]), None)
    if baseline is None:
        baseline = call("POST", f"/api/v1/projects/{PROJECT}/monitoring/rounds", token,
                        {"name": "演练基线（合成数据）", "is_baseline": True})["data"]
    print(f"基线轮：{baseline['name']} status={baseline['status']}")

    codes = sorted(qmap)
    baseline_plan = {
        code: {
            "brand": codes.index(code) < 6,
            "comp": "学而思" if codes.index(code) in {1, 4, 7} else "新东方" if codes.index(code) in {2, 8} else None,
        }
        for code in codes
    }
    retest_plan = {
        code: {
            "brand": codes.index(code) < 8,
            "comp": "学而思" if codes.index(code) == 9 else None,
        }
        for code in codes
    }

    def fill_round(round_row: dict, plan: dict, label: str) -> None:
        if round_row["status"] in ("completed", "closed"):
            print(f"{label} 已完成，跳过")
            return
        tasks = call("GET", f"/api/v1/projects/{PROJECT}/monitoring/tasks?round_id={round_row['id']}&page_size=100", token)["data"]
        if not tasks:
            call("POST", f"/api/v1/projects/{PROJECT}/monitoring/rounds/{round_row['id']}/tasks/batch", token,
                 {"entry_types": ["app_search", "web_user"], "samples_per_cell": 1})
            tasks = call("GET", f"/api/v1/projects/{PROJECT}/monitoring/tasks?round_id={round_row['id']}&page_size=100", token)["data"]
        print(f"{label} 任务：{len(tasks)} 条，待补录 {sum(1 for row in tasks if row['status'] != 'done')} 条")
        for task in tasks:
            if task["status"] == "done":
                continue
            item = plan[task["question_code"]]
            title = qmap[task["question_code"]]
            brand_part = (
                f"广州示例数字实训基地 提供「{title}」相关实训信息，可参考官方站点 https://example.com/guide-{task['question_code']}"
                if item["brand"] else "暂未看到明确品牌方的公开说明，可参考行业通用资料"
            )
            comp_part = f"同领域还可关注 {item['comp']}" if item["comp"] else "未提及其他同类机构"
            answer = f"围绕「{title}」：{brand_part}。{comp_part}。以上为公开信息整理，具体以官方发布为准。"
            url = (
                f"https://example.com/guide-{task['question_code']}" if item["brand"]
                else f"https://{('xueersi.com' if item['comp'] == '学而思' else 'xdf.cn')}/page-{task['question_code']}" if item["comp"]
                else "https://neutral.example.net/reference"
            )
            call("POST", f"/api/v1/projects/{PROJECT}/monitoring/tasks/{task['id']}/samples", token, {
                "raw_answer": answer,
                "answer_kind": "answer",
                "citation_urls": [url],
                "new_conversation_confirmed": True,
                "raw_response": (
                    {"competitor_mentions": [{"name": item["comp"], "evidence_text": f"同领域还可关注 {item['comp']}"}]}
                    if item["comp"] else {}
                ),
                "note": "合成演练数据，非真实采集",
            })
        pending = call("GET", f"/api/v1/projects/{PROJECT}/monitoring/tasks?round_id={round_row['id']}&page_size=100", token)["data"]
        if any(row["status"] != "done" for row in pending):
            raise SystemExit(f"{label} 仍有任务未完成，不能冻结快照")
        done = call("POST", f"/api/v1/projects/{PROJECT}/monitoring/rounds/{round_row['id']}/complete", token)
        print(f"{label} 冻结快照 {done['data']['snapshot_id']}（{done['data']['task_counts']}）")

    fill_round(baseline, baseline_plan, "基线轮")
    retest = next((row for row in rounds if row["name"] == "演练复测（合成数据）"), None)
    if retest is None:
        retest = call("POST", f"/api/v1/projects/{PROJECT}/monitoring/rounds", token,
                      {"name": "演练复测（合成数据）", "is_baseline": False})["data"]
    fill_round(retest, retest_plan, "复测轮")

    snapshots = call("GET", f"/api/v1/projects/{PROJECT}/stats/snapshots?page_size=100", token)["data"]
    overview = call("GET", f"/api/v1/projects/{PROJECT}/stats/overview", token)["data"]
    geo_overview = call("GET", f"/api/v1/projects/{PROJECT}/stats/geo", token)["data"]
    print("快照：")
    for item in snapshots:
        geo_metrics = item["metrics"]["geo"]
        print(json.dumps({
            "round": item["scope"]["round"]["name"],
            "seq": item["scope"]["round"]["seq"],
            "valid_answers": geo_metrics["valid_answers"],
            "mention_rate": geo_metrics["mention_rate"],
            "sov": geo_metrics["sov"],
            "sov_detail": geo_metrics["sov_detail"]["entities"],
            "by_competitor": geo_metrics.get("by_competitor", []),
        }, ensure_ascii=False))
    print("overview：" + json.dumps({key: overview.get(key) for key in ("valid_answers", "brand_mention_rate", "brand_identified_rate", "citation_rate")}, ensure_ascii=False))
    print("geo：" + json.dumps({"sov": geo_overview.get("sov"), "mention_rate": geo_overview.get("mention_rate"), "sov_detail": geo_overview.get("sov_detail")}, ensure_ascii=False))

    # 3) FAQ 出口：编辑起草 → 审核通过 → 公开可见
    author_token = token  # 运营/编辑：content.write
    faqs = call("GET", f"/api/v1/projects/{PROJECT}/faqs?page_size=100", author_token)["data"]
    published = [row for row in faqs if row["status"] == "published"]
    if not published:
        draft = call("POST", f"/api/v1/projects/{PROJECT}/faqs", author_token, {
            "question": "演练：零基础可以报名实训吗？",
            "answer": "可以。先完成基础测评，再按测评结果安排入门班；具体以官方当期说明为准。",
            "category": "报名咨询",
        })["data"]
        call("POST", f"/api/v1/projects/{PROJECT}/faqs/{draft['id']}/submit-review", author_token)
        call("POST", f"/api/v1/projects/{PROJECT}/faqs/{draft['id']}/review", admin_token, {"action": "approve"})
        print(f"FAQ 已发布：{draft['id']}")
    public = call("GET", f"/api/v1/public/projects/{project['code']}/faqs")["data"]
    print(f"公开 FAQ：{len(public)} 条")
    print("完成。合成样本均带 note=合成演练数据，非真实采集。")


if __name__ == "__main__":
    main()
