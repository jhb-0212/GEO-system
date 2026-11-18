"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { OpportunityRecord } from "@/lib/workbench/types";

const gapTypeNames: Record<string, string> = {
  own_page: "自有页面", media_report: "媒体报道", reference_site: "参考站点",
  ugc: "UGC", fact_correction: "事实纠错", website_fix: "网站修复",
};
const statusNames: Record<string, string> = {
  open: "待处理", in_progress: "进行中", done: "已完成", dismissed: "已忽略",
};
const factorLabels: Record<string, string> = {
  business_value: "业务目标重要度", competitor_gap: "竞品引用差距",
  material_readiness: "官方素材就绪度", implementation_cost: "实施成本",
  channel_authorization: "授权发布渠道", verifiability: "下一轮可验证性",
};

const defaultFactors: Record<string, number> = {
  business_value: 3, competitor_gap: 3, material_readiness: 3,
  implementation_cost: 3, channel_authorization: 3, verifiability: 3,
};

export function OpportunitiesWorkspace({ mode, projectId, canRead, canWrite, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean;
  onNotice: (message: string) => void;
}) {
  const [rows, setRows] = useState<OpportunityRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [gapFilter, setGapFilter] = useState("");
  const [title, setTitle] = useState("");
  const [gapType, setGapType] = useState("own_page");
  const [factors, setFactors] = useState<Record<string, number>>(defaultFactors);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const result = await workbenchClient.opportunities(projectId, page, { status: statusFilter || undefined, gap_type: gapFilter || undefined });
    setRows(result.data); setTotal(result.meta?.total ?? result.data.length);
  }, [projectId, page, statusFilter, gapFilter]);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.opportunities(projectId, page, { status: statusFilter || undefined, gap_type: gapFilter || undefined })
      .then((result) => {
        if (!active) return;
        setRows(result.data); setTotal(result.meta?.total ?? result.data.length); setError("");
      })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "机会加载失败"); });
    return () => { active = false; };
  }, [mode, projectId, canRead, page, statusFilter, gapFilter]);

  async function createOpportunity() {
    if (!title.trim()) return;
    setBusy(true);
    try {
      const created = await workbenchClient.saveOpportunity(projectId, {
        title: title.trim(), gap_type: gapType, score_factors: factors,
        ...(notes.trim() ? { notes: notes.trim() } : {}),
      });
      setRows((current) => [created, ...current]);
      setTotal((current) => current + 1);
      setTitle(""); setNotes(""); setFactors(defaultFactors);
      onNotice("机会已创建，优先分已按六因子计算");
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "机会创建失败"); }
    finally { setBusy(false); }
  }

  async function updateStatus(row: OpportunityRecord, status: string) {
    setBusy(true);
    try {
      const updated = await workbenchClient.saveOpportunity(projectId, { status }, row.id);
      setRows((current) => current.map((item) => item.id === updated.id ? updated : item));
      onNotice("机会状态已更新");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "机会状态更新失败"); }
    finally { setBusy(false); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">机会中心请切换到真实接口模式。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有内容读取权限。</p></Panel>;

  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>机会列表</h3><p>共 {total} 条；按六因子加权分从高到低排序，优先处理高分缺口</p></div><Badge tone="blue">证据驱动</Badge></div>
      <div className="knowledge-actions">
        <label className="field"><span className="field-label">状态</span><select className="text-input" value={statusFilter} onChange={(e) => { setPage(1); setStatusFilter(e.target.value); }}><option value="">全部状态</option>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="field"><span className="field-label">缺口类型</span><select className="text-input" value={gapFilter} onChange={(e) => { setPage(1); setGapFilter(e.target.value); }}><option value="">全部类型</option>{Object.entries(gapTypeNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      </div>
      <div className="knowledge-list">{rows.map((row) => <div className="knowledge-item" key={row.id}>
        <span><strong>{row.title}</strong><small>{gapTypeNames[row.gap_type] ?? row.gap_type} · 优先分 {row.priority_score.toFixed(2)} · {row.owner_name ?? "未指派"} · 证据 {row.evidence_refs.length} 条</small></span>
        {canWrite ? <select className="text-input" aria-label={`更新 ${row.title} 状态`} value={row.status} disabled={busy} onChange={(e) => void updateStatus(row, e.target.value)}>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select> : <Badge tone={row.status === "done" ? "green" : row.status === "dismissed" ? "slate" : "amber"}>{statusNames[row.status] ?? row.status}</Badge>}
      </div>)}{!rows.length && <p className="knowledge-empty">暂无机会</p>}</div>
      {total > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><span>{page} / {Math.ceil(total / 20)}</span><Button variant="secondary" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>下一页</Button></div>}
    </Panel>
    {canWrite && <Panel className="knowledge-editor-panel">
      <div className="panel-heading"><div><h3>新建机会</h3><p>六因子各 1–5 分；实施成本越高，最终优先分越低</p></div></div>
      <label className="field"><span className="field-label">机会标题</span><input className="text-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：补一篇课程对比页"/></label>
      <label className="field"><span className="field-label">缺口类型</span><select className="text-input" value={gapType} onChange={(e) => setGapType(e.target.value)}>{Object.entries(gapTypeNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <div className="knowledge-actions">{Object.entries(factorLabels).map(([key, label]) => <label className="field" key={key}><span className="field-label">{label}</span><select className="text-input" value={factors[key] ?? 3} onChange={(e) => setFactors((current) => ({ ...current, [key]: Number(e.target.value) }))}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>)}</div>
      <label className="field"><span className="field-label">备注</span><textarea className="text-input knowledge-textarea short" value={notes} onChange={(e) => setNotes(e.target.value)}/></label>
      <div className="knowledge-actions"><Button disabled={busy || !title.trim()} onClick={() => void createOpportunity()}>创建机会</Button><span className="knowledge-footnote">创建只落机会，不会自动生成内容或发布。</span></div>
    </Panel>}
  </div>;
}
