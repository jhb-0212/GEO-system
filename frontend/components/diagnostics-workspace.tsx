"use client";

import { useCallback, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { TablePager } from "./table-pager";
import { formatDateTime, formatSerialNo } from "@/lib/workbench/format";
import { WORKBENCH_PAGE_SIZE, workbenchClient } from "@/lib/workbench/client";
import { usePagedData } from "@/lib/workbench/use-paged-data";
import type { DiagnosticSample, TraceChain } from "@/lib/workbench/types";

const failureLabels: Record<string, string> = {
  login_blocked: "登录受阻",
  timeout: "超时",
  access_blocked: "访问受限",
  captcha: "验证码",
  rate_limited: "限流",
  other: "其他",
};

function toneForFailure(code: string | null) {
  if (!code) return "slate" as const;
  if (code === "timeout" || code === "rate_limited") return "amber" as const;
  return "red" as const;
}

export function DiagnosticsWorkspace({ mode, projectId, canRead, isSystemAdmin }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; isSystemAdmin?: boolean;
}) {
  const [failureCode, setFailureCode] = useState("");
  const fetchDiagnostics = useCallback(
    (target: number) => workbenchClient.diagnostics(projectId, target, failureCode || undefined),
    [projectId, failureCode],
  );
  const { rows, total, page, setPage, loading, error, reload, refresh } = usePagedData<DiagnosticSample>({
    fetchPage: fetchDiagnostics,
    enabled: mode === "live" && canRead && !!projectId && projectId !== "all",
  });
  const [traceId, setTraceId] = useState("");
  const [trace, setTrace] = useState<TraceChain | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState("");
  const [unlockName, setUnlockName] = useState("");
  const [unlockIp, setUnlockIp] = useState("");
  const [unlockBusy, setUnlockBusy] = useState(false);
  const [unlockNotice, setUnlockNotice] = useState("");
  const [unlockError, setUnlockError] = useState("");

  async function loadTrace() {
    const value = traceId.trim();
    if (!value) { setTraceError("请输入 trace_id"); return; }
    setTraceLoading(true);
    try {
      const result = await workbenchClient.traceChain(projectId, value);
      setTrace(result); setTraceError("");
    } catch (cause) {
      setTrace(null); setTraceError(cause instanceof Error ? cause.message : "链路查询失败");
    } finally {
      setTraceLoading(false);
    }
  }

  async function submitUnlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setUnlockError("");
    setUnlockNotice("");
    const name = unlockName.trim();
    if (!name) { setUnlockError("请输入要解除的账号"); return; }
    setUnlockBusy(true);
    try {
      await workbenchClient.resetLoginThrottle(name, unlockIp.trim() || undefined);
      setUnlockNotice(unlockIp.trim()
        ? `已解除 ${name} 在 ${unlockIp.trim()} 上的登录限流，可以立即重试登录。`
        : `已解除 ${name} 的登录限流（含该账号最近的来源 IP），可以立即重试登录。`);
      setUnlockName("");
    } catch (cause) {
      setUnlockError(cause instanceof Error ? cause.message : "解除失败，请稍后再试");
    } finally {
      setUnlockBusy(false);
    }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">内部排障只读取真实接口数据，演示模式不展示。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有监测读取权限，无法查看排障数据。</p></Panel>;

  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    <Panel className="list-panel">
      <div className="panel-heading list-heading">
        <div><h3>失败样本与执行链路</h3><p>按失败样本聚合：失败码、重试次数、耗时、token 与 trace_id</p></div>
        <Badge tone={total ? "red" : "green"}>{total} 条失败</Badge>
      </div>
      <div className="table-toolbar">
        <div className="toolbar-left">
          <div className="filter-select">
            <select aria-label="筛选失败码" value={failureCode} onChange={(event) => { setFailureCode(event.target.value); refresh(); }}>
              <option value="">全部失败码</option>
              {Object.entries(failureLabels).map(([code, label]) => <option key={code} value={code}>{label} · {code}</option>)}
            </select>
          </div>
        </div>
        <div className="toolbar-extra"><Button variant="secondary" icon="refresh" disabled={loading} onClick={() => reload()}>{loading ? "加载中…" : "刷新"}</Button></div>
      </div>
      <div className="table-scroll">
        <table>
          <thead><tr><th>样本 / 任务</th><th>问题 / 引擎</th><th>失败码</th><th>重试</th><th>耗时</th><th>Token</th><th>完成时间</th><th>trace_id</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.sample_id}>
            <td><strong className="table-title">失败样本 #{formatSerialNo(row.serial_no)}</strong><small className="table-sub">{row.task_status} · attempt {row.attempt_no}</small></td>
            <td><strong className="table-title">{row.question_title || "—"}</strong><small className="table-sub">{row.engine_name || row.engine_code || "—"} · {row.question_code || "—"}</small></td>
            <td><Badge tone={toneForFailure(row.failure_code)} dot>{row.failure_code ? (failureLabels[row.failure_code] || row.failure_code) : "未记录"}</Badge>{row.failure_note && <small className="table-sub">{row.failure_note}</small>}</td>
            <td>{row.retry_count > 0 ? `${row.retry_count} 次` : "首次"}<small className="table-sub">attempt {row.attempt_no}</small></td>
            <td>{row.latency_ms == null ? "—" : `${row.latency_ms} ms`}</td>
            <td>{row.total_tokens == null ? "—" : row.total_tokens.toLocaleString()}</td>
            <td>{formatDateTime(row.finished_at)}</td>
            <td><code title={row.trace_id || "无 trace"}>{row.trace_id ? `${row.trace_id.slice(0, 12)}…` : "—"}</code></td>
          </tr>)}</tbody>
        </table>
        {!rows.length && <p className="knowledge-empty">{loading ? "正在加载排障数据…" : "当前筛选下没有失败样本"}</p>}
      </div>
      <TablePager page={page} total={total} pageSize={WORKBENCH_PAGE_SIZE} loading={loading} onChange={setPage}/>
    </Panel>
    <Panel className="knowledge-list-panel">
      <div className="panel-heading list-heading">
        <div><h3>跨实体 trace 链路</h3><p>轮次 → 任务 → 样本 → 引用 → 内容版本 → 发布任务；只查当前项目</p></div>
        <Badge tone={trace?.found ? "green" : trace ? "amber" : "slate"}>{trace ? (trace.found ? "已找到" : "未找到") : "待查询"}</Badge>
      </div>
      <div className="table-toolbar">
        <div className="toolbar-left"><label className="search-field"><input aria-label="trace_id" placeholder="输入 trace_id（32 位 hex）" value={traceId} onChange={(event) => setTraceId(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadTrace(); }}/></label></div>
        <div className="toolbar-extra"><Button variant="secondary" icon="search" disabled={traceLoading} onClick={() => void loadTrace()}>{traceLoading ? "查询中…" : "查链路"}</Button></div>
      </div>
      {traceError && <p className="form-error" role="alert">{traceError}</p>}
      {trace?.found && <>
        <p className="stats-excluded">轮次 {trace.counts.rounds} · 任务 {trace.counts.tasks} · 样本 {trace.counts.samples} · 引用 {trace.counts.citations} · 内容版本 {trace.counts.content_versions} · 发布任务 {trace.counts.publish_tasks}</p>
        <div className="trace-chain-grid">
          <section><h4>轮次 / 任务</h4>{trace.tasks.map((task) => <div key={task.id} className="trace-node"><strong>{task.question_title || task.question_code || "未命名问题"}</strong><small>{task.engine_name} · {task.entry_name} · {task.status}</small><code>任务 #{formatSerialNo(task.serial_no)} · v{task.version_no}</code></div>)}{!trace.tasks.length && <p className="knowledge-empty">无任务节点</p>}</section>
          <section><h4>样本</h4>{trace.samples.map((sample) => <div key={sample.id} className="trace-node"><strong>{sample.status} · {sample.brand_mentioned ? "提及品牌" : "未提及"}</strong><small>{sample.failure_code || "无失败码"} · {sample.latency_ms == null ? "无耗时" : `${sample.latency_ms} ms`} · {sample.total_tokens == null ? "无 token" : `${sample.total_tokens} token`}</small><code>样本 #{formatSerialNo(sample.serial_no)} · attempt {sample.attempt_no}</code></div>)}{!trace.samples.length && <p className="knowledge-empty">无样本节点</p>}</section>
          <section><h4>引用</h4>{trace.citations.map((citation) => <div key={citation.id} className="trace-node"><strong>{citation.domain || "未知域名"}</strong><small>{citation.is_brand_related ? "品牌相关" : "非品牌"} · {citation.citation_usage || "未标注使用方式"} · {citation.review_status || "未复核"}</small><code title={citation.raw_url}>{citation.raw_url}</code></div>)}{!trace.citations.length && <p className="knowledge-empty">无引用节点</p>}</section>
          <section><h4>内容版本 / 发布</h4>{trace.content_versions.map((version) => <div key={version.id} className="trace-node"><strong>{version.item_title} · v{version.version_no}</strong><small>{version.status} · {version.content_hash.slice(0, 12)}…</small><code>内容版本 v{version.version_no}</code></div>)}{trace.publish_tasks.map((task) => <div key={task.id} className="trace-node"><strong>{task.channel_name || "未知渠道"} · {task.publish_mode}</strong><small>{task.account_name || "未绑定账号"} · {task.status}</small><code>发布任务 #{formatSerialNo(task.serial_no)}</code></div>)}{!trace.content_versions.length && !trace.publish_tasks.length && <p className="knowledge-empty">无内容版本或发布节点</p>}</section>
        </div>
      </>}
      {trace && !trace.found && <p className="knowledge-empty">该 trace 在当前项目下没有任何任务、样本、引用或发布节点。</p>}
    </Panel>
    {isSystemAdmin && <Panel className="knowledge-editor-panel">
      <div className="panel-heading"><div><h3>解除登录限流</h3><p>限流按「账号 + 来源 IP」分桶（分钟 / 小时窗口），被误封时在这里立即放行</p></div><Icon name="lock" size={18}/></div>
      <form onSubmit={submitUnlock}>
        <label className="field"><span className="field-label">账号 *</span><input className="text-input" value={unlockName} maxLength={64} placeholder="例如 geo_editor" onChange={(event) => setUnlockName(event.target.value)}/></label>
        <label className="field"><span className="field-label">来源 IP（可留空：留空按账号解除全部来源）</span><input className="text-input" value={unlockIp} maxLength={64} placeholder="例如 203.0.113.7" onChange={(event) => setUnlockIp(event.target.value)}/></label>
        <div className="knowledge-actions"><Button type="submit" disabled={unlockBusy}>{unlockBusy ? "解除中…" : "解除限流"}</Button></div>
      </form>
      {unlockNotice && <p className="knowledge-footnote">{unlockNotice}</p>}
      {unlockError && <p className="form-error" role="alert">{unlockError}</p>}
    </Panel>}
  </div>;
}
