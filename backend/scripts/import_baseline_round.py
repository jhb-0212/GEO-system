"""把一个已跑完的监测轮次从源库导入目标库（默认 smoke -> 共享开发库）。

用途：24 格真实基线在隔离 smoke 库跑完后，共享库 `geo` 仍看不到结果。
本脚本只复制轮次 / 任务 / 样本 / 引用，不重建库、不重跑模型、不改源库。

安全边界：
- 默认 dry-run，只打印映射和数量；`--apply` 才写目标库。
- 只允许导入 `status='completed'` 的源轮次；源轮次不是 baseline 时必须显式
  `--allow-non-baseline`，且目标轮次保持 `is_baseline=false`。
- 目标项目必须已存在；目标库已有 baseline 时默认拒绝，除非显式 `--replace-baseline`。
- 题目版本按 `题目 code + version_no` 映射，引擎入口按 `引擎 code` 映射到目标库 active 入口。
- 样本 / 引用的复核字段一律置空，导入后仍需人工复核；渠道/竞品归属按 code 映射，
  映射不到时直接拒绝，避免静默丢归属。
- 导入轮次与任务记录导入操作人，并写 `monitoring.round_import` 审计。
"""

from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DEFAULT_SOURCE = "postgresql://geo:geo_dev@localhost:5433/geo_full24_lite_smoke"
DEFAULT_TARGET = "postgresql://geo:geo_dev@localhost:5433/geo"

ROUND_COLUMNS = (
    "id", "project_id", "seq", "name", "is_baseline", "planned_at", "status",
    "created_by", "created_at", "updated_at",
)
TASK_COLUMNS = (
    "id", "project_id", "round_id", "question_version_id", "engine_entry_id",
    "sampling_no", "sampling_mode", "status", "planned_at", "created_by",
    "created_at", "updated_at", "trace_id",
)
SAMPLE_COLUMNS = (
    "id", "project_id", "task_id", "attempt_no", "status", "sampled_at",
    "finished_at", "sampling_mode", "raw_answer", "raw_response",
    "brand_mentioned", "failure_code", "failure_note", "reviewed_by",
    "reviewed_at", "review_result", "review_note", "created_at", "updated_at",
    "engine_model", "model_version", "country_code", "language", "trace_id",
    "request_payload", "latency_ms", "prompt_tokens", "completion_tokens",
    "total_tokens", "estimated_cost_cny", "gateway_version", "brand_identified",
    "answer_kind",
)
CITATION_COLUMNS = (
    "id", "project_id", "sample_id", "raw_url", "normalized_url", "domain",
    "channel_id", "is_brand_related", "review_status", "reviewed_by",
    "reviewed_at", "review_note", "created_at", "updated_at", "citation_usage",
    "competitor_id", "trace_id",
)
AUDIT_COLUMNS = (
    "id", "project_id", "actor_id", "action", "target_type", "target_id",
    "payload", "created_at",
)


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, row_factory=dict_row)


