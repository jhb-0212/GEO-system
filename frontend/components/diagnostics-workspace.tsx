"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { DiagnosticSample } from "@/lib/workbench/types";

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

export function DiagnosticsWorkspace({ mode, projectId, canRead }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean;
}) {
  const [rows, setRows] = useState<DiagnosticSample[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [failureCode, setFailureCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await workbenchClient.diagnostics(projectId, page, failureCode || undefined);
      setRows(result.data); setTotal(result.meta?.total ?? result.data.length); setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "排障数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [projectId, page, failureCode]);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.diagnostics(projectId, page, failureCode || undefined)
      .then((result) => {
        if (!active) return;
        setRows(result.data); setTotal(result.meta?.total ?? result.data.length); setError("");
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : "排障数据加载失败");
      });
    return () => { active = false; };
  }, [mode, canRead, projectId, page, failureCode]);

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
            <select aria-label="筛选失败码" value={failureCode} onChange={(event) => { setFailureCode(event.target.value); setPage(1); }}>
              <option value="">全部失败码</option>
              {Object.entries(failureLabels).map(([code, label]) => <option key={code} value={code}>{label} · {code}</option>)}
            </select>
          </div>
        </div>
        <div className="toolbar-extra"><Button variant="secondary" icon="refresh" disabled={loading} onClick={() => void load()}>{loading ? "加载中…" : "刷新"}</Button></div>
      </div>
      <div className="table-scroll">
        <table>
          <thead><tr><th>样本 / 任务</th><th>问题 / 引擎</th><th>失败码</th><th>重试</th><th>耗时</th><th>Token</th><th>完成时间</th><th>trace_id</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.sample_id}>
            <td><strong className="table-title">{row.sample_id.slice(0, 8)}</strong><small className="table-sub">{row.task_status} · {row.task_id.slice(0, 8)}</small></td>
            <td><strong className="table-title">{row.question_title || "—"}</strong><small className="table-sub">{row.engine_name || row.engine_code || "—"} · {row.question_code || "—"}</small></td>
            <td><Badge tone={toneForFailure(row.failure_code)} dot>{row.failure_code ? (failureLabels[row.failure_code] || row.failure_code) : "未记录"}</Badge>{row.failure_note && <small className="table-sub">{row.failure_note}</small>}</td>
            <td>{row.retry_count > 0 ? `${row.retry_count} 次` : "首次"}<small className="table-sub">attempt {row.attempt_no}</small></td>
            <td>{row.latency_ms == null ? "—" : `${row.latency_ms} ms`}</td>
            <td>{row.total_tokens == null ? "—" : row.total_tokens.toLocaleString()}</td>
            <td>{row.finished_at ? new Date(row.finished_at).toLocaleString("zh-CN") : "—"}</td>
            <td><code title={row.trace_id || "无 trace"}>{row.trace_id ? `${row.trace_id.slice(0, 12)}…` : "—"}</code></td>
          </tr>)}</tbody>
        </table>
        {!rows.length && <p className="knowledge-empty">当前筛选下没有失败样本</p>}
      </div>
      <div className="table-footer">
        <span>显示 {rows.length} 条 / 共 {total} 条</span>
        <span className="knowledge-panel-foot">
          <Button variant="secondary" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)}>上一页</Button>
          <span>{page} / {Math.max(1, Math.ceil(total / 20))}</span>
          <Button variant="secondary" disabled={page * 20 >= total || loading} onClick={() => setPage(page + 1)}>下一页</Button>
        </span>
      </div>
    </Panel>
  </div>;
}
