"use client";

import { useEffect, useState } from "react";

import { Badge, Panel } from "../ui";
import { StatePlaceholder } from "../states";
import { workbenchClient } from "@/lib/workbench/client";
import type { PublishClosureItemRecord, PublishClosureRecord } from "@/lib/workbench/types";

/**
 * P4 发布闭环看板。
 *
 * 与「发布回链」互补：回链以回执为轴，看不见没回执的单子；这里以任务为轴，
 * 直接标出断在哪一环。闭环率分母只算拿到回执的任务，检测失败不并入未收录。
 */

const STAGE_TONE: Record<string, "green" | "red" | "amber" | "slate" | "blue"> = {
  closed: "green",
  no_receipt: "red",
  task_closed: "slate",
  not_checked: "amber",
  check_failed: "red",
  not_in_index: "red",
  not_cited: "amber",
  not_published: "slate",
};

const STAGE_ORDER = ["closed", "not_cited", "not_in_index", "check_failed", "not_checked", "no_receipt", "task_closed", "not_published"];
const STAGE_LABEL: Record<string, string> = {
  closed: "闭环",
  not_cited: "未被引用",
  not_in_index: "未被收录",
  check_failed: "检测失败",
  not_checked: "未做收录检测",
  no_receipt: "缺回执",
  task_closed: "任务终止",
  not_published: "尚未发布",
};

function percent(rate: number | null): string {
  return rate === null ? "暂无回执，不计算" : `${(rate * 100).toFixed(1)}%`;
}

export function PublishClosureWorkspace({
  mode,
  projectId,
  canRead,
}: {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
}) {
  const [data, setData] = useState<PublishClosureRecord | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");

  const projectReady = Boolean(projectId) && projectId !== "all";
  const active = mode === "live" && canRead && projectReady;
  const loading = active && loadedFor !== projectId;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    workbenchClient.publishClosure(projectId)
      .then((result) => { if (!cancelled) { setData(result); setError(""); } })
      .catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "闭环数据加载失败"); })
      .finally(() => { if (!cancelled) setLoadedFor(projectId); });
    return () => { cancelled = true; };
  }, [projectId, active]);

  if (mode !== "live") {
    return <StatePlaceholder kind="not-collected" title="演示模式不展示发布闭环" description="闭环判定依赖真实任务、回执与引用，演示数据不参与。" />;
  }
  if (!canRead) {
    return <StatePlaceholder kind="permission" title="无权查看发布闭环" description="当前账号缺少发布读取能力，请联系项目管理员。" />;
  }
  if (!projectReady) {
    return <StatePlaceholder kind="empty" title="请先选择项目" description="闭环按项目算；在右上角选择具体项目后再看。" />;
  }
  if (loading) return <StatePlaceholder kind="loading" title="正在计算发布闭环" />;
  if (error) return <StatePlaceholder kind="error" title="闭环数据加载失败" description={error} />;
  if (!data) return <StatePlaceholder kind="empty" title="暂无发布任务" description="建了发布任务之后，这里会按任务标出链路断点。" />;

  const items = filter ? data.items.filter((item) => item.stage === filter) : data.items;

  return (
    <div className="report-layout">
      <Panel title="闭环概览">
        <div className="closure-summary">
          <div className="closure-kpi"><span>任务总数</span><strong>{data.summary.total_tasks}</strong></div>
          <div className="closure-kpi"><span>已拿回执</span><strong>{data.summary.tasks_with_receipt}</strong></div>
          <div className="closure-kpi"><span>闭环</span><strong>{data.summary.closed}</strong></div>
          <div className="closure-kpi"><span>闭环率</span><strong>{percent(data.summary.closure_rate)}</strong></div>
          <div className="closure-kpi"><span>回执前断点</span><strong>{data.summary.broken_before_receipt}</strong></div>
          <div className="closure-kpi"><span>回执后断点</span><strong>{data.summary.broken_after_receipt}</strong></div>
        </div>
        <div className="dist-chips">
          <button type="button" className={`basic-cat-chip${filter === "" ? " active" : ""}`} onClick={() => setFilter("")}>全部 {data.items.length}</button>
          {STAGE_ORDER.filter((stage) => (data.counts[stage] ?? 0) > 0).map((stage) => (
            <button key={stage} type="button" className={`basic-cat-chip${filter === stage ? " active" : ""}`} onClick={() => setFilter(stage)}>
              {STAGE_LABEL[stage]} {data.counts[stage]}
            </button>
          ))}
        </div>
        <ul className="factory-hint">
          {data.caveats.map((note) => <li key={note}>{note}</li>)}
        </ul>
      </Panel>

      {items.length === 0 ? (
        <StatePlaceholder kind="empty" compact title="该阶段没有任务" description="换个阶段看看，或者等任务流转后再来。" />
      ) : (
        <Panel title={`任务明细（${items.length}）`}>
          <div className="closure-list">
            {items.map((item) => <Row key={item.task_id} item={item} />)}
          </div>
        </Panel>
      )}
    </div>
  );
}

function Row({ item }: { item: PublishClosureItemRecord }) {
  return (
    <div className="closure-row">
      <div className="dist-card-head">
        <div>
          <strong>#{item.serial_no} {item.content_title}</strong>
          <p className="factory-hint">
            {item.channel_name ?? "未指定渠道"} · 任务 {item.task_status}
            {item.published_host ? ` · ${item.published_host}` : ""}
            {item.visibility_checked_at ? ` · 检测于 ${item.visibility_checked_at.slice(0, 16).replace("T", " ")}` : ""}
          </p>
        </div>
        <Badge tone={STAGE_TONE[item.stage] ?? "slate"}>{item.stage_label}</Badge>
      </div>
      <p className="factory-hint">{item.hint}</p>
      {item.published_url ? <p className="factory-hint closure-url">{item.published_url}</p> : null}
    </div>
  );
}
