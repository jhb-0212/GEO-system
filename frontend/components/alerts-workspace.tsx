"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Panel } from "./ui";
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
      <div className="knowledge-list">{events.map((event) => <div className="knowledge-item" key={event.id}>
        <span>
          <strong>{codeNames[event.code] ?? event.code} · {event.title}</strong>
          <small>{event.message}</small>
          <small>当前 {percent(event.metric_value)} · 上一周期 {percent(event.baseline_value)} · 触发 {event.trigger_count} 次 · 样本 {event.current_samples ?? 0}</small>
          <small>{event.triggered_at ? new Date(event.triggered_at).toLocaleString("zh-CN") : ""} · webhook {event.webhook_status ?? "未配置"}</small>
        </span>
        <div className="knowledge-actions">
          <Badge tone={event.severity === "critical" ? "red" : "amber"}>{severityNames[event.severity] ?? event.severity}</Badge>
          {canWrite && event.status === "open" && <Button disabled={busy} onClick={() => void acknowledge(event, "ack")}>确认</Button>}
          {canWrite && event.status !== "resolved" && <Button variant="quiet" disabled={busy} onClick={() => void acknowledge(event, "resolve")}>标记恢复</Button>}
        </div>
      </div>)}{!events.length && <p className="knowledge-empty">该状态下暂无预警事件。</p>}</div>
    </Panel>
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>规则开关</h3><p>阈值保存在规则里，可按项目调整；关闭后不参与重算</p></div></div>
      <div className="knowledge-list">{rules.map((rule) => <div className="knowledge-item" key={rule.id}>
        <span><strong>{rule.name}</strong><small>{codeNames[rule.code] ?? rule.code} · {severityNames[rule.severity] ?? rule.severity}</small><small>{Object.entries(rule.thresholds ?? {}).map(([key, value]) => `${key}=${value}`).join(" · ")}</small></span>
        {canWrite ? <Button variant={rule.is_enabled ? "quiet" : "secondary"} disabled={busy} onClick={() => void toggle(rule)}>{rule.is_enabled ? "已启用" : "已关闭"}</Button> : <Badge tone={rule.is_enabled ? "green" : "slate"}>{rule.is_enabled ? "启用" : "关闭"}</Badge>}
      </div>)}</div>
    </Panel>
  </div>;
}


