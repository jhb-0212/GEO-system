"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, DetailModal, Icon, Panel } from "./ui";
import { DataTable } from "./data-table";
import { workbenchClient } from "@/lib/workbench/client";
import type { ChannelRecord, PlanRecord, QuoteRecord } from "@/lib/workbench/types";

const statusLabels: Record<string, string> = { pending: "待审批", approved: "已通过", rejected: "已驳回", withdrawn: "已撤回" };
const toneOf = (status: string) => status === "approved" ? "green" as const : status === "rejected" ? "red" as const : status === "withdrawn" ? "slate" as const : "amber" as const;

interface Draft { plan_id: string; channel_id: string; unit_price: string; quantity: string; currency: string; note: string }
const blank = (): Draft => ({ plan_id: "", channel_id: "", unit_price: "", quantity: "1", currency: "CNY", note: "" });

export function QuotesWorkspace({ mode, projectId, canRead, canWrite, canReview, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean; canReview: boolean; onNotice: (message: string) => void;
}) {
  const [items, setItems] = useState<QuoteRecord[]>([]);
  const [plans, setPlans] = useState<PlanRecord[]>([]);
  const [channels, setChannels] = useState<ChannelRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [withdrawTarget, setWithdrawTarget] = useState<QuoteRecord | null>(null);
  const [withdrawBusy, setWithdrawBusy] = useState(false);
  const [withdrawError, setWithdrawError] = useState("");
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([
      workbenchClient.quotes(projectId),
      workbenchClient.plans(projectId).catch(() => ({ data: [] as PlanRecord[] })),
      workbenchClient.channels(projectId, 1, 100).catch(() => ({ data: [] as ChannelRecord[] })),
    ]).then(([quoteResult, planResult, channelResult]) => {
      if (active) { setItems(quoteResult.data); setPlans(planResult.data); setChannels(channelResult.data); setError(""); }
    }).catch((cause) => {
      if (active) { setItems([]); setError(cause instanceof Error ? cause.message : "报价加载失败"); }
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [mode, canRead, projectId, version]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || !canWrite) return;
    if (!draft.plan_id) { onNotice("请选择关联的内容计划"); return; }
    const unitPrice = Number(draft.unit_price);
    if (!Number.isFinite(unitPrice) || unitPrice <= 0) { onNotice("单价必须大于 0"); return; }
    setSaving(true);
    try {
      await workbenchClient.saveQuote(projectId, {
        plan_id: draft.plan_id,
        channel_id: draft.channel_id || null,
        unit_price: unitPrice,
        quantity: Number(draft.quantity) || 1,
        currency: draft.currency.trim() || "CNY",
        note: draft.note.trim() || null,
      });
      setDraft(null);
      setVersion((value) => value + 1);
      onNotice("报价已提交，等待审批");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "提交失败"); }
    finally { setSaving(false); }
  }

  async function review(quote: QuoteRecord, decision: "approved" | "rejected") {
    if (!canReview) return;
    try {
      await workbenchClient.reviewQuote(projectId, quote.id, decision);
      setItems((rows) => rows.map((row) => row.id === quote.id ? { ...row, status: decision, approved_at: new Date().toISOString() } : row));
      onNotice(decision === "approved" ? "报价已通过" : "报价已驳回");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "审批失败"); }
  }

  function askWithdraw(quote: QuoteRecord) {
    if (!canWrite && !canReview) return;
    setWithdrawError("");
    setWithdrawTarget(quote);
  }

  function closeWithdraw() {
    if (withdrawBusy) return;
    setWithdrawTarget(null);
    setWithdrawError("");
  }

  async function confirmWithdraw() {
    if (!withdrawTarget || withdrawBusy) return;
    setWithdrawBusy(true);
    setWithdrawError("");
    try {
      await workbenchClient.withdrawQuote(projectId, withdrawTarget.id);
      setItems((rows) => rows.map((row) => row.id === withdrawTarget.id ? { ...row, status: "withdrawn", approved_by: null, approved_by_name: null, approved_at: null } : row));
      setWithdrawTarget(null);
      onNotice("报价已撤回，记录保留");
    } catch (cause) {
      setWithdrawError(cause instanceof Error ? cause.message : "撤回失败");
    } finally {
      setWithdrawBusy(false);
    }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">媒体报价仅在真实接口模式显示。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有内容/报价查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;
  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>媒体报价与预算</h3><p>共 {items.length} 条报价 · 预算 = 单价 × 数量，通过后计入投放成本；待审批可撤回</p></div>{canWrite && <Button icon="plus" onClick={() => setDraft(blank())}>新增报价</Button>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <DataTable columns={[
        { key: "plan", label: "关联计划", width: "26%", className: "col-title", render: (quote) => <><strong title={quote.plan_title ?? ""}>{quote.plan_title || "未关联计划"}</strong><small className="data-cell-note">{quote.note ? (quote.note.length > 20 ? `${quote.note.slice(0, 20)}…` : quote.note) : "—"}</small></> },
        { key: "channel", label: "渠道", width: "16%", render: (quote) => quote.channel_name || "未指定" },
        { key: "calc", label: "单价 × 数量", width: "20%", className: "data-cell-mono", render: (quote) => `${quote.unit_price} × ${quote.quantity}` },
        { key: "budget", label: "预算", width: "16%", className: "col-budget", render: (quote) => <><strong className="data-cell-strong">{quote.budget}</strong><small className="data-cell-note">{quote.currency}</small></> },
        { key: "status", label: "状态", width: "10%", className: "col-status", render: (quote) => <Badge tone={toneOf(quote.status)}>{statusLabels[quote.status] ?? quote.status}</Badge> },
        { key: "actions", label: "操作", width: "22%", className: "data-cell-actions", render: (quote) => <>
          {canReview && quote.status === "pending" && <><Button onClick={() => void review(quote, "approved")}>通过</Button><Button variant="secondary" onClick={() => void review(quote, "rejected")}>驳回</Button></>}
          {(canWrite || canReview) && quote.status === "pending" && <Button variant="secondary" onClick={() => askWithdraw(quote)}>撤回</Button>}
          {quote.status !== "pending" && <small className="data-cell-note">已处理</small>}
        </> },
      ]} rows={items} rowKey={(quote) => quote.id} empty={<p className="knowledge-empty">{loading ? "正在加载报价…" : "当前项目暂无报价。"}</p>}/>
    </Panel>
    {draft && <DetailModal eyebrow="媒体报价" title="新增报价" subtitle="必须关联一条内容计划；审核通过后生效" onClose={() => { if (!saving) setDraft(null); }}>
      <form onSubmit={save}>
        <label className="field"><span className="field-label">关联计划</span><select className="text-input" value={draft.plan_id} required disabled={saving} onChange={(event) => setDraft({ ...draft, plan_id: event.target.value })}><option value="">选择计划</option>{plans.map((plan) => <option value={plan.id} key={plan.id}>{plan.title}</option>)}</select></label>
        <label className="field"><span className="field-label">投放渠道（可选）</span><select className="text-input" value={draft.channel_id} disabled={saving} onChange={(event) => setDraft({ ...draft, channel_id: event.target.value })}><option value="">不指定</option>{channels.map((channel) => <option value={channel.id} key={channel.id}>{channel.name}</option>)}</select></label>
        <label className="field"><span className="field-label">单价</span><input type="number" min="0.01" step="0.01" className="text-input" value={draft.unit_price} required disabled={saving} onChange={(event) => setDraft({ ...draft, unit_price: event.target.value })}/></label>
        <label className="field"><span className="field-label">数量</span><input type="number" min="1" step="1" className="text-input" value={draft.quantity} disabled={saving} onChange={(event) => setDraft({ ...draft, quantity: event.target.value })}/></label>
        <label className="field"><span className="field-label">币种</span><input className="text-input" value={draft.currency} maxLength={8} disabled={saving} onChange={(event) => setDraft({ ...draft, currency: event.target.value })}/></label>
        <label className="field"><span className="field-label">备注</span><textarea className="text-input knowledge-textarea short" value={draft.note} maxLength={5000} disabled={saving} onChange={(event) => setDraft({ ...draft, note: event.target.value })}/></label>
        <div className="knowledge-actions"><Button type="submit" disabled={saving}>{saving ? "提交中…" : "提交报价"}</Button><Button variant="secondary" onClick={() => setDraft(null)}>取消</Button></div>
      </form>
    </DetailModal>}
    {withdrawTarget && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !withdrawBusy) closeWithdraw(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="quote-withdraw-title">
        <div className="modal-header"><div><p className="eyebrow">WITHDRAW</p><h2 id="quote-withdraw-title">撤回报价</h2></div><button className="icon-button" aria-label="关闭" disabled={withdrawBusy} onClick={closeWithdraw}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">确定撤回「<strong>{withdrawTarget.plan_title || "未关联计划"}</strong>」这笔报价吗？</p>
        <p className="field-hint">撤回只对“待审批”报价生效，记录和审批历史都会保留，不会物理删除。已通过或已驳回的报价已锁定，不能撤回。</p>
        {withdrawError && <p className="form-error" role="alert">{withdrawError}</p>}
        <div className="modal-actions">
          <Button variant="secondary" disabled={withdrawBusy} onClick={closeWithdraw}>返回</Button>
          <Button variant="danger" disabled={withdrawBusy} onClick={() => void confirmWithdraw()}>{withdrawBusy ? "撤回中…" : "确认撤回"}</Button>
        </div>
      </div>
    </div>}
  </div>;
}
