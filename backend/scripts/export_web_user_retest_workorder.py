"""导出 P32 网页端复测的人工采样作业单。

从轮次任务表生成 24 条清单，按平台分组，附入口 URL、任务 ID、当前状态与
已有样本数。只读，不写库；用于运营逐题执行和交接。
"""

from __future__ import annotations

import argparse
import csv
import sys
import uuid
from pathlib import Path

from sqlalchemy import func, select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AiEngine,
    AiEngineEntry,
    MonitoringRound,
    MonitoringSample,
    MonitoringTask,
    Project,
    Question,
    QuestionVersion,
)

DEFAULT_ROUND_ID = uuid.UUID("79367876-9324-4507-b343-cc4135ff38b7")
DEFAULT_OUTPUT = "GEO_P32_网页端复测作业单_2026-11-21.md"
DEFAULT_CSV = "GEO_P32_网页端复测作业单_2026-11-21.csv"
FRONTEND_BASE_URL = "http://127.0.0.1:3000"

ENTRY_URL_FALLBACK = {
    "deepseek": "https://chat.deepseek.com/",
    "doubao": "https://www.doubao.com/chat/",
    "wenxin": "https://yiyan.baidu.com/",
    "yuanbao": "https://yuanbao.tencent.com/",
}
PLATFORM_ORDER = ("deepseek", "doubao", "wenxin", "yuanbao")


def _status(value: object) -> str:
    return str(getattr(value, "value", value))


