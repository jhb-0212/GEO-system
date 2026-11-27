"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Panel } from "./ui";
import { DataTable } from "./data-table";
import { workbenchClient } from "@/lib/workbench/client";
import type { AlertEventRecord, AlertRuleRecord } from "@/lib/workbench/types";

const codeNames: Record<string, string> = {
  mention_rate_drop: "品牌提及率下降",
  recommendation_rate_drop: "被推荐率下降",
  competitor_outrank: "竞品反超",
  negative_share_rise: "负面占比上升",
  collection_failure_rate: "采集失败率",
};
const severityNames: Record<string, string> = { info: "提示", warning: "警告", critical: "严重" };
const statusNames: Record<string, string> = { open: "待处理", acknowledged: "已确认", resolved: "已恢复" };

function percent(value: number | null) {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export function AlertsWorkspace({ mode, projectId, canRead, canWrite, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean;
  onNotice: (message: string) => void;
}) {
  const [rules, setRules] = useState<AlertRuleRecord[]>([]);
  const [events, setEvents] = useState<AlertEventRecord[]>([]);
  const [statusFilter, setStatusFilter] = useState("open");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [ruleResult, eventResult] = await Promise.all([
      workbenchClient.alertRules(projectId),
      workbenchClient.alertEvents(projectId, statusFilter || undefined),
    ]);
    setRules(ruleResult.data);
    setEvents(eventResult.data);
  }, [projectId, statusFilter]);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([
      workbenchClient.alertRules(projectId),
      workbenchClient.alertEvents(projectId, statusFilter || undefined),
    ])
      .then(([ruleResult, eventResult]) => {
        if (!active) return;
        setRules(ruleResult.data);
        setEvents(eventResult.data);
        setError("");
      })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "预警加载失败"); });
    return () => { active = false; };
  }, [mode, projectId, canRead, statusFilter]);

  async function evaluate() {
    setBusy(true);
    try {
      const result = await workbenchClient.evaluateAlerts(projectId);
      setMessage(`本次命中 ${result.count} 条；24 小时内同一规则只更新次数，不重复推送。`);
      await load();
      onNotice("预警已重算");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "预警重算失败"); }
    finally { setBusy(false); }
  }

  async function toggle(rule: AlertRuleRecord) {
    setBusy(true);
    try {
      await workbenchClient.updateAlertRule(projectId, rule.id, { is_enabled: !rule.is_enabled });
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "规则更新失败"); }
    finally { setBusy(false); }
  }

  async function acknowledge(event: AlertEventRecord, action: "ack" | "resolve") {
    setBusy(true);
    try {
      if (action === "ack") await workbenchClient.acknowledgeAlert(projectId, event.id, "运营已确认");
      else await workbenchClient.resolveAlert(projectId, event.id);
      await load();
      onNotice(action === "ack" ? "预警已确认" : "预警已标记恢复");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "事件处理失败"); }
    finally { setBusy(false); }
  }

  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>预警事件</h3><p>五类规则按 7 天窗口对比上一周期；样本不足不触发，未知不写 0</p></div><Badge tone={events.length ? "red" : "green"}>{events.length} 条{statusNames[statusFilter] ?? "事件"}</Badge></div>
      <div className="knowledge-actions">
        {canWrite && <Button variant="secondary" disabled={busy} onClick={() => void evaluate()}>立即重算</Button>}
        {["open", "acknowledged", "resolved", ""].map((value) => <Button key={value || "all"} variant={statusFilter === value ? "primary" : "quiet"} onClick={() => setStatusFilter(value)}>{value ? statusNames[value] : "全部"}</Button>)}
      </div>
      {message && <p className="knowledge-footnote">{message}</p>}
      <DataTable columns={[
        { key: "event", label: "预警事件", width: "30%", className: "col-title", render: (event) => <><strong title={event.title}>{codeNames[event.code] ?? event.code} · {event.title}</strong><small className="data-cell-note" title={event.message}>{event.message}</small></> },
        { key: "metric", label: "当前 / 上期", width: "14%", className: "data-cell-mono", render: (event) => `${percent(event.metric_value)} / ${percent(event.baseline_value)}` },
        { key: "hits", label: "触发 / 样本", width: "12%", className: "data-cell-mono", render: (event) => `${event.trigger_count} 次 / ${event.current_samples ?? 0}` },
        { key: "time", label: "触发时间", width: "16%", className: "col-time", render: (event) => event.triggered_at ? new Date(event.triggered_at).toLocaleString("zh-CN", { hour12: false }) : "—" },
        { key: "severity", label: "级别", width: "10%", className: "col-status", render: (event) => <Badge tone={event.severity === "critical" ? "red" : "amber"}>{severityNames[event.severity] ?? event.severity}</Badge> },
        { key: "actions", label: "操作", width: "18%", className: "data-cell-actions", render: (event) => <>
          {canWrite && event.status === "open" && <Button disabled={busy} onClick={() => void acknowledge(event, "ack")}>确认</Button>}
          {canWrite && event.status !== "resolved" && <Button variant="quiet" disabled={busy} onClick={() => void acknowledge(event, "resolve")}>标记恢复</Button>}
          {(!canWrite || event.status === "resolved") && <small className="data-cell-note">{statusNames[event.status] ?? event.status}</small>}
        </> },
      ]} rows={events} rowKey={(event) => event.id} empty={<p className="knowledge-empty">该状态下暂无预警事件。</p>}/>
    </Panel>
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>规则开关</h3><p>阈值保存在规则里，可按项目调整；关闭后不参与重算</p></div></div>
      <DataTable columns={[
        { key: "name", label: "规则", width: "38%", className: "col-title", render: (rule) => <><strong>{rule.name}</strong><small className="data-cell-note">{codeNames[rule.code] ?? rule.code}</small></> },
        { key: "thresholds", label: "阈值", width: "40%", className: "data-cell-mono", render: (rule) => Object.entries(rule.thresholds ?? {}).map(([key, value]) => `${key}=${value}`).join(" · ") || "—" },
        { key: "severity", label: "级别", width: "10%", className: "col-status", render: (rule) => <Badge tone={rule.severity === "critical" ? "red" : "amber"}>{severityNames[rule.severity] ?? rule.severity}</Badge> },
        { key: "switch", label: "开关", width: "12%", className: "data-cell-actions", render: (rule) => canWrite
          ? <Button variant={rule.is_enabled ? "quiet" : "secondary"} disabled={busy} onClick={() => void toggle(rule)}>{rule.is_enabled ? "已启用" : "已关闭"}</Button>
          : <Badge tone={rule.is_enabled ? "green" : "slate"}>{rule.is_enabled ? "启用" : "关闭"}</Badge> },
      ]} rows={rules} rowKey={(rule) => rule.id}/>
    </Panel>
  </div>;
}


