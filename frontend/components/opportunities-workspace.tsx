"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, DetailModal, Panel } from "./ui";
import { DataPager } from "./data-pager";
import { DataTable } from "./data-table";
import { workbenchClient } from "@/lib/workbench/client";
import type { OpportunityRecord, OpportunitySuggestionRecord } from "@/lib/workbench/types";

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
const ruleLabels: Record<string, string> = {
  brand_absent: "品牌缺席", competitor_outrank: "竞品反超", source_gap: "信源缺口",
  fact_error: "事实错误", stale_content: "内容过期",
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
  const [suggestions, setSuggestions] = useState<OpportunitySuggestionRecord[]>([]);
  const [suggestionMessage, setSuggestionMessage] = useState("");
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [gapFilter, setGapFilter] = useState("");
  const [title, setTitle] = useState("");
  const [gapType, setGapType] = useState("own_page");
  const [factors, setFactors] = useState<Record<string, number>>(defaultFactors);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const result = await workbenchClient.opportunities(projectId, page, { status: statusFilter || undefined, gap_type: gapFilter || undefined });
    setRows(result.data); setTotal(result.meta?.total ?? result.data.length);
  }, [projectId, page, statusFilter, gapFilter]);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.opportunitySuggestions(projectId, { status: "suggested" })
      .then((result) => { if (active) setSuggestions(result.data); })
      .catch(() => { if (active) setSuggestions([]); });
    return () => { active = false; };
  }, [mode, projectId, canRead]);

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

  async function generateSuggestions() {
    setBusy(true);
    try {
      const result = await workbenchClient.generateOpportunitySuggestions(projectId);
      setSuggestionMessage(`新增 ${result.created} 条、刷新 ${result.updated} 条、保留已处理 ${result.skipped} 条`);
      const latest = await workbenchClient.opportunitySuggestions(projectId, { status: "suggested" });
      setSuggestions(latest.data);
      onNotice("机会建议已按五条规则重算，仍需人工采纳");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "机会建议生成失败"); }
    finally { setBusy(false); }
  }

  async function reviewSuggestion(row: OpportunitySuggestionRecord, action: "accept" | "dismiss") {
    setBusy(true);
    try {
      const result = await workbenchClient.reviewOpportunitySuggestion(projectId, row.id, action);
      setSuggestions((current) => current.filter((item) => item.id !== row.id));
      if (action === "accept") {
        setRows((current) => [result as OpportunityRecord, ...current]);
        setTotal((current) => current + 1);
        onNotice("建议已采纳为机会，进入现有内容链路");
      } else {
        onNotice("建议已驳回，规则重跑不会恢复");
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "建议处理失败"); }
    finally { setBusy(false); }
  }

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
      setCreateOpen(false);
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
      <div className="panel-heading"><div><h3>规则机会建议</h3><p>品牌缺席、竞品反超、信源缺口、事实错误、内容过期；采纳后才创建机会</p></div><Badge tone="amber">{suggestions.length} 条待确认</Badge></div>
      {suggestionMessage && <p className="knowledge-footnote">{suggestionMessage}</p>}
      {canWrite && <div className="knowledge-actions"><Button variant="secondary" disabled={busy} onClick={() => void generateSuggestions()}>按五条规则重算</Button><span className="knowledge-footnote">重算只刷新未处理建议，不覆盖已采纳/已驳回。</span></div>}
      <DataTable columns={[
        { key: "rule", label: "规则建议", width: "34%", className: "col-title", render: (row) => <><strong title={row.title}>{ruleLabels[row.rule_code] ?? row.rule_code} · {row.title}</strong><small className="data-cell-note" title={row.description ?? ""}>{row.description ?? "—"}</small></> },
        { key: "score", label: "建议分", width: "10%", className: "data-cell-mono", render: (row) => row.score.toFixed(1) },
        { key: "severity", label: "等级", width: "10%", className: "col-status", render: (row) => <Badge tone="amber">{row.severity}</Badge> },
        { key: "evidence", label: "证据", width: "10%", className: "data-cell-mono", render: (row) => `${Object.keys(row.evidence ?? {}).length} 项` },
        { key: "actions", label: "操作", width: "26%", className: "data-cell-actions", render: (row) => canWrite
          ? <><Button disabled={busy} onClick={() => void reviewSuggestion(row, "accept")}>采纳</Button><Button variant="quiet" disabled={busy} onClick={() => void reviewSuggestion(row, "dismiss")}>驳回</Button></>
          : <Badge tone="amber">待确认</Badge> },
      ]} rows={suggestions} rowKey={(row) => row.id} empty={<p className="knowledge-empty">暂无待确认建议；可点“按五条规则重算”。</p>}/>
    </Panel>
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>机会列表</h3><p>共 {total} 条；按六因子加权分从高到低排序，优先处理高分缺口</p></div>{canWrite ? <Button icon="plus" onClick={() => setCreateOpen(true)}>新建机会</Button> : <Badge tone="blue">证据驱动</Badge>}</div>
      <div className="knowledge-actions">
        <label className="field"><span className="field-label">状态</span><select className="text-input" value={statusFilter} onChange={(e) => { setPage(1); setStatusFilter(e.target.value); }}><option value="">全部状态</option>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="field"><span className="field-label">缺口类型</span><select className="text-input" value={gapFilter} onChange={(e) => { setPage(1); setGapFilter(e.target.value); }}><option value="">全部类型</option>{Object.entries(gapTypeNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      </div>
      <DataTable columns={[
        { key: "title", label: "机会", width: "30%", className: "col-title", render: (row) => <><strong title={row.title}>{row.title}</strong><small className="data-cell-note">{gapTypeNames[row.gap_type] ?? row.gap_type} · {row.owner_name ?? "未指派"}</small></> },
        { key: "priority", label: "优先分", width: "12%", className: "data-cell-mono", render: (row) => row.priority_score.toFixed(2) },
        { key: "evidence", label: "证据", width: "10%", className: "data-cell-mono", render: (row) => `${row.evidence_refs.length} 条` },
        { key: "status", label: "状态", width: "20%", className: "col-status", render: (row) => canWrite
          ? <select className="text-input" aria-label={`更新 ${row.title} 状态`} value={row.status} disabled={busy} onChange={(e) => void updateStatus(row, e.target.value)}>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
          : <Badge tone={row.status === "done" ? "green" : row.status === "dismissed" ? "slate" : "amber"}>{statusNames[row.status] ?? row.status}</Badge> },
      ]} rows={rows} rowKey={(row) => row.id} empty={<p className="knowledge-empty">暂无机会</p>}/>
      <DataPager page={page} total={total} pageSize={20} onPage={(next) => setPage(next)}/>
    </Panel>
    {canWrite && createOpen && <DetailModal eyebrow="机会中心" title="新建机会" subtitle="六因子各 1–5 分；实施成本越高，最终优先分越低" onClose={() => setCreateOpen(false)}>
      <label className="field"><span className="field-label">机会标题</span><input className="text-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：补一篇课程对比页"/></label>
      <label className="field"><span className="field-label">缺口类型</span><select className="text-input" value={gapType} onChange={(e) => setGapType(e.target.value)}>{Object.entries(gapTypeNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <div className="knowledge-actions">{Object.entries(factorLabels).map(([key, label]) => <label className="field" key={key}><span className="field-label">{label}</span><select className="text-input" value={factors[key] ?? 3} onChange={(e) => setFactors((current) => ({ ...current, [key]: Number(e.target.value) }))}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>)}</div>
      <label className="field"><span className="field-label">备注</span><textarea className="text-input knowledge-textarea short" value={notes} onChange={(e) => setNotes(e.target.value)}/></label>
      <div className="knowledge-actions"><Button disabled={busy || !title.trim()} onClick={() => void createOpportunity()}>创建机会</Button><span className="knowledge-footnote">创建只落机会，不会自动生成内容或发布。</span></div>
    </DetailModal>}
  </div>;
}

