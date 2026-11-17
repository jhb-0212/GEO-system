"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { ChannelRecord, PlanRecord, QuoteRecord } from "@/lib/workbench/types";

const statusLabels: Record<string, string> = { pending: "待审批", approved: "已通过", rejected: "已驳回" };
const toneOf = (status: string) => status === "approved" ? "green" as const : status === "rejected" ? "red" as const : "amber" as const;

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

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">媒体报价仅在真实接口模式显示。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有内容/报价查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;
  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>媒体报价与预算</h3><p>共 {items.length} 条报价 · 预算 = 单价 × 数量，通过后计入投放成本</p></div>{canWrite && <Button icon="plus" onClick={() => setDraft(blank())}>新增报价</Button>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="knowledge-list">
        {items.map((quote) => <div className="knowledge-item" key={quote.id}>
          <span><strong>{quote.plan_title || "未关联计划"}</strong><small>{quote.channel_name || "未指定渠道"} · {quote.unit_price} × {quote.quantity} = {quote.budget} {quote.currency}</small>{quote.note && <small>{quote.note}</small>}</span>
          <span className="knowledge-actions">
            <Badge tone={toneOf(quote.status)}>{statusLabels[quote.status] ?? quote.status}</Badge>
            {canReview && quote.status === "pending" && <><Button onClick={() => void review(quote, "approved")}>通过</Button><Button variant="secondary" onClick={() => void review(quote, "rejected")}>驳回</Button></>}
          </span>
        </div>)}
        {loading && !items.length && <p className="knowledge-empty">正在加载报价…</p>}
        {!loading && !items.length && !error && <p className="knowledge-empty">当前项目暂无报价。</p>}
      </div>
    </Panel>
    {draft && <Panel className="knowledge-editor-panel">
      <div className="panel-heading"><div><h3>新增报价</h3><p>必须关联一条内容计划；审核通过后生效</p></div><Icon name="folder" size={18}/></div>
      <form onSubmit={save}>
        <label className="field"><span className="field-label">关联计划</span><select className="text-input" value={draft.plan_id} required disabled={saving} onChange={(event) => setDraft({ ...draft, plan_id: event.target.value })}><option value="">选择计划</option>{plans.map((plan) => <option value={plan.id} key={plan.id}>{plan.title}</option>)}</select></label>
        <label className="field"><span className="field-label">投放渠道（可选）</span><select className="text-input" value={draft.channel_id} disabled={saving} onChange={(event) => setDraft({ ...draft, channel_id: event.target.value })}><option value="">不指定</option>{channels.map((channel) => <option value={channel.id} key={channel.id}>{channel.name}</option>)}</select></label>
        <label className="field"><span className="field-label">单价</span><input type="number" min="0.01" step="0.01" className="text-input" value={draft.unit_price} required disabled={saving} onChange={(event) => setDraft({ ...draft, unit_price: event.target.value })}/></label>
        <label className="field"><span className="field-label">数量</span><input type="number" min="1" step="1" className="text-input" value={draft.quantity} disabled={saving} onChange={(event) => setDraft({ ...draft, quantity: event.target.value })}/></label>
        <label className="field"><span className="field-label">币种</span><input className="text-input" value={draft.currency} maxLength={8} disabled={saving} onChange={(event) => setDraft({ ...draft, currency: event.target.value })}/></label>
        <label className="field"><span className="field-label">备注</span><textarea className="text-input knowledge-textarea short" value={draft.note} maxLength={5000} disabled={saving} onChange={(event) => setDraft({ ...draft, note: event.target.value })}/></label>
        <div className="knowledge-actions"><Button type="submit" disabled={saving}>{saving ? "提交中…" : "提交报价"}</Button><Button variant="secondary" onClick={() => setDraft(null)}>取消</Button></div>
      </form>
    </Panel>}
  </div>;
}