def build(round_id: uuid.UUID) -> tuple[str, list[dict]]:
    with SessionLocal() as db:
        round_row = db.get(MonitoringRound, round_id)
        if round_row is None:
            raise SystemExit(f"轮次不存在：{round_id}")
        project = db.get(Project, round_row.project_id)
        samples = dict(
            db.execute(
                select(MonitoringSample.task_id, func.count(MonitoringSample.id))
                .join(MonitoringTask, MonitoringTask.id == MonitoringSample.task_id)
                .where(MonitoringTask.round_id == round_id)
                .group_by(MonitoringSample.task_id)
            ).all()
        )
        rows = db.execute(
            select(
                MonitoringTask,
                Question,
                QuestionVersion,
                AiEngine,
                AiEngineEntry,
            )
            .join(QuestionVersion, QuestionVersion.id == MonitoringTask.question_version_id)
            .join(Question, Question.id == QuestionVersion.question_id)
            .join(AiEngineEntry, AiEngineEntry.id == MonitoringTask.engine_entry_id)
            .join(AiEngine, AiEngine.id == AiEngineEntry.engine_id)
            .where(MonitoringTask.round_id == round_id)
            .order_by(Question.priority, Question.code, AiEngine.code)
        ).all()

    order = {code: index for index, code in enumerate(PLATFORM_ORDER)}
    records: list[dict] = []
    for task, question, version, engine, entry in rows:
        records.append(
            {
                "task_id": str(task.id),
                "question_code": question.code,
                "question_title": question.title,
                "question_text": version.text,
                "version_no": version.version_no,
                "engine_code": engine.code,
                "platform": engine.name,
                "entry_name": entry.name,
                "entry_url": entry.entry_url or ENTRY_URL_FALLBACK.get(engine.code, "—"),
                "manual_entry_url": (
                    f"{FRONTEND_BASE_URL}/workbench?section=samples"
                    f"&project_id={project.id}&task_id={task.id}"
                ),
                "status": _status(task.status),
                "sampling_mode": _status(task.sampling_mode),
                "sample_count": int(samples.get(task.id, 0)),
                "sampling_no": task.sampling_no,
                "sort_key": (order.get(engine.code, 99), question.priority, question.code),
            }
        )
    records.sort(key=lambda item: item["sort_key"])
    for index, item in enumerate(records, start=1):
        item["serial_no"] = index

    total = len(records)
    done = sum(1 for item in records if item["status"] == "done")
    failed = sum(1 for item in records if item["status"] == "failed")
    pending = sum(1 for item in records if item["status"] == "pending")
    with_sample = sum(1 for item in records if item["sample_count"] > 0)

    lines: list[str] = []
    add = lines.append
    add(f"# {project.name} P32 网页端同题复测作业单")
    add("")
    add(
        f"> 轮次：seq{round_row.seq}「{round_row.name}」；状态 `{_status(round_row.status)}`；"
        f"任务 {total} 条（pending {pending} / done {done} / failed {failed}），已有样本 {with_sample} 条。"
    )
    add("> 入口 URL 优先取入口表；为空时使用已核验的官方首页映射，仅用于人工打开，不代表采集协议。")
    add("")
    add("## 一、执行口径")
    add("")
    add("1. 逐题打开对应网页，**新开会话**，不复用上一题上下文。")
    add("2. 联网模式固定 `search_on`；每格只录 `sampling_no=1` 一条样本。")
    add("3. 记录回答原文、`answer_kind`（`answer` / `search_result` / `no_answer_surface`）、品牌提及原话、竞品、来源 URL。")
    add("4. 每题至少保存 1 张截图或录屏；证据必须挂到样本上。")
    add("5. 无法采样时登记 `manual-failure`，不要补造回答；失败样本进入失败分桶，不进入有效回答分母。")
    add("6. 24 条全部 `done` 或 `failed` 后，冻结复测快照，再与 seq5 做同题对比。")
    add("")
    add("## 二、平台直达链接")
    add("")
    add("| 平台 | 入口 | 网页直达 | 本地录入页 |")
    add("|---|---|---|---|")
    for code in PLATFORM_ORDER:
        group = [item for item in records if item["engine_code"] == code]
        if not group:
            continue
        first = group[0]
        add(
            f"| {first['platform']} | {first['entry_name']} | "
            f"[打开网页]({first['entry_url']}) | "
            f"[打开手测录入]({FRONTEND_BASE_URL}/workbench?section=samples&project_id={project.id}) |"
        )
    add("")
    add("## 三、按平台汇总")
    add("")
    add("| 平台 | 入口 | 任务数 | done | failed | pending | 已有样本 |")
    add("|---|---|---:|---:|---:|---:|---:|")
    for code in PLATFORM_ORDER:
        group = [item for item in records if item["engine_code"] == code]
        if not group:
            continue
        first = group[0]
        add(
            f"| {first['platform']} | {first['entry_name']} | {len(group)} | "
            f"{sum(1 for item in group if item['status'] == 'done')} | "
            f"{sum(1 for item in group if item['status'] == 'failed')} | "
            f"{sum(1 for item in group if item['status'] == 'pending')} | "
            f"{sum(1 for item in group if item['sample_count'] > 0)} |"
        )
    add("")
    add("## 四、24 条任务")
    add("")
    add("| # | 题目 | 平台 | 版本 | 网页入口 | 本地录入 | 任务 ID | 状态 | 样本 |")
    add("|---:|---|---|---:|---|---|---|---|---:|")
    for item in records:
        add(
            f"| {item['serial_no']} | {item['question_code']} | {item['platform']} | "
            f"v{item['version_no']} | [打开网页]({item['entry_url']}) | "
            f"[录入本题]({item['manual_entry_url']}) | `{item['task_id']}` | "
            f"{item['status']} | {item['sample_count']} |"
        )
    add("")
    add("## 五、题目原文")
    add("")
    add("| 题目 | 原文 |")
    add("|---|---|")
    seen: set[str] = set()
    for item in records:
        if item["question_code"] in seen:
            continue
        seen.add(item["question_code"])
        add(f"| {item['question_code']} | {item['question_text']} |")
    add("")
    return "\n".join(lines), records


def write_csv(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "serial_no",
                "question_code",
                "question_text",
                "platform",
                "entry_name",
                "entry_url",
                "manual_entry_url",
                "version_no",
                "task_id",
                "status",
                "sample_count",
            ],
        )
        writer.writeheader()
        for item in records:
            writer.writerow({key: item[key] for key in writer.fieldnames})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-id", default=str(DEFAULT_ROUND_ID))
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--csv-output", default=DEFAULT_CSV)
    args = parser.parse_args()
    markdown, records = build(uuid.UUID(args.round_id))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    write_csv(Path(args.csv_output), records)
    print(f"written: {output} ({len(markdown)} bytes), {args.csv_output} ({len(records)} rows)")


if __name__ == "__main__":
    main()
