"""导出 GEO 试点轮次的逐格原始证据包。

只读：按 round_id 读取 monitoring_samples / monitoring_citations / 任务与入口，
生成 sample/citation 明细、原始回答与原始响应文件、逐文件 SHA256 清单，
并可选对引用 URL 做一次自动可达性探测（只作机器预检，不等于人工复核）。

用法（在 backend/ 下）：
    .venv/Scripts/python.exe scripts/export_pilot_round_evidence.py \
        --database-url "postgresql+psycopg://geo:geo_dev@localhost:5433/geo_pilot" \
        --round-id 250592b0-8596-43f1-9439-1f24360b6ea3 \
        --out-dir "C:/Users/EDY/Desktop/GEO系统开发/GEO_R1_真实采集_2026-11-27" \
        --probe
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

SAMPLE_SQL = """
select
    s.id as sample_id,
    s.task_id,
    s.status,
    s.sampled_at,
    s.finished_at,
    s.sampling_mode,
    s.conversation_mode,
    s.answer_kind,
    s.raw_answer,
    s.raw_response,
    s.request_payload,
    s.brand_mentioned,
    s.brand_identified,
    s.brand_recommendation,
    s.brand_match_kind,
    s.brand_match_term,
    s.brand_match_evidence,
    s.brand_list_rank,
    s.engine_model,
    s.model_version,
    s.latency_ms,
    s.failure_code,
    s.failure_note,
    s.trace_id,
    s.sampling_context,
    e.code as engine_code,
    ee.name as entry_name,
    ee.protocol,
    ee.model_name,
    ee.entry_url,
    ee.supports_search,
    q.code as question_code,
    q.title as question_title
from monitoring_samples s
join monitoring_tasks t on t.id = s.task_id
join ai_engine_entries ee on ee.id = t.engine_entry_id
join ai_engines e on e.id = ee.engine_id
join question_versions qv on qv.id = t.question_version_id
join questions q on q.id = qv.question_id
where t.round_id = %(round_id)s
order by e.code, q.code, s.attempt_no
"""

CITATION_SQL = """
select
    c.id as citation_id,
    c.sample_id,
    c.raw_url,
    c.normalized_url,
    c.domain,
    c.title,
    c.snippet,
    c.position,
    c.citation_order,
    c.is_brand_related,
    c.review_status,
    c.source_category,
    c.page_type,
    c.provider_payload,
    e.code as engine_code,
    q.code as question_code
from monitoring_citations c
join monitoring_samples s on s.id = c.sample_id
join monitoring_tasks t on t.id = s.task_id
join ai_engine_entries ee on ee.id = t.engine_entry_id
join ai_engines e on e.id = ee.engine_id
join question_versions qv on qv.id = t.question_version_id
join questions q on q.id = qv.question_id
where t.round_id = %(round_id)s
order by e.code, q.code, c.position, c.citation_order, c.id
"""

ROUND_SQL = """
select r.id, r.name, r.status, r.is_baseline, r.planned_at, r.created_at,
       p.code as project_code, p.name as project_name,
       b.canonical_name as brand_canonical_name