def load_source(cur: psycopg.Cursor, round_id: uuid.UUID) -> dict[str, Any]:
    cur.execute(
        """SELECT id, project_id, seq, name, is_baseline, planned_at, status,
                  created_by, created_at, updated_at
           FROM monitoring_rounds WHERE id = %s""",
        (round_id,),
    )
    round_data = cur.fetchone()
    if round_data is None:
        raise SystemExit(f"源轮次不存在：{round_id}")

    cur.execute("SELECT id, code, name FROM projects WHERE id = %s", (round_data["project_id"],))
    project = cur.fetchone()
    if project is None:
        raise SystemExit("源轮次的项目不存在")

    cur.execute(
        """SELECT t.id, t.project_id, t.round_id, t.question_version_id,
                  t.engine_entry_id, t.sampling_no, t.sampling_mode, t.status,
                  t.planned_at, t.created_by, t.created_at, t.updated_at, t.trace_id,
                  q.code AS question_code, v.version_no,
                  en.code AS engine_code, e.entry_type, e.protocol, e.model_name
           FROM monitoring_tasks t
           JOIN question_versions v ON v.id = t.question_version_id
           JOIN questions q ON q.id = v.question_id
           JOIN ai_engine_entries e ON e.id = t.engine_entry_id
           JOIN ai_engines en ON en.id = e.engine_id
           WHERE t.round_id = %s
           ORDER BY q.code, en.code""",
        (round_id,),
    )
    tasks = cur.fetchall()

    cur.execute(
        """SELECT s.*
           FROM monitoring_samples s
           JOIN monitoring_tasks t ON t.id = s.task_id
           WHERE t.round_id = %s
           ORDER BY s.created_at, s.id""",
        (round_id,),
    )
    samples = cur.fetchall()

    cur.execute(
        """SELECT c.*
           FROM monitoring_citations c
           JOIN monitoring_samples s ON s.id = c.sample_id
           JOIN monitoring_tasks t ON t.id = s.task_id
           WHERE t.round_id = %s
           ORDER BY c.created_at, c.id""",
        (round_id,),
    )
    citations = cur.fetchall()

    # 引用可能带渠道/竞品归属；跨库 UUID 不能直接复制，先按 code/name 建映射。
    project_id = round_data["project_id"]
    cur.execute("SELECT id, code FROM channels WHERE project_id = %s", (project_id,))
    channel_codes = {str(row["id"]): row["code"] for row in cur.fetchall()}
    cur.execute("SELECT id, name FROM competitors WHERE project_id = %s", (project_id,))
    competitor_names = {str(row["id"]): row["name"] for row in cur.fetchall()}

    return {
        "round": round_data,
        "project": project,
        "tasks": tasks,
        "samples": samples,
        "citations": citations,
        "channel_codes": channel_codes,
        "competitor_names": competitor_names,
    }


def target_maps(cur: psycopg.Cursor, project_code: str, actor_username: str) -> dict[str, Any]:
    cur.execute("SELECT id, code, name FROM projects WHERE code = %s", (project_code,))
    project = cur.fetchone()
    if project is None:
        raise SystemExit(f"目标库没有项目 {project_code}")
    project_id = project["id"]

    cur.execute("SELECT id FROM users WHERE username = %s", (actor_username,))
    actor = cur.fetchone()
    if actor is None:
        raise SystemExit(f"目标库没有导入操作人账号 {actor_username}")

    cur.execute(
        """SELECT q.code, v.version_no, v.id
           FROM question_versions v
           JOIN questions q ON q.id = v.question_id
           WHERE q.project_id = %s AND q.status = 'active'
             AND q.code LIKE 'Q%%'
           ORDER BY q.code, v.version_no""",
        (project_id,),
    )
    qv_map = {(row["code"], row["version_no"]): row["id"] for row in cur.fetchall()}

    cur.execute(
        """SELECT en.code, e.id
           FROM ai_engine_entries e
           JOIN ai_engines en ON en.id = e.engine_id
           WHERE e.is_active IS TRUE
           ORDER BY en.code, e.id""",
    )
    entry_map: dict[str, list[uuid.UUID]] = {}
    for row in cur.fetchall():
        entry_map.setdefault(row["code"], []).append(row["id"])

    cur.execute("SELECT id, code FROM channels WHERE project_id = %s", (project_id,))
    channel_map = {row["code"]: row["id"] for row in cur.fetchall()}
    cur.execute("SELECT id, name FROM competitors WHERE project_id = %s", (project_id,))
    competitor_map = {row["name"]: row["id"] for row in cur.fetchall()}

    cur.execute(
        """SELECT id, seq, name, is_baseline, status
           FROM monitoring_rounds WHERE project_id = %s ORDER BY seq""",
        (project_id,),
    )
    return {
        "project_id": project_id,
        "actor_id": actor["id"],
        "qv_map": qv_map,
        "entry_map": entry_map,
        "channel_map": channel_map,
        "competitor_map": competitor_map,
        "rounds": cur.fetchall(),
    }


