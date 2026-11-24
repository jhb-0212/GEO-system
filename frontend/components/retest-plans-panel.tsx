"use client";

import { useEffect, useState, type FormEvent } from "react";

import { workbenchClient } from "@/lib/workbench/client";
import type { RetestPlanRecord, RetestPlanRunResult } from "@/lib/workbench/types";
import { Badge, Button, Icon, Panel, TextInput } from "./ui";

const roundStatusNames: Record<string, string> = {
  planning: "计划中",
  running: "执行中",
  completed: "已完成",
  closed: "已关闭",
};

function formatDateTime(value: string | null): string {
  if (!value) return "未记录";
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function toLocalInput(value: string): string {
  const date = new Date(value);
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function defaultFirstRun(): string {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(9, 0, 0, 0);
  return toLocalInput(date.toISOString());
}

export function RetestPlansPanel({
  mode,
  projectId,
  canExecute,
  onNotice,
  onGenerated,
}: {
  mode: "mock" | "live";
  projectId: string;
  canExecute: boolean;
  onNotice: (message: string) => void;
  onGenerated?: () => void;
}) {
  const [plans, setPlans] = useState<RetestPlanRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("每周复测");
  const [intervalDays, setIntervalDays] = useState(7);
  const [firstRunAt, setFirstRunAt] = useState(defaultFirstRun);
  const [entryScope, setEntryScope] = useState<string[]>(["api", "app_search"]);
  const [engineCodes, setEngineCodes] = useState("");
  const [samplesPerCell, setSamplesPerCell] = useState(1);
  const [enabled, setEnabled] = useState(true);

  async function loadPlans() {
    if (mode !== "live" || !projectId || projectId === "all") {
      setPlans([]);
      return;
    }
    try {
      const response = await workbenchClient.retestPlans(projectId);
      setPlans(response.data);
      setError("");
    } catch (cause) {
      setPlans([]);
      setError(cause instanceof Error ? cause.message : "复测计划加载失败");
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadPlans();
    }, 0);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, projectId]);

  function toggleScope(scope: string, checked: boolean) {
    setEntryScope((current) => checked ? [...new Set([...current, scope])] : current.filter((item) => item !== scope));
  }

  async function createPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canExecute || projectId === "all") return;
    if (!name.trim()) { onNotice("请输入计划名称"); return; }
    if (!entryScope.length) { onNotice("至少选择一个入口范围"); return; }
    setBusy(true);
    try {
      await workbenchClient.createRetestPlan(projectId, {
        name: name.trim(),
        interval_days: intervalDays,
        first_run_at: new Date(firstRunAt).toISOString(),
        entry_scope: entryScope,
        engine_codes: engineCodes.split(/[,，\s]+/).map((item) => item.trim()).filter(Boolean),
        samples_per_cell: samplesPerCell,
        enabled,
      });
      setShowForm(false);
      setName("每周复测");
      setIntervalDays(7);
      setFirstRunAt(defaultFirstRun());
      setEntryScope(["api", "app_search"]);
      setEngineCodes("");
      setSamplesPerCell(1);
      setEnabled(true);
      await loadPlans();
      onNotice("复测计划已创建");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "创建复测计划失败");
    } finally {
      setBusy(false);
    }
  }

  async function togglePlan(plan: RetestPlanRecord) {
    if (!canExecute) return;
    setBusy(true);
    try {
      await workbenchClient.updateRetestPlan(projectId, plan.id, { enabled: !plan.enabled });
      await loadPlans();
      onNotice(plan.enabled ? "复测计划已暂停" : "复测计划已启用");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "更新复测计划失败");
    } finally {
      setBusy(false);
    }
  }

  async function runNow(plan: RetestPlanRecord) {
    if (!canExecute) return;
    if (!window.confirm(`立即执行「${plan.name}」？会新建一轮并调用 API 入口，应用内入口只建待手测任务。`)) return;
    setBusy(true);
    try {
      const result: RetestPlanRunResult = await workbenchClient.runRetestPlan(projectId, plan.id);
      await loadPlans();
      onGenerated?.();
      onNotice(`已新建轮次 ${result.round_id.slice(0, 8)}…：API ${result.api_task_count} 条，应用内 ${result.manual_task_count} 条`);
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "立即执行复测失败");
    } finally {
      setBusy(false);
    }
  }

  if (mode !== "live") {
    return <Panel className="rounds-panel"><div className="panel-heading"><div><h3>固定周期复测</h3><p>真实接口模式下可用</p></div><Badge tone="slate">演示不执行</Badge></div><p className="knowledge-empty">演示模式不会创建复测计划，也不会调用 API。</p></Panel>;
  }

  return <Panel className="rounds-panel retest-plans-panel">
    <div className="panel-heading">
      <div><h3>固定周期复测</h3><p>到期自动建轮；API 自动采样，应用内入口只建待手测任务</p></div>
      <Button icon="plus" disabled={busy || !canExecute} onClick={() => setShowForm(true)}>新建计划</Button>
    </div>
    {error && <p className="form-error" role="alert">{error}</p>}
    <div className="rounds-list">
      {plans.map((plan) => <div key={plan.id} className="retest-plan-item">
        <div className="retest-plan-main">
          <strong>{plan.name}</strong>
          <span className="retest-plan-meta">
            每 {plan.interval_days} 天 · 每格 {plan.samples_per_cell} 次 · {plan.entry_scope.map((item) => item === "api" ? "API" : "应用内").join(" + ")}
            {plan.engine_codes.length ? ` · 引擎 ${plan.engine_codes.join(" / ")}` : " · 全部启用引擎"}
          </span>
          <span className="retest-plan-meta">
            下次 {formatDateTime(plan.next_run_at)} · 上次 {formatDateTime(plan.last_run_at)}
            {plan.latest_round_name && <> · 最近轮次「{plan.latest_round_name}」{roundStatusNames[plan.latest_round_status ?? ""] ?? plan.latest_round_status}</>}
          </span>
        </div>
        <div className="retest-plan-actions">
          <Badge tone={plan.enabled ? "green" : "slate"}>{plan.enabled ? "启用" : "暂停"}</Badge>
          <Button variant="secondary" disabled={busy || !canExecute} onClick={() => void togglePlan(plan)}>{plan.enabled ? "暂停" : "启用"}</Button>
          <Button variant="secondary" disabled={busy || !canExecute} onClick={() => void runNow(plan)}>立即执行</Button>
        </div>
      </div>)}
      {!plans.length && !error && <p className="knowledge-empty">还没有复测计划。建议每 7 天、每格 1 次，先控 API 成本。</p>}
    </div>
    <p className="knowledge-footnote">上一轮未结束时，下一次计划会跳过并顺延，避免人工任务越积越多；固定周期不会补做漏掉的轮次。</p>

    {showForm && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setShowForm(false); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="retest-plan-title">
        <div className="modal-header"><div><p className="eyebrow">RETEST PLAN</p><h2 id="retest-plan-title">新建复测计划</h2></div><button type="button" className="icon-button" aria-label="关闭" disabled={busy} onClick={() => setShowForm(false)}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">到点只建一次轮次；API 入口自动跑，应用内入口等人手测。上一轮没结束时本轮跳过。</p>
        <form onSubmit={createPlan} className="rounds-form">
          <TextInput label="计划名称" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：每周复测" disabled={busy}/>
          <label className="field"><span className="field-label">执行周期</span><select className="text-input" value={intervalDays} onChange={(event) => setIntervalDays(Number(event.target.value))} disabled={busy}><option value={7}>每 7 天</option><option value={14}>每 14 天</option><option value={30}>每 30 天</option></select></label>
          <label className="field"><span className="field-label">首次执行时间</span><input type="datetime-local" className="text-input" value={firstRunAt} onChange={(event) => setFirstRunAt(event.target.value)} disabled={busy}/></label>
          <div className="field"><span className="field-label">入口范围</span><div className="retest-scope">
            <label><input type="checkbox" checked={entryScope.includes("api")} onChange={(event) => toggleScope("api", event.target.checked)} disabled={busy}/> API 入口自动采样</label>
            <label><input type="checkbox" checked={entryScope.includes("app_search")} onChange={(event) => toggleScope("app_search", event.target.checked)} disabled={busy}/> 应用内入口（人工）</label>
          </div></div>
          <div className="field"><span className="field-label">API 引擎范围（可选）</span><input className="text-input" value={engineCodes} onChange={(event) => setEngineCodes(event.target.value)} placeholder="例如：deepseek；留空=全部启用引擎" disabled={busy}/></div>
          <label className="field"><span className="field-label">每格采样次数</span><select className="text-input" value={samplesPerCell} onChange={(event) => setSamplesPerCell(Number(event.target.value))} disabled={busy}><option value={1}>1 次（建议）</option><option value={3}>3 次（看波动，成本更高）</option></select></label>
          <label className="rounds-checkbox"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} disabled={busy}/> 创建后立即启用</label>
          <p className="knowledge-footnote">题目沿用当前启用题目；品牌题和通用题都会建任务，统计仍分开呈现。应用内入口只建 pending 任务，不自动调用。引擎范围只影响 API 入口，填一个引擎可以先把单引擎闭环跑通。</p>
          <div className="modal-actions"><Button type="submit" disabled={busy || !canExecute || !entryScope.length}>创建计划</Button><Button variant="secondary" disabled={busy} onClick={() => setShowForm(false)}>取消</Button></div>
        </form>
      </div>
    </div>}
  </Panel>;
}