from monitoring_rounds r
join projects p on p.id = r.project_id
left join brand_profiles b on b.project_id = r.project_id
where r.id = %(round_id)s
"""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fields})


def probe_url(url: str) -> dict[str, Any]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    result: dict[str, Any] = {
        "url": url,
        "http_status": "",
        "final_url": "",
        "reachable": "",
        "error": "",
        "probed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            result["http_status"] = resp.status_code
            result["final_url"] = str(resp.url)
            result["reachable"] = "yes" if resp.status_code < 400 else "no"
    except Exception as exc:  # noqa: BLE001 - 探测失败要留痕
        result["reachable"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--round-id", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--probe", action="store_true", help="对引用 URL 做自动可达性探测")
    args = parser.parse_args()

    dsn = args.database_url.replace("postgresql+psycopg://", "postgresql://")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(ROUND_SQL, {"round_id": args.round_id})
            round_row = cur.fetchone()
            if not round_row:
                raise SystemExit(f"round not found: {args.round_id}")
            cur.execute(SAMPLE_SQL, {"round_id": args.round_id})
            samples = cur.fetchall()
            cur.execute(CITATION_SQL, {"round_id": args.round_id})
            citations = cur.fetchall()

    generated_at = datetime.now(timezone.utc).isoformat()
    round_info = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in round_row.items()}

    # ---- 原始回答 / 原始响应落盘，并计算内容指纹 ----
    sample_rows: list[dict[str, Any]] = []
    for s in samples:
        engine = s["engine_code"] or "unknown"
        qcode = s["question_code"] or "Q??"
        raw_answer = s.get("raw_answer") or ""
        raw_response = s.get("raw_response")
        response_text = stable_json(raw_response) if raw_response is not None else ""

        answer_path = Path("raw_answers") / engine / f"{qcode}.md"
        response_path = Path("raw_responses") / engine / f"{qcode}.json"
        (out_dir / answer_path).parent.mkdir(parents=True, exist_ok=True)
        (out_dir / answer_path).write_text(raw_answer, encoding="utf-8")
        (out_dir / response_path).parent.mkdir(parents=True, exist_ok=True)
        (out_dir / response_path).write_text(
            json.dumps(raw_response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        sample_rows.append(
            {
                "engine": engine,
                "question": qcode,
                "question_title": s["question_title"],
                "sample_id": str(s["sample_id"]),
                "task_id": str(s["task_id"]),
                "trace_id": s["trace_id"],
                "status": s["status"],
                "sampling_mode": s["sampling_mode"],
                "conversation_mode": s["conversation_mode"],
                "answer_kind": s["answer_kind"] or "",
                "entry_name": s["entry_name"],
                "protocol": s["protocol"],
                "model_name": s["model_name"],
                "engine_model": s["engine_model"] or "",
                "model_version": s["model_version"] or "",
                "supports_search": bool(s["supports_search"]),
                "sampled_at": s["sampled_at"].isoformat() if s["sampled_at"] else "",
                "finished_at": s["finished_at"].isoformat() if s["finished_at"] else "",
                "latency_ms": s["latency_ms"],
                "answer_chars": len(raw_answer),
                "answer_sha256": sha256_text(raw_answer),
                "response_sha256": sha256_text(response_text) if response_text else "",
                "raw_answer_file": answer_path.as_posix(),
                "raw_response_file": response_path.as_posix(),
                "brand_mentioned": bool(s["brand_mentioned"]),
                "brand_identified": bool(s["brand_identified"]),
                "brand_recommendation": bool(s["brand_recommendation"]),
                "brand_match_kind": s["brand_match_kind"] or "",
                "brand_match_term": s["brand_match_term"] or "",
                "brand_match_evidence": (s["brand_match_evidence"] or "")[:300],
                "brand_list_rank": s["brand_list_rank"] if s["brand_list_rank"] is not None else "",
                "failure_code": s["failure_code"] or "",
                "failure_note": s["failure_note"] or "",
            }
        )

    sample_fields = list(sample_rows[0].keys()) if sample_rows else []
    write_csv(out_dir / "samples.csv", sample_rows, sample_fields)
    write_json(out_dir / "samples.json", sample_rows)

    # ---- 引用明细 ----
    citation_rows: list[dict[str, Any]] = []
    for c in citations:
        canonical = {
            "url": c["normalized_url"] or c["raw_url"],
            "title": c["title"] or "",
            "snippet": c["snippet"] or "",
            "position": c["position"],
            "citation_order": c["citation_order"],
            "provider_payload": c["provider_payload"],
        }
        citation_rows.append(
            {
                "engine": c["engine_code"],
                "question": c["question_code"],
                "sample_id": str(c["sample_id"]),
                "citation_id": str(c["citation_id"]),
                "position": c["position"] if c["position"] is not None else "",
                "citation_order": c["citation_order"] if c["citation_order"] is not None else "",
                "raw_url": c["raw_url"] or "",
                "normalized_url": c["normalized_url"] or "",
                "domain": c["domain"] or "",
                "title": (c["title"] or "").replace("\n", " ")[:200],
                "snippet": (c["snippet"] or "").replace("\n", " ")[:300],
                "is_brand_related": bool(c["is_brand_related"]) if c["is_brand_related"] is not None else "",
                "review_status": c["review_status"] or "",
                "source_category": c["source_category"] or "",
                "page_type": c["page_type"] or "",
                "citation_record_sha256": sha256_text(stable_json(canonical)),
            }
        )
    citation_fields = list(citation_rows[0].keys()) if citation_rows else []
    write_csv(out_dir / "citations.csv", citation_rows, citation_fields)
    write_json(out_dir / "citations.json", citation_rows)

    # ---- 引用 URL 机器预检（可选，明确不是人工复核） ----
    probe_rows: list[dict[str, Any]] = []
    if args.probe:
        unique_urls = sorted({r["normalized_url"] or r["raw_url"] for r in citation_rows if (r["normalized_url"] or r["raw_url"])})
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(probe_url, u): u for u in unique_urls}
            for fut in concurrent.futures.as_completed(futures):
                probe_rows.append(fut.result())
        probe_rows.sort(key=lambda r: r["url"])
        write_csv(
            out_dir / "url_probe.csv",
            probe_rows,
            ["url", "http_status", "final_url", "reachable", "error", "probed_at"],
        )

    # ---- 汇总 ----
    per_engine: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"samples": 0, "valid": 0, "mentioned": 0, "identified": 0, "recommended": 0, "failed": 0}
    )
    for r in sample_rows:
        agg = per_engine[r["engine"]]
        agg["samples"] += 1
        if r["status"] in {"hit", "miss"}:
            agg["valid"] += 1
        if r["status"] == "failed" or r["failure_code"]:
            agg["failed"] += 1
        agg["mentioned"] += int(r["brand_mentioned"])
        agg["identified"] += int(r["brand_identified"])
        agg["recommended"] += int(r["brand_recommendation"])

    citations_per_engine = Counter(r["engine"] for r in citation_rows)
    hit_matrix = {
        q: {e: next((r["status"] for r in sample_rows if r["engine"] == e and r["question"] == q), None)
            for e in sorted({r["engine"] for r in sample_rows})}
        for q in sorted({r["question"] for r in sample_rows})
    }
    probe_summary = {}
    if probe_rows:
        probe_summary = {
            "unique_urls": len(probe_rows),
            "reachable_yes": sum(1 for r in probe_rows if r["reachable"] == "yes"),
            "reachable_no": sum(1 for r in probe_rows if r["reachable"] == "no"),
            "reachable_error": sum(1 for r in probe_rows if r["reachable"] == "error"),
            "note": "自动 HTTP 探测只作机器预检；引用可访问性与人工复核结论需双人另行签字。",
        }

    # ---- 文件清单与 SHA256 ----
    manifest: list[dict[str, str]] = []
    for p in sorted(out_dir.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            manifest.append(
                {
                    "path": p.relative_to(out_dir).as_posix(),
                    "bytes": str(p.stat().st_size),
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
            )

    summary = {
        "mode": "pilot-round-evidence-export",
        "generated_at": generated_at,
        "round": round_info,
        "counts": {
            "samples": len(sample_rows),
            "by_status": dict(Counter(r["status"] for r in sample_rows)),
            "citations": len(citation_rows),
            "citations_per_engine": dict(citations_per_engine),
            "mentions": sum(int(r["brand_mentioned"]) for r in sample_rows),
            "identified": sum(int(r["brand_identified"]) for r in sample_rows),
            "recommended": sum(int(r["brand_recommendation"]) for r in sample_rows),
        },
        "per_engine": dict(per_engine),
        "hit_matrix": hit_matrix,
        "url_probe": probe_summary,
        "boundary": [
            "本证据包只覆盖一个试点轮次、每格 1 个样本；提及率不能外推为平台整体结论。",
            "元宝是 search_result（检索结果聚合），与生成式回答的提及率必须分平台读，不能合并。",
            "文心入口在本轮 sampling_mode=search_on 但 0 条引用，属平台入口能力缺口，需单列说明，不得用其它平台数据补齐。",
            "citation_record_sha256 是引用记录（URL/标题/摘要/位置）的规范化 JSON 指纹，不是网页正文哈希。",
            "自动 URL 探测只证明机器当下能否打开，不替代人工复核；人工复核字段仍为空。",
            "本轮为本机试点库 geo_pilot 的人工采集轮，不是生产库结论，也不构成 CI 自动门禁。",
        ],
    }
    write_json(out_dir / "summary.json", summary)
    write_json(out_dir / "manifest.json", {"generated_at": generated_at, "files": manifest})

    print(
        json.dumps(
            {
                "out_dir": str(out_dir),
                "samples": len(sample_rows),
                "status": dict(Counter(r["status"] for r in sample_rows)),
                "citations": len(citation_rows),
                "per_engine": dict(per_engine),
                "url_probe": probe_summary,
                "files": len(manifest),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