def plan_import(
    source: dict[str, Any],
    target: dict[str, Any],
    replace_baseline: bool,
    allow_non_baseline: bool = False,
) -> dict[str, Any]:
    if source["project"]["code"] != "gz-base":
        raise SystemExit(f"源项目不是 gz-base，而是 {source['project']['code']}")

    source_round = source["round"]
    if source_round["status"] != "completed":
        raise SystemExit(
            f"源轮次 {source_round['id']} 状态是 {source_round['status']}，"
            "只允许导入 completed 轮次"
        )
    source_is_baseline = bool(source_round["is_baseline"])
    if not source_is_baseline and not allow_non_baseline:
        raise SystemExit(
            f"源轮次 {source_round['id']} 不是 baseline；"
            "如确认要导入历史轮次，加 --allow-non-baseline（目标轮次不会成为 baseline）"
        )

    baseline = [row for row in target["rounds"] if row["is_baseline"]]
    if source_is_baseline and baseline and not replace_baseline:
        raise SystemExit(
            "目标库已有 baseline 轮次，默认拒绝导入。"
            "如确认要替换，加 --replace-baseline（旧轮会降级为历史轮）。"
        )

    new_seq = max((row["seq"] for row in target["rounds"]), default=0) + 1

    task_plan: list[dict[str, Any]] = []
    for row in source["tasks"]:
        qv = target["qv_map"].get((row["question_code"], row["version_no"]))
        if qv is None:
            raise SystemExit(f"目标库缺少题目版本：{row['question_code']} v{row['version_no']}")
        entries = target["entry_map"].get(row["engine_code"], [])
        if len(entries) != 1:
            raise SystemExit(
                f"目标库引擎 {row['engine_code']} 的 active 入口不是唯一一个：{entries}"
            )
        task_plan.append({
            "source_id": row["id"],
            "new_id": uuid.uuid4(),
            "question_version_id": qv,
            "engine_entry_id": entries[0],
            "sampling_no": row["sampling_no"],
            "sampling_mode": row["sampling_mode"],
            "status": row["status"],
            "planned_at": row["planned_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "trace_id": row["trace_id"],
            "question_code": row["question_code"],
            "version_no": row["version_no"],
            "engine_code": row["engine_code"],
        })

    return {
        "new_seq": new_seq,
        "is_baseline": source_is_baseline,
        "baseline_to_close": baseline[0]["id"] if source_is_baseline and baseline else None,
        "task_plan": task_plan,
        "task_id_map": {row["source_id"]: row["new_id"] for row in task_plan},
    }


def insert_rows(cur: psycopg.Cursor, table: str, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    placeholders = ", ".join(["%s"] * len(columns))
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        sql.SQL(placeholders),
    )
    cur.executemany(
        statement,
        [[row[column] for column in columns] for row in rows],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", default=DEFAULT_SOURCE)
    parser.add_argument("--target-url", default=DEFAULT_TARGET)
    parser.add_argument("--source-round", required=True)
    parser.add_argument("--project-code", default="gz-base")
    parser.add_argument("--actor-username", default="geo_admin")
    parser.add_argument("--name", default=None)
    parser.add_argument("--replace-baseline", action="store_true")
    parser.add_argument(
        "--allow-non-baseline",
        action="store_true",
        help="允许导入 completed 但不是 baseline 的历史轮次；目标轮次保持 is_baseline=false",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source_round_id = uuid.UUID(args.source_round)
    with connect(args.source_url) as source_conn, source_conn.cursor() as source_cur:
        source = load_source(source_cur, source_round_id)

    with connect(args.target_url) as target_conn, target_conn.cursor() as target_cur:
        target = target_maps(target_cur, args.project_code, args.actor_username)
        plan = plan_import(
            source,
            target,
            args.replace_baseline,
            args.allow_non_baseline,
        )

        print(f"源轮次：{source['round']['name']}（{source['round']['status']}，baseline={source['round']['is_baseline']}）")
        print(f"源项目：{source['project']['code']} / {source['project']['name']}")
        print(f"导入操作人：{args.actor_username}（{target['actor_id']}）")
        print(f"目标项目：{args.project_code}；新 seq={plan['new_seq']}；is_baseline={plan['is_baseline']}")
        print(f"任务 {len(plan['task_plan'])}；样本 {len(source['samples'])}；引用 {len(source['citations'])}")
        print("映射：")
        for row in plan["task_plan"][:8]:
            print(f"  {row['question_code']} v{row['version_no']} / {row['engine_code']} -> {row['engine_entry_id']}")
        if len(plan["task_plan"]) > 8:
            print(f"  ... 共 {len(plan['task_plan'])} 条")

        if not args.apply:
            print("\n[dry-run] 未写入。确认后加 --apply。")
            return 0

        now = datetime.now(timezone.utc)
        new_round_id = uuid.uuid4()
        round_name = args.name or (
            "首月 24 格真实基线（导入 smoke）"
            if plan["is_baseline"]
            else "历史轮次导入（非 baseline）"
        )
        task_rows: list[dict[str, Any]] = []
        sample_rows: list[dict[str, Any]] = []
        citation_rows: list[dict[str, Any]] = []

        with target_conn.transaction():
            if plan["baseline_to_close"]:
                target_cur.execute(
                    """UPDATE monitoring_rounds
                       SET is_baseline = FALSE,
                           status = CASE WHEN status = 'running' THEN 'closed' ELSE status END,
                           updated_at = %s
                       WHERE id = %s""",
                    (now, plan["baseline_to_close"]),
                )

            insert_rows(target_cur, "monitoring_rounds", ROUND_COLUMNS, [{
                "id": new_round_id,
                "project_id": target["project_id"],
                "seq": plan["new_seq"],
                "name": round_name,
                "is_baseline": plan["is_baseline"],
                "planned_at": source["round"]["planned_at"],
                "status": source["round"]["status"],
                "created_by": target["actor_id"],
                "created_at": source["round"]["created_at"] or now,
                "updated_at": now,
            }])

            for row in plan["task_plan"]:
                task_rows.append({
                    "id": row["new_id"],
                    "project_id": target["project_id"],
                    "round_id": new_round_id,
                    "question_version_id": row["question_version_id"],
                    "engine_entry_id": row["engine_entry_id"],
                    "sampling_no": row["sampling_no"],
                    "sampling_mode": row["sampling_mode"],
                    "status": row["status"],
                    "planned_at": row["planned_at"],
                    "created_by": target["actor_id"],
                    "created_at": row["created_at"] or now,
                    "updated_at": now,
                    "trace_id": row["trace_id"],
                })
            insert_rows(target_cur, "monitoring_tasks", TASK_COLUMNS, task_rows)

            for sample in source["samples"]:
                new_task_id = plan["task_id_map"].get(sample["task_id"])
                if new_task_id is None:
                    raise SystemExit(f"样本 {sample['id']} 的任务不在本轮")
                sample_rows.append({
                    "id": uuid.uuid4(),
                    "project_id": target["project_id"],
                    "task_id": new_task_id,
                    "attempt_no": sample["attempt_no"],
                    "status": sample["status"],
                    "sampled_at": sample["sampled_at"],
                    "finished_at": sample["finished_at"],
                    "sampling_mode": sample["sampling_mode"],
                    "raw_answer": sample["raw_answer"],
                    "raw_response": Jsonb(sample["raw_response"]) if sample["raw_response"] is not None else None,
                    "brand_mentioned": sample["brand_mentioned"],
                    "failure_code": sample["failure_code"],
                    "failure_note": sample["failure_note"],
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "review_result": None,
                    "review_note": None,
                    "created_at": sample["created_at"] or now,
                    "updated_at": now,
                    "engine_model": sample["engine_model"],
                    "model_version": sample["model_version"],
                    "country_code": sample["country_code"],
                    "language": sample["language"],
                    "trace_id": sample["trace_id"],
                    "request_payload": Jsonb(sample["request_payload"]) if sample["request_payload"] is not None else None,
                    "latency_ms": sample["latency_ms"],
                    "prompt_tokens": sample["prompt_tokens"],
                    "completion_tokens": sample["completion_tokens"],
                    "total_tokens": sample["total_tokens"],
                    "estimated_cost_cny": sample["estimated_cost_cny"],
                    "gateway_version": sample["gateway_version"],
                    "brand_identified": sample["brand_identified"],
                    "answer_kind": sample["answer_kind"],
                })
            insert_rows(target_cur, "monitoring_samples", SAMPLE_COLUMNS, sample_rows)

            # source sample id -> new sample id; the loop above used generated ids
            sample_id_map = {}
            for source_sample, new_sample in zip(source["samples"], sample_rows):
                sample_id_map[source_sample["id"]] = new_sample["id"]

            for citation in source["citations"]:
                new_sample_id = sample_id_map.get(citation["sample_id"])
                if new_sample_id is None:
                    raise SystemExit(f"引用 {citation['id']} 的样本不在本轮")

                channel_code = None
                if citation["channel_id"] is not None:
                    channel_code = source["channel_codes"].get(str(citation["channel_id"]))
                    if channel_code is None:
                        raise SystemExit(
                            f"引用 {citation['id']} 的渠道 {citation['channel_id']} 在源项目中找不到 code"
                        )
                target_channel_id = (
                    target["channel_map"].get(channel_code) if channel_code is not None else None
                )
                if channel_code is not None and target_channel_id is None:
                    raise SystemExit(
                        f"目标库没有渠道 code={channel_code}，拒绝静默丢弃引用归属"
                    )

                competitor_name = None
                if citation["competitor_id"] is not None:
                    competitor_name = source["competitor_names"].get(
                        str(citation["competitor_id"])
                    )
                    if competitor_name is None:
                        raise SystemExit(
                            f"引用 {citation['id']} 的竞品 {citation['competitor_id']} 在源项目中找不到 name"
                        )
                target_competitor_id = (
                    target["competitor_map"].get(competitor_name)
                    if competitor_name is not None
                    else None
                )
                if competitor_name is not None and target_competitor_id is None:
                    raise SystemExit(
                        f"目标库没有竞品 name={competitor_name}，拒绝静默丢弃引用归属"
                    )

                citation_rows.append({
                    "id": uuid.uuid4(),
                    "project_id": target["project_id"],
                    "sample_id": new_sample_id,
                    "raw_url": citation["raw_url"],
                    "normalized_url": citation["normalized_url"],
                    "domain": citation["domain"],
                    "channel_id": target_channel_id,
                    "is_brand_related": bool(citation["is_brand_related"]),
                    "review_status": "auto",
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "review_note": None,
                    "created_at": citation["created_at"] or now,
                    "updated_at": now,
                    "citation_usage": citation["citation_usage"],
                    "competitor_id": target_competitor_id,
                    "trace_id": citation["trace_id"],
                })
            insert_rows(target_cur, "monitoring_citations", CITATION_COLUMNS, citation_rows)

            insert_rows(target_cur, "audit_logs", AUDIT_COLUMNS, [{
                "id": uuid.uuid4(),
                "project_id": target["project_id"],
                "actor_id": target["actor_id"],
                "action": "monitoring.round_import",
                "target_type": "monitoring_round",
                "target_id": new_round_id,
                "payload": Jsonb({
                    "source_round_id": str(source["round"]["id"]),
                    "source_round_name": source["round"]["name"],
                    "source_round_status": source["round"]["status"],
                    "source_is_baseline": source["round"]["is_baseline"],
                    "target_is_baseline": plan["is_baseline"],
                    "task_count": len(task_rows),
                    "sample_count": len(sample_rows),
                    "citation_count": len(citation_rows),
                }),
                "created_at": now,
            }])

        print("\n导入完成：")
        print(f"  round_id={new_round_id} seq={plan['new_seq']} status={source['round']['status']} is_baseline={plan['is_baseline']}")
        print(f"  tasks={len(task_rows)} samples={len(sample_rows)} citations={len(citation_rows)}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
