"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { BudgetApproval, BudgetCategory, PublishReceiptRecord, QuoteRecord } from "@/lib/workbench/types";

const categoryLabels: Record<BudgetCategory, string> = {
  development_hours: "开发工时",
  content_production: "内容制作",
  media_placement: "媒体投放",
  monitoring_service: "监测服务",
};
const statusLabels: Record<string, string> = { pending: "待审批", approved: "已通过", rejected: "已驳回" };
const toneOf = (status: string) => status === "approved" ? "green" as const : status === "rejected" ? "red" as const : "amber" as const;

interface Draft {
  category: BudgetCategory;
  media_quote_id: string;
  title: string;
  quantity: string;
  unit: string;
  unit_price: string;
  amount: string;
  currency: string;
  note: string;
}
const blank = (): Draft => ({
  category: "development_hours",
  media_quote_id: "",
  title: "",
  quantity: "",
  unit: "",
  unit_price: "",
  amount: "",
  currency: "CNY",
  note: "",
});

export function BudgetWorkspace({ mode, projectId, currentUserId, canRead, canWrite, canApprove, onNotice }: {
  mode: "mock" | "live";
  projectId: string;
  currentUserId?: string;
  canRead: boolean;
  canWrite: boolean;
  canApprove: boolean;
  onNotice: (message: string) => void;
}) {
  const [items, setItems] = useState<BudgetApproval[]>([]);
  const [quotes, setQuotes] = useState<QuoteRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loadedKey, setLoadedKey] = useState("");
  const [error, setError] = useState("");
  const [submitError, setSubmitError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [approveTarget, setApproveTarget] = useState<BudgetApproval | null>(null);
  const [rejectTarget, setRejectTarget] = useState<BudgetApproval | null>(null);
  const [rejectNote, setRejectNote] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [detail, setDetail] = useState<BudgetApproval | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [receiptCandidates, setReceiptCandidates] = useState<PublishReceiptRecord[]>([]);
  const [selectedReceiptId, setSelectedReceiptId] = useState("");
  const [linking, setLinking] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.budgetApprovals(projectId, page).then((result) => {
      if (active) { setItems(result.data); setTotal(result.meta?.total ?? result.data.length); setError(""); }
    }).catch((cause) => {
      if (active) { setItems([]); setTotal(0); setError(cause instanceof Error ? cause.message : "预算申请加载失败"); }
    }).finally(() => { if (active) setLoadedKey(`${projectId}:${page}`); });
    return () => { active = false; };
  }, [mode, canRead, projectId, page, version]);

  useEffect(() => {
    if (mode !== "live" || !canWrite || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.quotes(projectId).then((result) => {
      if (active) setQuotes(result.data.filter((quote) => quote.status === "approved"));
    }).catch(() => { if (active) setQuotes([]); });
    return () => { active = false; };
  }, [mode, canWrite, projectId]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || !canWrite) return;
    const quantity = draft.quantity.trim() ? Number(draft.quantity) : null;
    const unitPrice = draft.unit_price.trim() ? Number(draft.unit_price) : null;
    let amount = draft.amount.trim() ? Number(draft.amount) : null;
    if (quantity !== null && unitPrice !== null) amount = Number((quantity * unitPrice).toFixed(2));
    if (amount === null || !Number.isFinite(amount) || amount <= 0) {
      onNotice("金额必须大于 0；填写数量和单价时会自动计算");
      return;
    }
    if (!draft.title.trim()) { onNotice("请填写费用事项"); return; }
    if (draft.category === "media_placement" && !draft.media_quote_id) {
      onNotice("媒体投放预算必须先选择一条已批准的媒体报价");
      return;
    }
    setSaving(true);
    setSubmitError("");
    try {
      await workbenchClient.createBudgetApproval(projectId, {
        category: draft.category,
        media_quote_id: draft.category === "media_placement" ? draft.media_quote_id : null,
        title: draft.title.trim(),
        quantity,
        unit: draft.unit.trim() || null,
        unit_price: unitPrice,
        amount,
        currency: draft.currency.trim() || "CNY",
        note: draft.note.trim() || null,
      });
      setDraft(null);
      setSubmitError("");
      setPage(1);
      setVersion((value) => value + 1);
      onNotice("预算申请已提交，等待审批");
    } catch (cause) {
      setSubmitError(cause instanceof Error ? cause.message : "提交失败");
    } finally {
      setSaving(false);
    }
  }

  async function confirmApprove() {
    if (!approveTarget || !canApprove || reviewing) return;
    setReviewing(true);
    try {
      const updated = await workbenchClient.reviewBudgetApproval(projectId, approveTarget.id, "approved", undefined);
      setItems((rows) => rows.map((row) => row.id === approveTarget.id ? updated : row));
      onNotice("预算申请已通过");
      setApproveTarget(null);
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "审批失败");
    } finally {
      setReviewing(false);
    }
  }

  async function submitReject() {
    if (!rejectTarget || !canApprove || reviewing) return;
    const note = rejectNote.trim();
    if (!note) { onNotice("请填写驳回原因"); return; }
    setReviewing(true);
    try {
      const updated = await workbenchClient.reviewBudgetApproval(projectId, rejectTarget.id, "rejected", note);
      setItems((rows) => rows.map((row) => row.id === rejectTarget.id ? updated : row));
      onNotice("预算申请已驳回");
      setRejectTarget(null);
      setRejectNote("");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "审批失败");
    } finally {
      setReviewing(false);
    }
  }

  async function loadReceiptCandidates(record: BudgetApproval) {
    const channelId = record.media_quote?.channel_id;
    if (!channelId) { setReceiptCandidates([]); return; }
    try {
      const result = await workbenchClient.publishReceipts(projectId, 1, { has_budget: false, channel_id: channelId });
      setReceiptCandidates(result.data.filter((receipt) => !/example\.com($|\/)/i.test(receipt.published_url)));
    } catch {
      setReceiptCandidates([]);
    }
  }

  async function openDetail(item: BudgetApproval) {
    setDetail(item);
    setDetailError("");
    setDetailLoading(true);
    setSelectedReceiptId("");
    setReceiptCandidates([]);
    try {
      const record = await workbenchClient.budgetApproval(projectId, item.id);
      setDetail(record);
      await loadReceiptCandidates(record);
    } catch (cause) {
      setDetailError(cause instanceof Error ? cause.message : "预算详情加载失败");
    } finally {
      setDetailLoading(false);
    }
  }

  async function linkReceipt() {
    if (!detail || !selectedReceiptId || linking) return;
    setLinking(true);
    setDetailError("");
    try {
      await workbenchClient.linkBudgetReceipt(projectId, detail.id, selectedReceiptId);
      const record = await workbenchClient.budgetApproval(projectId, detail.id);
      setDetail(record);
      await loadReceiptCandidates(record);
      setSelectedReceiptId("");
      setVersion((value) => value + 1);
      onNotice("回执已挂到预算");
    } catch (cause) {
      setDetailError(cause instanceof Error ? cause.message : "挂接回执失败");
    } finally {
      setLinking(false);
    }
  }

  async function unlinkReceipt(receiptId: string) {
    if (!detail || linking) return;
    setLinking(true);
    setDetailError("");
    try {
      await workbenchClient.unlinkBudgetReceipt(projectId, detail.id, receiptId);
      const record = await workbenchClient.budgetApproval(projectId, detail.id);
      setDetail(record);
      await loadReceiptCandidates(record);
      setVersion((value) => value + 1);
      onNotice("回执已解绑，不会删除回执");
    } catch (cause) {
      setDetailError(cause instanceof Error ? cause.message : "解绑回执失败");
    } finally {
      setLinking(false);
    }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">预算审批仅在真实接口模式显示。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有预算查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  const loading = loadedKey !== `${projectId}:${page}`;
  const canLinkReceipt = canWrite || canApprove;
  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>四类预算审批</h3><p>共 {total} 条申请 · 开发工时 / 内容制作 / 媒体投放 / 监测服务分别确认</p></div>{canWrite && <Button icon="plus" onClick={() => { setSubmitError(""); setDraft(blank()); }}>新增申请</Button>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="knowledge-list">
        {items.map((item) => <div className="knowledge-item" key={item.id}>
          <span>
            <strong>{item.title}</strong>
            <small>{categoryLabels[item.category]} · {item.quantity !== null ? `${item.quantity}${item.unit || ""} × ${item.unit_price ?? "—"}` : "按总额"} = {item.amount} {item.currency}</small>
            {item.media_quote_channel_name && <small>报价渠道：{item.media_quote_channel_name} · 已挂回执 {item.linked_receipt_count ?? 0}/{item.quantity ?? 0} 篇{item.receipt_complete ? " · 已完成" : ""}</small>}
            <small>{item.requested_by_name || "未知申请人"} 提交{item.approved_by_name ? ` · ${item.approved_by_name} 审批` : ""}</small>
            {item.note && <small>申请备注：{item.note}</small>}
            {item.decision_note && <small>审批意见：{item.decision_note}</small>}
          </span>
          <span className="knowledge-actions">
            <Badge tone={toneOf(item.status)}>{statusLabels[item.status] ?? item.status}</Badge>
            <Button variant="secondary" onClick={() => void openDetail(item)}>{item.category === "media_placement" ? "详情/挂回执" : "详情"}</Button>
            {canApprove && item.status === "pending" && item.requested_by === currentUserId && <small>本人提交，需他人审批</small>}
            {canApprove && item.status === "pending" && item.requested_by !== currentUserId && <><Button onClick={() => setApproveTarget(item)}>通过</Button><Button variant="secondary" onClick={() => { setRejectTarget(item); setRejectNote(""); }}>驳回</Button></>}
          </span>
        </div>)}
        {loading && !items.length && <p className="knowledge-empty">正在加载预算申请…</p>}
        {!loading && !items.length && !error && <p className="knowledge-empty">当前项目暂无预算申请。</p>}
      </div>
      {total > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><span>{page} / {Math.ceil(total / 20)}</span><Button variant="secondary" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>下一页</Button></div>}
    </Panel>

    {draft && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) { setSubmitError(""); setDraft(null); } }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="budget-new-title" style={{ maxHeight: "88vh", overflowY: "auto" }}>
        <div className="modal-header"><div><p className="eyebrow">BUDGET REQUEST</p><h2 id="budget-new-title">新增预算申请</h2></div><button className="icon-button" aria-label="关闭" disabled={saving} onClick={() => { setSubmitError(""); setDraft(null); }}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">按费用类别分别提交；有数量和单价时金额自动计算。</p>
        <form onSubmit={save}>
          {submitError && <p className="form-error" role="alert">{submitError}</p>}
          <label className="field"><span className="field-label">费用类别</span><select className="text-input" value={draft.category} required disabled={saving} onChange={(event) => { const category = event.target.value as BudgetCategory; setDraft({ ...draft, category, media_quote_id: category === "media_placement" ? draft.media_quote_id : "" }); }}>{Object.entries(categoryLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          {draft.category === "media_placement" && <label className="field"><span className="field-label">已批准媒体报价 *</span><select className="text-input" value={draft.media_quote_id} required disabled={saving} onChange={(event) => { const quote = quotes.find((row) => row.id === event.target.value); if (!quote) { setDraft({ ...draft, media_quote_id: "" }); return; } setDraft({ ...draft, media_quote_id: quote.id, quantity: String(quote.quantity), unit: "篇", unit_price: String(quote.unit_price), amount: String(quote.budget), currency: quote.currency }); }}><option value="">请选择已批准报价</option>{quotes.map((quote) => <option value={quote.id} key={quote.id}>{quote.channel_name || "未指定渠道"} · {quote.quantity} 篇 × {quote.unit_price} {quote.currency}</option>)}</select><small>媒体投放预算的单价、币种和金额会按报价带出，提交时由后端再次校验剩余篇数。</small></label>}
          <label className="field"><span className="field-label">费用事项</span><input className="text-input" value={draft.title} required maxLength={255} disabled={saving} onChange={(event) => setDraft({ ...draft, title: event.target.value })}/></label>
          <label className="field"><span className="field-label">数量（可选）</span><input type="number" min="0.01" step="0.01" className="text-input" value={draft.quantity} disabled={saving} onChange={(event) => setDraft({ ...draft, quantity: event.target.value })}/></label>
          <label className="field"><span className="field-label">单位（可选）</span><input className="text-input" value={draft.unit} maxLength={32} placeholder="人时 / 篇 / 次" disabled={saving} onChange={(event) => setDraft({ ...draft, unit: event.target.value })}/></label>
          <label className="field"><span className="field-label">单价（可选）</span><input type="number" min="0" step="0.01" className="text-input" value={draft.unit_price} disabled={saving} onChange={(event) => setDraft({ ...draft, unit_price: event.target.value })}/></label>
          <label className="field"><span className="field-label">金额</span><input type="number" min="0.01" step="0.01" className="text-input" value={draft.amount} disabled={saving || (draft.quantity !== "" && draft.unit_price !== "")} onChange={(event) => setDraft({ ...draft, amount: event.target.value })}/></label>
          <label className="field"><span className="field-label">币种</span><input className="text-input" value={draft.currency} maxLength={8} disabled={saving} onChange={(event) => setDraft({ ...draft, currency: event.target.value })}/></label>
          <label className="field"><span className="field-label">申请备注</span><textarea className="text-input knowledge-textarea short" value={draft.note} maxLength={5000} disabled={saving} onChange={(event) => setDraft({ ...draft, note: event.target.value })}/></label>
          <div className="modal-actions"><Button type="submit" disabled={saving}>{saving ? "提交中…" : "提交申请"}</Button><Button variant="secondary" disabled={saving} onClick={() => { setSubmitError(""); setDraft(null); }}>取消</Button></div>
        </form>
      </div>
    </div>}

    {detail && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !linking) setDetail(null); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="budget-detail-title" style={{ maxHeight: "88vh", overflowY: "auto" }}>
        <div className="modal-header"><div><p className="eyebrow">BUDGET DETAIL</p><h2 id="budget-detail-title">预算详情</h2></div><button className="icon-button" aria-label="关闭" disabled={linking} onClick={() => setDetail(null)}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">{detail.title} · {categoryLabels[detail.category]} · {detail.quantity !== null ? `${detail.quantity}${detail.unit || ""} × ${detail.unit_price ?? "—"}` : "按总额"} = {detail.amount} {detail.currency}</p>
        {detailError && <p className="form-error" role="alert">{detailError}</p>}
        {detailLoading && <p className="knowledge-empty">正在加载详情…</p>}
        <div className="knowledge-list">
          <div className="knowledge-item">
            <span>
              <strong>报价与回执进度</strong>
              <small>{detail.media_quote ? `${detail.media_quote.channel_name || "未指定渠道"} · ${detail.media_quote.quantity} 篇 × ${detail.media_quote.unit_price} ${detail.media_quote.currency} · 报价 ${detail.media_quote.status}` : "非媒体投放预算，不关联报价"}</small>
              <small>已挂回执 {detail.linked_receipt_count ?? 0}/{detail.quantity ?? 0} 篇 · 剩余 {detail.remaining_quantity ?? 0} 篇{detail.receipt_complete ? " · 已完成" : ""}</small>
              {detail.note && <small>申请备注：{detail.note}</small>}
              {detail.decision_note && <small>审批意见：{detail.decision_note}</small>}
            </span>
            <span className="knowledge-actions"><Badge tone={toneOf(detail.status)}>{statusLabels[detail.status] ?? detail.status}</Badge></span>
          </div>
        </div>
        <h3 style={{ marginTop: 18, marginBottom: 8 }}>已挂回执</h3>
        <div className="knowledge-list">
          {(detail.receipts ?? []).map((receipt) => <div className="knowledge-item" key={receipt.receipt_id}>
            <span>
              <strong><a href={receipt.published_url} target="_blank" rel="noreferrer">回执 {receipt.receipt_id.slice(0, 8)}</a></strong>
              <small style={{ wordBreak: "break-all" }}>{receipt.published_url}</small>
              <small>接收时间：{receipt.received_at}</small>
            </span>
            <span className="knowledge-actions">{canLinkReceipt && <Button variant="secondary" disabled={linking} onClick={() => void unlinkReceipt(receipt.receipt_id)}>解绑</Button>}</span>
          </div>)}
          {!(detail.receipts ?? []).length && <p className="knowledge-empty">该预算还没有挂回执。</p>}
        </div>
        {detail.category === "media_placement" && <div style={{ marginTop: 18 }}>
          <h3 style={{ marginBottom: 8 }}>挂一条回执</h3>
          {detail.status !== "approved" && <p className="knowledge-empty">预算审批通过后才能挂回执。</p>}
          {detail.status === "approved" && (detail.remaining_quantity ?? 0) <= 0 && <p className="knowledge-empty">该预算已挂满 {(detail.quantity ?? 0)} 篇，不能继续挂接。</p>}
          {detail.status === "approved" && (detail.remaining_quantity ?? 0) > 0 && canLinkReceipt && <>
            {receiptCandidates.length ? <><label className="field"><span className="field-label">同渠道、未挂预算的回执</span><select className="text-input" value={selectedReceiptId} disabled={linking} onChange={(event) => setSelectedReceiptId(event.target.value)}><option value="">请选择回执</option>{receiptCandidates.map((receipt) => <option value={receipt.id} key={receipt.id}>{receipt.serial_no} · {receipt.published_url.slice(0, 72)}</option>)}</select></label><div className="modal-actions" style={{ justifyContent: "flex-start" }}><Button disabled={!selectedReceiptId || linking} onClick={() => void linkReceipt()}>{linking ? "挂接中…" : "挂接回执"}</Button></div></> : <p className="knowledge-empty">当前没有同渠道、未挂预算且非 example.com 的回执。</p>}
          </>}
        </div>}
        <div className="modal-actions"><Button variant="secondary" disabled={linking} onClick={() => setDetail(null)}>关闭</Button></div>
      </div>
    </div>}

    {approveTarget && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !reviewing) setApproveTarget(null); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="budget-approve-title">
        <div className="modal-header"><div><p className="eyebrow">APPROVE</p><h2 id="budget-approve-title">审批通过</h2></div><button className="icon-button" aria-label="关闭" disabled={reviewing} onClick={() => setApproveTarget(null)}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">确认通过 <strong>{approveTarget.title}</strong>（{categoryLabels[approveTarget.category]} · {approveTarget.amount} {approveTarget.currency}）？通过后该预算申请即生效。</p>
        <div className="modal-actions"><Button variant="secondary" disabled={reviewing} onClick={() => setApproveTarget(null)}>取消</Button><Button disabled={reviewing} onClick={() => void confirmApprove()}>{reviewing ? "处理中…" : "确认通过"}</Button></div>
      </div>
    </div>}

    {rejectTarget && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !reviewing) { setRejectTarget(null); setRejectNote(""); } }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="budget-reject-title">
        <div className="modal-header"><div><p className="eyebrow">REJECT</p><h2 id="budget-reject-title">驳回申请</h2></div><button className="icon-button" aria-label="关闭" disabled={reviewing} onClick={() => { setRejectTarget(null); setRejectNote(""); }}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">驳回 <strong>{rejectTarget.title}</strong>，请填写驳回原因，会随审批意见一并展示。</p>
        <form onSubmit={(event) => { event.preventDefault(); void submitReject(); }}>
          <label className="field"><span className="field-label">驳回原因 *</span><textarea className="text-input knowledge-textarea short" value={rejectNote} required maxLength={2000} disabled={reviewing} onChange={(event) => setRejectNote(event.target.value)}/></label>
          <div className="modal-actions"><Button variant="secondary" disabled={reviewing} onClick={() => { setRejectTarget(null); setRejectNote(""); }}>取消</Button><Button type="submit" variant="danger" disabled={reviewing}>{reviewing ? "处理中…" : "确认驳回"}</Button></div>
        </form>
      </div>
    </div>}
  </div>;
}
