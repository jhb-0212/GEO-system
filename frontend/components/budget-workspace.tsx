"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { BudgetApproval, BudgetCategory } from "@/lib/workbench/types";

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
  title: "",
  quantity: "",
  unit: "",
  unit_price: "",
  amount: "",
  currency: "CNY",
  note: "",
});

export function BudgetWorkspace({ mode, projectId, canRead, canWrite, canApprove, onNotice }: {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
  canWrite: boolean;
  canApprove: boolean;
  onNotice: (message: string) => void;
}) {
  const [items, setItems] = useState<BudgetApproval[]>([]);
  const [loadedProjectId, setLoadedProjectId] = useState("");
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.budgetApprovals(projectId).then((result) => {
      if (active) { setItems(result.data); setError(""); }
    }).catch((cause) => {
      if (active) { setItems([]); setError(cause instanceof Error ? cause.message : "预算申请加载失败"); }
    }).finally(() => { if (active) setLoadedProjectId(projectId); });
    return () => { active = false; };
  }, [mode, canRead, projectId, version]);

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
    setSaving(true);
    try {
      await workbenchClient.createBudgetApproval(projectId, {
        category: draft.category,
        title: draft.title.trim(),
        quantity,
        unit: draft.unit.trim() || null,
        unit_price: unitPrice,
        amount,
        currency: draft.currency.trim() || "CNY",
        note: draft.note.trim() || null,
      });
      setDraft(null);
      setVersion((value) => value + 1);
      onNotice("预算申请已提交，等待审批");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "提交失败");
    } finally {
      setSaving(false);
    }
  }

  async function review(item: BudgetApproval, decision: "approved" | "rejected") {
    if (!canApprove) return;
    let note: string | undefined;
    if (decision === "rejected") {
      const reason = window.prompt("请填写驳回原因");
      if (!reason?.trim()) return;
      note = reason.trim();
    }
    try {
      const updated = await workbenchClient.reviewBudgetApproval(projectId, item.id, decision, note);
      setItems((rows) => rows.map((row) => row.id === item.id ? updated : row));
      onNotice(decision === "approved" ? "预算申请已通过" : "预算申请已驳回");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "审批失败");
    }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">预算审批仅在真实接口模式显示。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有预算查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  const loading = loadedProjectId !== projectId;
  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>四类预算审批</h3><p>共 {items.length} 条申请 · 开发工时 / 内容制作 / 媒体投放 / 监测服务分别确认</p></div>{canWrite && <Button icon="plus" onClick={() => setDraft(blank())}>新增申请</Button>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="knowledge-list">
        {items.map((item) => <div className="knowledge-item" key={item.id}>
          <span>
            <strong>{item.title}</strong>
            <small>{categoryLabels[item.category]} · {item.quantity !== null ? `${item.quantity}${item.unit || ""} × ${item.unit_price ?? "—"}` : "按总额"} = {item.amount} {item.currency}</small>
            <small>{item.requested_by_name || "未知申请人"} 提交{item.approved_by_name ? ` · ${item.approved_by_name} 审批` : ""}</small>
            {item.note && <small>申请备注：{item.note}</small>}
            {item.decision_note && <small>审批意见：{item.decision_note}</small>}
          </span>
          <span className="knowledge-actions">
            <Badge tone={toneOf(item.status)}>{statusLabels[item.status] ?? item.status}</Badge>
            {canApprove && item.status === "pending" && <><Button onClick={() => void review(item, "approved")}>通过</Button><Button variant="secondary" onClick={() => void review(item, "rejected")}>驳回</Button></>}
          </span>
        </div>)}
        {loading && !items.length && <p className="knowledge-empty">正在加载预算申请…</p>}
        {!loading && !items.length && !error && <p className="knowledge-empty">当前项目暂无预算申请。</p>}
      </div>
    </Panel>
    {draft && <Panel className="knowledge-editor-panel">
      <div className="panel-heading"><div><h3>新增预算申请</h3><p>按费用类别分别提交；有数量和单价时金额自动计算</p></div><Icon name="folder" size={18}/></div>
      <form onSubmit={save}>
        <label className="field"><span className="field-label">费用类别</span><select className="text-input" value={draft.category} required disabled={saving} onChange={(event) => setDraft({ ...draft, category: event.target.value as BudgetCategory })}>{Object.entries(categoryLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <label className="field"><span className="field-label">费用事项</span><input className="text-input" value={draft.title} required maxLength={255} disabled={saving} onChange={(event) => setDraft({ ...draft, title: event.target.value })}/></label>
        <label className="field"><span className="field-label">数量（可选）</span><input type="number" min="0.01" step="0.01" className="text-input" value={draft.quantity} disabled={saving} onChange={(event) => setDraft({ ...draft, quantity: event.target.value })}/></label>
        <label className="field"><span className="field-label">单位（可选）</span><input className="text-input" value={draft.unit} maxLength={32} placeholder="人时 / 篇 / 次" disabled={saving} onChange={(event) => setDraft({ ...draft, unit: event.target.value })}/></label>
        <label className="field"><span className="field-label">单价（可选）</span><input type="number" min="0" step="0.01" className="text-input" value={draft.unit_price} disabled={saving} onChange={(event) => setDraft({ ...draft, unit_price: event.target.value })}/></label>
        <label className="field"><span className="field-label">金额</span><input type="number" min="0.01" step="0.01" className="text-input" value={draft.amount} disabled={saving || (draft.quantity !== "" && draft.unit_price !== "")} onChange={(event) => setDraft({ ...draft, amount: event.target.value })}/></label>
        <label className="field"><span className="field-label">币种</span><input className="text-input" value={draft.currency} maxLength={8} disabled={saving} onChange={(event) => setDraft({ ...draft, currency: event.target.value })}/></label>
        <label className="field"><span className="field-label">申请备注</span><textarea className="text-input knowledge-textarea short" value={draft.note} maxLength={5000} disabled={saving} onChange={(event) => setDraft({ ...draft, note: event.target.value })}/></label>
        <div className="knowledge-actions"><Button type="submit" disabled={saving}>{saving ? "提交中…" : "提交申请"}</Button><Button variant="secondary" onClick={() => setDraft(null)}>取消</Button></div>
      </form>
    </Panel>}
  </div>;
}
