"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Panel } from "../ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { ConsumptionEvent, ConsumptionMetricRow, ConsumptionSummary } from "@/lib/workbench/types";

const DAY_OPTIONS = [7, 30, 90] as const;

/** 本地日历日：不能用 toISOString，东八区凌晨会退到前一天。 */
function dayOffset(offset: number): string {
  const date = new Date();
  date.setDate(date.getDate() - offset);
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function basisBadge(row: ConsumptionMetricRow) {
  return row.basis === "facts"
    ? <Badge tone="blue">事实派生</Badge>
    : <Badge tone="slate">事件账本</Badge>;
}

function MetricCard({ row }: { row: ConsumptionMetricRow }) {
  return <div className={`consumption-card${row.quota ? " consumption-card-alert" : ""}`}>
    <span className="consumption-card-head">
      <strong>{row.label}</strong>
      {basisBadge(row)}
    </span>
    <span className="consumption-card-value">
      {row.quantity}
      <small>{row.unit}</small>
    </span>
    <span className="consumption-card-note">{row.note}</span>
    {row.quota && <span className="consumption-card-quota">
      <Badge tone={row.quota.level === "exceeded" ? "red" : "amber"}>{row.quota.level === "exceeded" ? "已超额度" : "接近额度"}</Badge>
      <small>{row.quota.message}</small>
    </span>}
  </div>;
}

/** 消耗计量：六项并列，只答「用了多少」，不出现价格与金额。 */
export function ConsumptionWorkspace({ mode, projectId, canRead }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean;
}) {
  const [days, setDays] = useState<number>(30);
  const [summary, setSummary] = useState<ConsumptionSummary | null>(null);
  const [events, setEvents] = useState<ConsumptionEvent[]>([]);
  const [metricFilter, setMetricFilter] = useState<string>("");
  const [loadedKey, setLoadedKey] = useState("");
  const [error, setError] = useState("");

  const usable = mode === "live" && canRead && !!projectId && projectId !== "all";
  const requestKey = `${projectId}:${days}:${metricFilter}`;
  const loading = usable && loadedKey !== requestKey;

  useEffect(() => {
    if (!usable) return;
    let active = true;
    const start = dayOffset(days - 1);
    const end = dayOffset(0);
    Promise.all([
      workbenchClient.consumption(projectId, start, end),
      workbenchClient.consumptionEvents(projectId, { start, end, metric: metricFilter || undefined, limit: 120 }),
    ])
      .then(([summaryResult, eventRows]) => {
        if (!active) return;
        setSummary(summaryResult);
        setEvents(eventRows);
        setError("");
        setLoadedKey(requestKey);
      })
      .catch((cause) => {
        if (!active) return;
        setSummary(null);
        setEvents([]);
        setError(cause instanceof Error ? cause.message : "消耗数据加载失败");
        setLoadedKey(requestKey);
      });
    return () => { active = false; };
  }, [usable, projectId, days, metricFilter, requestKey]);

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">消耗计量仅真实接口模式可用。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有统计查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  const metricRows = summary?.metrics ?? [];
  const detailRows = metricRows.filter((row) => row.detail && row.detail.length > 0);

  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel consumption-panel">
      <div className="panel-heading">
        <div>
          <h3>消耗计量</h3>
          <p>六项分开计，单位不同不合计；能派生的实时数业务表，不能派生的读事件账本。</p>
        </div>
        <div className="toolbar-extra">
          {DAY_OPTIONS.map((option) => (
            <Button key={option} variant={days === option ? undefined : "secondary"} onClick={() => setDays(option)}>近 {option} 天</Button>
          ))}
          <Button variant="secondary" onClick={() => setLoadedKey("")}>刷新</Button>
        </div>
      </div>

      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && !summary && <p className="knowledge-empty">正在加载消耗数据…</p>}

      {summary && <>
        <p className="knowledge-footnote">
          统计区间 {summary.range.start} 至 {summary.range.end}
          {summary.scope === "organization" ? " · 客户级汇总" : " · 当前项目"}
          {summary.alerts.length > 0 ? ` · ${summary.alerts.length} 项额度提醒` : ""}
        </p>

        <div className="consumption-grid">
          {metricRows.map((row) => <MetricCard key={row.metric} row={row} />)}
        </div>

        {summary.alerts.length > 0 && <div className="consumption-alerts">
          {summary.alerts.map((alert) => <p key={alert.metric}>
            <Badge tone={alert.level === "exceeded" ? "red" : "amber"}>
              {alert.level === "exceeded" ? "超出额度" : "接近额度"}
            </Badge>
            <strong>{metricRows.find((row) => row.metric === alert.metric)?.label ?? alert.metric}</strong>
            <small>{alert.message}</small>
          </p>)}
        </div>}

        {detailRows.length > 0 && <div className="consumption-details">
          {detailRows.map((row) => <div className="consumption-detail" key={row.metric}>
            <h4>{row.label}明细</h4>
            <table className="consumption-table">
              <thead><tr><th>{row.metric === "collection" ? "引擎" : "类型"}</th><th>数量</th><th>占比</th></tr></thead>
              <tbody>
                {row.detail!.map((item) => <tr key={item.key}>
                  <td>{item.label}</td>
                  <td>{item.quantity}</td>
                  <td>{row.quantity > 0 ? `${((item.quantity / row.quantity) * 100).toFixed(1)}%` : "—"}</td>
                </tr>)}
              </tbody>
            </table>
          </div>)}
        </div>}

        <p className="knowledge-footnote">{summary.note}</p>
      </>}
    </Panel>

    <Panel className="knowledge-list-panel consumption-ledger-panel">
      <div className="panel-heading">
        <div><h3>消耗账本</h3><p>每一行是一次消耗事实，带来源 id；汇总数字由这里与业务表共同支撑。</p></div>
        <div className="toolbar-extra">
          <select className="text-input consumption-filter" value={metricFilter} onChange={(event) => setMetricFilter(event.target.value)}>
            <option value="">全部计量项</option>
            {metricRows.map((row) => <option key={row.metric} value={row.metric}>{row.label}</option>)}
          </select>
        </div>
      </div>

      {!metricFilter && <p className="knowledge-footnote">采集、生成、发布、线索由业务表直接统计，不另写账本；账本行只有收录检测与报告导出。</p>}

      {events.length === 0
        ? <p className="knowledge-empty">{loading ? "正在加载…" : "区间内没有事件类消耗（收录检测、报告导出）。"}</p>
        : <table className="consumption-table">
          <thead><tr><th>日期</th><th>计量项</th><th>数量</th><th>来源</th><th>来源 ID</th></tr></thead>
          <tbody>
            {events.map((event) => <tr key={event.id}>
              <td>{event.occurred_on}</td>
              <td>{event.label}</td>
              <td>{event.quantity} {event.unit}</td>
              <td>{event.source_type}</td>
              <td><code className="consumption-source">{event.source_id.length > 12 ? `${event.source_id.slice(0, 12)}…` : event.source_id}</code></td>
            </tr>)}
          </tbody>
        </table>}
    </Panel>
  </div>;
}
