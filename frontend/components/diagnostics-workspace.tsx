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
  rate_limited: "请求太频繁",
  other: "其他",
};

const taskStatusLabels: Record<string, string> = {
  pending: "待执行", running: "执行中", done: "已完成", failed: "失败", cancelled: "已取消", uncertain: "待核实",
};
const sampleStatusLabels: Record<string, string> = {
  pending: "待执行", running: "执行中", hit: "已命中", miss: "未命中", no_answer_surface: "没有返回答案", failed: "执行失败", manual_review: "待人工复核",
};
const citationStatusLabels: Record<string, string> = { auto: "自动复核", manual_confirmed: "人工确认", manual_rejected: "人工排除" };
const citationUsageLabels: Record<string, string> = { used: "影响回答但未明确引用", cited: "回答中明确引用" };
const contentStatusLabels: Record<string, string> = {
  draft: "草稿", pending_review: "待审核", approved: "已通过", rejected: "已驳回", scheduled: "已排期",
  pending_publish: "待发布", published: "已发布", needs_attention: "需要处理", archived: "已归档",
};
const publishModeLabels: Record<string, string> = { manual: "人工发布", api: "接口发布", authorized: "授权发布" };
const labelOf = (labels: Record<string, string>, value: string | null | undefined, fallback = "未记录") => value ? (labels[value] || value) : fallback;

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
    if (!value) { setTraceError("请输入执行编号"); return; }
    setTraceLoading(true);
    try {
      const result = await workbenchClient.traceChain(projectId, value);
      setTrace(result); setTraceError("");
    } catch (cause) {
      setTrace(null); setTraceError(cause instanceof Error ? cause.message : "查询失败，请确认执行编号后重试");
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
        ? `已解除 ${name} 在 ${unlockIp.trim()} 上的登录限制，可以立即重试登录。`
        : `已解除 ${name} 的登录限制（含该账号最近的来源 IP），可以立即重试登录。`);
      setUnlockName("");
    } catch (cause) {
      setUnlockError(cause instanceof Error ? cause.message : "解除失败，请稍后再试");
    } finally {
      setUnlockBusy(false);
    }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">问题排查只读取真实数据，演示模式不展示。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有查看监测数据的权限，无法排查。</p></Panel>;

  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    <Panel className="list-panel">
      <div className="panel-heading list-heading">
        <div><h3>失败记录与排查线索</h3><p>这些记录表示这次没拿到 AI 回答，不代表品牌没被提及；先按失败原因筛选，再决定刷新重试或联系管理员。</p></div>
        <Badge tone={total ? "red" : "green"}>{total} 条待排查</Badge>
      </div>
      <div className="table-toolbar">
        <div className="toolbar-left">
          <div className="filter-select">
            <select aria-label="按失败原因筛选" value={failureCode} onChange={(event) => { setFailureCode(event.target.value); refresh(); }}>
              <option value="">全部失败原因</option>
              {Object.entries(failureLabels).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
            </select>
          </div>
        </div>
        <div className="toolbar-extra"><Button variant="secondary" icon="refresh" disabled={loading} onClick={() => reload()}>{loading ? "加载中…" : "刷新"}</Button></div>
      </div>
      <div className="table-scroll">
        <table>
          <thead><tr><th>失败记录</th><th>问题 / 引擎</th><th>失败原因</th><th>尝试情况</th><th>耗时</th><th>Token 消耗</th><th>完成时间</th><th>执行编号</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.sample_id}>
            <td><strong className="table-title">失败记录 #{formatSerialNo(row.serial_no)}</strong><small className="table-sub">{labelOf(taskStatusLabels, row.task_status)} · 第 {row.attempt_no} 次尝试</small></td>
            <td><strong className="table-title">{row.question_title || "—"}</strong><small className="table-sub">{row.engine_name || row.engine_code || "—"} · {row.question_code || "—"}</small></td>
            <td><Badge tone={toneForFailure(row.failure_code)} dot>{row.failure_code ? (failureLabels[row.failure_code] || row.failure_code) : "未记录"}</Badge>{row.failure_note && <small className="table-sub">{row.failure_note}</small>}</td>
            <td>{row.retry_count > 0 ? `重试 ${row.retry_count} 次` : row.attempt_no > 1 ? `第 ${row.attempt_no} 次尝试` : "首次尝试"}</td>
            <td>{row.latency_ms == null ? "—" : `${row.latency_ms} ms`}</td>
            <td>{row.total_tokens == null ? "—" : row.total_tokens.toLocaleString()}</td>
            <td>{formatDateTime(row.finished_at)}</td>
            <td><code title={row.trace_id ? `执行编号：${row.trace_id}` : "没有执行编号"}>{row.trace_id ? `${row.trace_id.slice(0, 12)}…` : "—"}</code></td>
          </tr>)}</tbody>
        </table>
        {!rows.length && <p className="knowledge-empty">{loading ? "正在加载失败记录…" : "当前没有这类失败记录，可以切回「全部失败原因」查看，或稍后刷新。"}</p>}
      </div>
      <TablePager page={page} total={total} pageSize={WORKBENCH_PAGE_SIZE} loading={loading} onChange={setPage}/>
    </Panel>
    <Panel className="knowledge-list-panel">
      <div className="panel-heading list-heading">
        <div><h3>按执行编号查完整链路</h3><p>从监测到发布，一次执行经过了哪些环节；只查当前项目。</p></div>
        <Badge tone={trace?.found ? "green" : trace ? "amber" : "slate"}>{trace ? (trace.found ? "已找到" : "未找到") : "未查询"}</Badge>
      </div>
      <div className="table-toolbar">
        <div className="toolbar-left"><label className="search-field"><input aria-label="执行编号" placeholder="输入执行编号（32 位字符）" value={traceId} onChange={(event) => setTraceId(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadTrace(); }}/></label></div>
        <div className="toolbar-extra"><Button variant="secondary" icon="search" disabled={traceLoading} onClick={() => void loadTrace()}>{traceLoading ? "查询中…" : "查询链路"}</Button></div>
      </div>
      {traceError && <p className="form-error" role="alert">{traceError}</p>}
      {trace?.found && <>
        <p className="stats-excluded">本次执行包含：轮次 {trace.counts.rounds} · 任务 {trace.counts.tasks} · 回答 {trace.counts.samples} · 引用 {trace.counts.citations} · 内容版本 {trace.counts.content_versions} · 发布任务 {trace.counts.publish_tasks}</p>
        <div className="trace-chain-grid">
          <section><h4>监测轮次与任务</h4>{trace.tasks.map((task) => <div key={task.id} className="trace-node"><strong>{task.question_title || task.question_code || "未命名问题"}</strong><small>{task.engine_name} · {task.entry_name} · {labelOf(taskStatusLabels, task.status)}</small><code>任务 #{formatSerialNo(task.serial_no)} · v{task.version_no}</code></div>)}{!trace.tasks.length && <p className="knowledge-empty">没有任务记录</p>}</section>
          <section><h4>回答记录</h4>{trace.samples.map((sample) => <div key={sample.id} className="trace-node"><strong>{labelOf(sampleStatusLabels, sample.status)} · {sample.brand_mentioned ? "提及品牌" : "未提及品牌"}</strong><small>{sample.failure_code ? labelOf(failureLabels, sample.failure_code) : "没有失败原因"} · {sample.latency_ms == null ? "无耗时" : `${sample.latency_ms} ms`} · {sample.total_tokens == null ? "无 Token" : `${sample.total_tokens} Token`}</small><code>回答 #{formatSerialNo(sample.serial_no)} · 第 {sample.attempt_no} 次尝试</code></div>)}{!trace.samples.length && <p className="knowledge-empty">没有回答记录</p>}</section>
          <section><h4>引用来源</h4>{trace.citations.map((citation) => <div key={citation.id} className="trace-node"><strong>{citation.domain || "未记录来源"}</strong>{(citation.site_name || citation.title) && <small>{citation.site_name || "未知站点"}{citation.title ? ` · ${citation.title}` : ""}</small>}<small>{citation.is_brand_related ? "品牌相关" : "非品牌"} · {labelOf(citationUsageLabels, citation.citation_usage, "未标注使用方式")} · {labelOf(citationStatusLabels, citation.review_status, "未复核")}</small><code title={citation.raw_url}>{citation.raw_url}</code></div>)}{!trace.citations.length && <p className="knowledge-empty">没有引用记录</p>}</section>
          <section><h4>内容与发布</h4>{trace.content_versions.map((version) => <div key={version.id} className="trace-node"><strong>{version.item_title} · v{version.version_no}</strong><small>内容状态：{labelOf(contentStatusLabels, version.status)} · {version.content_hash.slice(0, 12)}…</small><code>内容版本 v{version.version_no}</code></div>)}{trace.publish_tasks.map((task) => <div key={task.id} className="trace-node"><strong>{task.channel_name || "未知渠道"} · {labelOf(publishModeLabels, task.publish_mode)}</strong><small>{task.account_name || "未绑定账号"} · {labelOf(taskStatusLabels, task.status)}</small><code>发布任务 #{formatSerialNo(task.serial_no)}</code></div>)}{!trace.content_versions.length && !trace.publish_tasks.length && <p className="knowledge-empty">没有内容或发布记录</p>}</section>
        </div>
      </>}
      {trace && !trace.found && <p className="knowledge-empty">这个执行编号在当前项目下没有查到任务、回答、引用或发布记录，请核对编号后重试。</p>}
    </Panel>
    {isSystemAdmin && <Panel className="knowledge-editor-panel">
      <div className="panel-heading"><div><h3>解除登录限制</h3><p>同一账号从同一来源频繁尝试登录会被暂时拦住；确认是本人后，可在这里立即恢复。</p></div><Icon name="lock" size={18}/></div>
      <form onSubmit={submitUnlock}>
        <label className="field"><span className="field-label">账号 *</span><input className="text-input" value={unlockName} maxLength={64} placeholder="例如：运营编辑" onChange={(event) => setUnlockName(event.target.value)}/></label>
        <label className="field"><span className="field-label">来源 IP（可留空）</span><input className="text-input" value={unlockIp} maxLength={64} placeholder="例如：203.0.113.7；留空会解除该账号所有来源的限制" onChange={(event) => setUnlockIp(event.target.value)}/></label>
        <div className="knowledge-actions"><Button type="submit" disabled={unlockBusy}>{unlockBusy ? "处理中…" : "解除登录限制"}</Button></div>
      </form>
      {unlockNotice && <p className="knowledge-footnote">{unlockNotice}</p>}
      {unlockError && <p className="form-error" role="alert">{unlockError}</p>}
    </Panel>}
  </div>;
}
