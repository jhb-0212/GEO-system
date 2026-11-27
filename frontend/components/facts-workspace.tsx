"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, DetailModal, Panel } from "./ui";
import { WorkTabs } from "./work-tabs";
import { DataTable } from "./data-table";
import { workbenchClient } from "@/lib/workbench/client";
import { formatDateTime, formatSerialNo } from "@/lib/workbench/format";
import type { CorrectionTaskRecord, FactClaimRecord, FactPushRecord, FactRecord, FactTypeOption, FactVersionRecord } from "@/lib/workbench/types";

type FactTab = "library" | "claims";
const statusNames: Record<string, string> = {
  draft: "草稿", pending_review: "待审批", approved: "已批准", expired: "已过期",
};
const statusTone = (status: string): "green" | "amber" | "red" | "slate" => status === "approved" ? "green" : status === "pending_review" ? "amber" : status === "expired" ? "red" : "slate";
const verdictNames: Record<string, string> = {
  correct: "正确", wrong: "错误", expired: "过期", unconfirmed: "无法确认",
};
const actionNames: Record<string, string> = {
  created: "创建", revised: "修订", submitted: "提交审批", approved: "批准", rejected: "驳回", expired: "标记过期",
};

const emptyForm = {
  fact_type: "course_duration", fact_key: "", fact_value: "", source_document: "", source_url: "",
  owner: "", business_confirmed_note: "",
};

export function FactsWorkspace({ mode, projectId, canRead, canWrite, canReview, canReviewClaims, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean;
  canWrite: boolean; canReview: boolean; canReviewClaims: boolean;
  onNotice: (message: string) => void;
}) {
  const [activeTab, setActiveTab] = useState<FactTab>("library");
  const [types, setTypes] = useState<FactTypeOption[]>([]);
  const [facts, setFacts] = useState<FactRecord[]>([]);
  const [selected, setSelected] = useState<FactRecord | null>(null);
  const [versions, setVersions] = useState<FactVersionRecord[]>([]);
  const [claims, setClaims] = useState<FactClaimRecord[]>([]);
  const [correctionTasks, setCorrectionTasks] = useState<CorrectionTaskRecord[]>([]);
  const [selectedClaim, setSelectedClaim] = useState<FactClaimRecord | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [editForm, setEditForm] = useState({ fact_value: "", source_document: "", source_url: "", owner: "", change_note: "" });
  const [confirmNote, setConfirmNote] = useState("");
  const [businessConfirmed, setBusinessConfirmed] = useState(false);
  const [claimForm, setClaimForm] = useState({ sample_id: "", claim_text: "", fact_id: "", source_url: "" });
  const [verdict, setVerdict] = useState("wrong");
  const [verdictNote, setVerdictNote] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // 事实推送（G9）：只推已核准事实；百科方向只生成草稿词条，webhook 方向记录回执
  const [pushTarget, setPushTarget] = useState<"encyclopedia" | "webhook">("encyclopedia");
  const [pushRef, setPushRef] = useState("");
  const [pushes, setPushes] = useState<FactPushRecord[]>([]);
  const [pushBusy, setPushBusy] = useState(false);

  const loadFacts = useCallback(async () => {
    if (mode !== "live" || !projectId || projectId === "all") return;
    const result = await workbenchClient.facts(projectId, typeFilter || undefined);
    setFacts(result.data);
  }, [mode, projectId, typeFilter]);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([
      workbenchClient.factTypes(projectId),
      workbenchClient.facts(projectId, typeFilter || undefined),
      workbenchClient.factClaims(projectId),
      workbenchClient.correctionTasks(projectId),
    ]).then(([typeRows, factRows, claimRows, taskRows]) => {
      if (!active) return;
      setTypes(typeRows); setFacts(factRows.data); setClaims(claimRows.data);
      setCorrectionTasks(taskRows.data); setError("");
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "事实库加载失败"); });
    return () => { active = false; };
  }, [mode, canRead, projectId, typeFilter]);

  async function openFact(fact: FactRecord) {
    setSelected(fact); setError("");
    setEditForm({
      fact_value: fact.fact_value, source_document: fact.source_document ?? "",
      source_url: fact.source_url ?? "", owner: fact.owner ?? "", change_note: "",
    });
    try { setVersions((await workbenchClient.factVersions(projectId, fact.id)).data); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "版本历史加载失败"); }
    try { setPushes((await workbenchClient.factPushes(projectId, fact.id)).data); }
    catch { setPushes([]); }
  }

  async function createFact() {
    if (!canWrite) return;
    setBusy(true);
    try {
      const created = await workbenchClient.createFact(projectId, {
        ...form,
        fact_key: form.fact_key.trim(),
        fact_value: form.fact_value.trim(),
        source_document: form.source_document || null,
        source_url: form.source_url || null,
        owner: form.owner || null,
        business_confirmed: false,
        business_confirmed_note: form.business_confirmed_note || null,
      });
      setFacts((rows) => [...rows, created]); setForm(emptyForm); setSelected(created); setCreateOpen(false);
      onNotice("事实草稿已创建");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "创建事实失败"); }
    finally { setBusy(false); }
  }

  async function saveEdit() {
    if (!selected || !canWrite) return;
    setBusy(true);
    try {
      const updated = await workbenchClient.updateFact(projectId, selected.id, {
        fact_value: editForm.fact_value,
        source_document: editForm.source_document || null,
        source_url: editForm.source_url || null,
        owner: editForm.owner || null,
        change_note: editForm.change_note || null,
      });
      setSelected(updated); await loadFacts(); await openFact(updated); onNotice("事实修订已保存，需重新审批");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "修订事实失败"); }
    finally { setBusy(false); }
  }

  async function submitFact() {
    if (!selected) return;
    setBusy(true);
    try { setSelected(await workbenchClient.submitFact(projectId, selected.id)); await loadFacts(); onNotice("事实已提交审批"); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "提交审批失败"); }
    finally { setBusy(false); }
  }

  async function reviewFact(decision: "approved" | "rejected") {
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await workbenchClient.reviewFact(projectId, selected.id, {
        decision, business_confirmed: businessConfirmed,
        business_confirmed_note: confirmNote || null,
        comment: decision === "rejected" ? (confirmNote || "审批驳回") : null,
      });
      setSelected(updated); await loadFacts(); onNotice(decision === "approved" ? "事实已批准" : "事实已驳回草稿");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "审批失败"); }
    finally { setBusy(false); }
  }

  async function pushFact() {
    if (!selected) return;
    setPushBusy(true);
    try {
      const record = await workbenchClient.factPush(projectId, selected.id, pushTarget,
        pushTarget === "encyclopedia" ? (pushRef.trim() || "other") : pushRef.trim());
      setPushes((rows) => [record, ...rows.filter((row) => row.id !== record.id)]);
      onNotice(record.status === "failed"
        ? "推送未送达，失败原因已记录，可重试"
        : "已推送：百科方向生成的是草稿词条，仍需人工提交与审核");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "推送失败"); }
    finally { setPushBusy(false); }
  }

  async function retryPush(pushId: string) {
    setPushBusy(true);
    try {
      const record = await workbenchClient.retryFactPush(projectId, pushId);
      setPushes((rows) => rows.map((row) => row.id === record.id ? record : row));
      onNotice(record.status === "failed" ? "重试仍未送达" : "重试已送达");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "重试失败"); }
    finally { setPushBusy(false); }
  }

  async function expireFact() {
    if (!selected) return;
    setBusy(true);
    try { setSelected(await workbenchClient.expireFact(projectId, selected.id)); await loadFacts(); onNotice("事实已标记过期"); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "标记过期失败"); }
    finally { setBusy(false); }
  }

  async function createClaim() {
    if (!canWrite) return;
    setBusy(true);
    try {
      const created = await workbenchClient.createFactClaim(projectId, claimForm.sample_id.trim(), {
        claim_text: claimForm.claim_text.trim(),
        fact_id: claimForm.fact_id || null,
        source_url: claimForm.source_url || null,
      });
      setClaims((rows) => [created, ...rows]); setSelectedClaim(created);
      setClaimForm({ sample_id: "", claim_text: "", fact_id: "", source_url: "" });
      onNotice("事实陈述已登记");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "登记事实陈述失败"); }
    finally { setBusy(false); }
  }

  async function reviewClaim() {
    if (!selectedClaim) return;
    setBusy(true);
    try {
      const updated = await workbenchClient.reviewFactClaim(projectId, selectedClaim.id, {
        verdict, review_note: verdictNote || null,
      });
      setSelectedClaim(updated); setClaims((rows) => rows.map((row) => row.id === updated.id ? updated : row));
      setCorrectionTasks((await workbenchClient.correctionTasks(projectId)).data);
      onNotice(updated.correction_task_id ? "判定已保存，已生成纠错任务" : "判定已保存");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "判定失败"); }
    finally { setBusy(false); }
  }

  const approvedFacts = facts.filter((fact) => fact.approval_status === "approved");

  return <div className="knowledge-workspace">
    <WorkTabs items={[{ id: "library", label: "权威事实库" }, { id: "claims", label: "回答核验" }]} active={activeTab} onChange={(tab) => setActiveTab(tab as FactTab)} ariaLabel="事实库视图" />
    {!canRead && <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有内容读取权限。</p></Panel>}
    {canRead && mode !== "live" && <Panel className="knowledge-list-panel"><p className="knowledge-empty">演示模式不连接事实库；切换真实数据后使用。</p></Panel>}
    {error && <p className="form-error" role="alert">{error}</p>}

    {canRead && mode === "live" && activeTab === "library" && <>
      <Panel className={`knowledge-list-panel facts-panel${facts.length ? "" : " facts-empty-panel"}`}><div className="panel-heading"><div><h3>12 类权威事实</h3><p>共 {facts.length} 条；已批准 {approvedFacts.length} 条。按类型分组，点条目查看版本历史。</p></div><div className="facts-heading-actions"><label className="field"><span className="field-label">类型筛选</span><select className="text-input" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}><option value="">全部类型</option>{types.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>{canWrite && <Button icon="plus" onClick={() => setCreateOpen(true)}>新增事实</Button>}</div></div>
        <DataTable columns={[
          { key: "key", label: "事实项", width: "22%", className: "col-title", render: (fact) => <strong title={fact.fact_key}>{fact.fact_key}</strong> },
          { key: "value", label: "事实内容", width: "28%", className: "data-cell-note-inline", render: (fact) => <span title={fact.fact_value}>{fact.fact_value}</span> },
          { key: "type", label: "类型", width: "14%", render: (fact) => types.find((item) => item.value === fact.fact_type)?.label ?? fact.fact_type },
          { key: "version", label: "版本", width: "8%", className: "data-cell-mono", render: (fact) => `v${fact.version_no}` },
          { key: "owner", label: "责任人", width: "12%", render: (fact) => fact.owner ?? "未指定" },
          { key: "status", label: "审批", width: "12%", className: "col-status", render: (fact) => <Badge tone={statusTone(fact.approval_status)}>{statusNames[fact.approval_status] ?? fact.approval_status}</Badge> },
        ]} rows={facts} rowKey={(fact) => fact.id} onRow={(fact) => void openFact(fact)} empty={<div className="knowledge-empty"><strong>还没有权威事实</strong><p>先录一条课程周期、价格或资质，审批通过后内容工厂才能引用。</p>{canWrite && <Button variant="secondary" onClick={() => setCreateOpen(true)}>新增第一条事实</Button>}</div>}/>
      </Panel>

      {createOpen && <DetailModal eyebrow="新增事实" title="先落一条可审批的草稿" subtitle="提交后由内容审核批准；来源文件或链接是批准前置条件。" onClose={() => setCreateOpen(false)}>
        <div className="form-grid">
          <label className="field"><span className="field-label">事实类型</span><select className="text-input" value={form.fact_type} onChange={(e) => setForm({ ...form, fact_type: e.target.value })}>{types.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          <label className="field"><span className="field-label">事实标识</span><input className="text-input" value={form.fact_key} onChange={(e) => setForm({ ...form, fact_key: e.target.value })} placeholder="如“短视频课程周期”"/></label>
          <label className="field"><span className="field-label">事实内容</span><textarea className="text-input knowledge-textarea short" value={form.fact_value} onChange={(e) => setForm({ ...form, fact_value: e.target.value })}/></label>
          <label className="field"><span className="field-label">来源文件</span><input className="text-input" value={form.source_document} onChange={(e) => setForm({ ...form, source_document: e.target.value })} placeholder="简章/合同/备案文件名"/></label>
          <label className="field"><span className="field-label">来源链接</span><input className="text-input" value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })}/></label>
          <label className="field"><span className="field-label">责任人</span><input className="text-input" value={form.owner} onChange={(e) => setForm({ ...form, owner: e.target.value })}/></label>
          <label className="field"><span className="field-label">就业承诺书面确认说明（仅涉及保证就业时填）</span><input className="text-input" value={form.business_confirmed_note} onChange={(e) => setForm({ ...form, business_confirmed_note: e.target.value })}/></label>
        </div>
        <div className="knowledge-actions"><Button variant="secondary" onClick={() => setCreateOpen(false)}>取消</Button><Button disabled={busy || !form.fact_key.trim() || !form.fact_value.trim()} onClick={() => void createFact()}>{busy ? "创建中…" : "创建草稿"}</Button></div>
      </DetailModal>}

      {selected && <DetailModal eyebrow="FACT VERSION" title={selected.fact_key} subtitle={`${types.find((item) => item.value === selected.fact_type)?.label ?? selected.fact_type} · v${selected.version_no} · ${statusNames[selected.approval_status] ?? selected.approval_status}`} onClose={() => setSelected(null)}>
        <p className="knowledge-footnote">来源：{selected.source_document || selected.source_url || "未提供"} · 责任人：{selected.owner ?? "未指定"}{selected.rejection_note ? ` · 驳回说明：${selected.rejection_note}` : ""}</p>
        {canWrite && <div className="form-grid">
          <label className="field"><span className="field-label">事实内容</span><textarea className="text-input knowledge-textarea short" value={editForm.fact_value} onChange={(e) => setEditForm({ ...editForm, fact_value: e.target.value })}/></label>
          <label className="field"><span className="field-label">来源文件</span><input className="text-input" value={editForm.source_document} onChange={(e) => setEditForm({ ...editForm, source_document: e.target.value })}/></label>
          <label className="field"><span className="field-label">来源链接</span><input className="text-input" value={editForm.source_url} onChange={(e) => setEditForm({ ...editForm, source_url: e.target.value })}/></label>
          <label className="field"><span className="field-label">修订说明</span><input className="text-input" value={editForm.change_note} onChange={(e) => setEditForm({ ...editForm, change_note: e.target.value })}/></label>
        </div>}
        <div className="knowledge-actions">
          {canWrite && <Button disabled={busy} onClick={() => void saveEdit()}>保存修订</Button>}
          {canWrite && selected.approval_status === "draft" && <Button variant="secondary" disabled={busy} onClick={() => void submitFact()}>提交审批</Button>}
          {canReview && selected.approval_status === "pending_review" && <>
            <label className="field"><span className="field-label">审批说明</span><input className="text-input" value={confirmNote} onChange={(e) => setConfirmNote(e.target.value)}/></label>
            <label className="field"><span className="field-label">业务方已书面确认保证就业</span><input type="checkbox" checked={businessConfirmed} onChange={(e) => setBusinessConfirmed(e.target.checked)}/></label>
            <Button disabled={busy} onClick={() => void reviewFact("approved")}>批准</Button>
            <Button variant="secondary" disabled={busy} onClick={() => void reviewFact("rejected")}>驳回</Button>
          </>}
          {canReview && selected.approval_status === "approved" && <Button variant="secondary" disabled={busy} onClick={() => void expireFact()}>标记过期</Button>}
          {canReview && selected.approval_status === "approved" && <>
            <label className="field"><span className="field-label">推送方向</span>
              <select className="text-input" value={pushTarget}
                onChange={(e) => { setPushTarget(e.target.value as "encyclopedia" | "webhook"); setPushRef(""); }}>
                <option value="encyclopedia">百科词条（生成草稿）</option>
                <option value="webhook">外部 EEAT 信源（webhook）</option>
              </select>
            </label>
            <label className="field"><span className="field-label">{pushTarget === "encyclopedia" ? "目标平台" : "目标地址"}</span>
              <input className="text-input" value={pushRef} onChange={(e) => setPushRef(e.target.value)}
                placeholder={pushTarget === "encyclopedia" ? "baidu_baike / other" : "https://example.com/eeat-hook"} />
            </label>
            <Button variant="secondary" disabled={pushBusy} onClick={() => void pushFact()}>推送 EEAT</Button>
          </>}
        </div>
        {pushes.length > 0 && <div className="knowledge-list">
          {pushes.map((row) => <div className="knowledge-item" key={row.id}>
            <span>
              <strong>{row.target_type === "encyclopedia" ? "百科词条" : "webhook"} · {row.target_ref}</strong>
              <small>{row.status === "sent" ? "已送达" : row.status === "failed" ? "失败" : "待发"} · 第 {row.attempt_count} 次{row.created_at ? " · " + formatDateTime(row.created_at) : ""}</small>
              {row.error && <small className="form-error">{row.error}</small>}
            </span>
            {row.status === "failed"
              ? <Button variant="secondary" disabled={pushBusy} onClick={() => void retryPush(row.id)}>重试</Button>
              : <Badge tone={row.status === "sent" ? "green" : "amber"}>{row.status === "sent" ? "已送达" : "待发"}</Badge>}
          </div>)}
        </div>}
        <p className="knowledge-empty">推送不等于发布：百科方向只生成草稿词条，仍需提交与审核；webhook 方向只说明对方收下了 JSON，对方是否采用要看回执与后续引用。</p>
        <div className="knowledge-list">{versions.map((row) => <div className="knowledge-item" key={`${row.version_no}-${row.created_at}`}><span><strong>#{row.version_no} {actionNames[row.action] ?? row.action}</strong><small>{row.change_note || "无说明"} · {formatDateTime(row.created_at)}</small></span><Badge tone={row.action === "approved" ? "green" : row.action === "rejected" ? "red" : "slate"}>{actionNames[row.action] ?? row.action}</Badge></div>)}{!versions.length && <p className="knowledge-empty">暂无版本历史</p>}</div>
      </DetailModal>}
    </>}

    {canRead && mode === "live" && activeTab === "claims" && <>
      {canWrite && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>登记事实陈述</h3><p>从样本回答里摘一条涉及基地的陈述；首期人工勾选，第三月再加半自动抽取。</p></div></div>
        <div className="form-grid">
          <label className="field"><span className="field-label">样本 ID</span><input className="text-input" value={claimForm.sample_id} onChange={(e) => setClaimForm({ ...claimForm, sample_id: e.target.value })}/></label>
          <label className="field"><span className="field-label">陈述原文</span><textarea className="text-input knowledge-textarea short" value={claimForm.claim_text} onChange={(e) => setClaimForm({ ...claimForm, claim_text: e.target.value })}/></label>
          <label className="field"><span className="field-label">对照事实（已批准）</span><select className="text-input" value={claimForm.fact_id} onChange={(e) => setClaimForm({ ...claimForm, fact_id: e.target.value })}><option value="">暂不关联</option>{approvedFacts.map((fact) => <option key={fact.id} value={fact.id}>{fact.fact_key}：{fact.fact_value.slice(0, 40)}</option>)}</select></label>
          <label className="field"><span className="field-label">来源 URL</span><input className="text-input" value={claimForm.source_url} onChange={(e) => setClaimForm({ ...claimForm, source_url: e.target.value })}/></label>
        </div>
        <div className="knowledge-actions"><Button disabled={busy || !claimForm.sample_id.trim() || !claimForm.claim_text.trim()} onClick={() => void createClaim()}>登记陈述</Button></div>
      </Panel>}

      <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>回答事实陈述</h3><p>品牌识别问“有没有提到”，事实核验问“说对了没有”；错误/过期会自动生成纠错任务。</p></div></div>
        <div className="knowledge-list">{claims.map((claim) => <button type="button" className="knowledge-item" key={claim.id} onClick={() => { setSelectedClaim(claim); setVerdict(claim.verdict ?? "wrong"); setVerdictNote(""); }}><span><strong>{claim.claim_text}</strong><small>陈述 #{formatSerialNo(claim.serial_no)} · {claim.source_url || "无来源 URL"}</small></span><Badge tone={claim.verdict === "correct" ? "green" : claim.verdict === "wrong" ? "red" : claim.verdict ? "amber" : "slate"}>{claim.verdict ? verdictNames[claim.verdict] : "待核验"}</Badge></button>)}{!claims.length && <p className="knowledge-empty">暂无事实陈述</p>}</div>
      </Panel>

      <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>纠错任务</h3><p>由错误/过期判定自动生成；状态由内容机会中心跟进。</p></div></div>
        <div className="knowledge-list">{correctionTasks.map((task) => <div className="knowledge-item" key={task.id}><span><strong>{task.title}</strong><small>{task.source_url || "无来源 URL"} · {task.description || "无说明"}</small></span><Badge tone={task.status === "open" ? "amber" : task.status === "resolved" ? "green" : "slate"}>{task.status}</Badge></div>)}{!correctionTasks.length && <p className="knowledge-empty">暂无纠错任务</p>}</div>
      </Panel>

      {selectedClaim && <DetailModal eyebrow="FACT CHECK" title="核验判定" subtitle={selectedClaim.claim_text} onClose={() => setSelectedClaim(null)}>
        <p className="knowledge-footnote">来源：{selectedClaim.source_url || "未提供"} · 对照事实：{selectedClaim.fact_id ? ((approvedFacts.find((fact) => fact.id === selectedClaim.fact_id) ?? facts.find((fact) => fact.id === selectedClaim.fact_id))?.fact_key ?? "已关联事实") : "未关联"}{selectedClaim.correction_task_id ? " · 已生成纠错任务" : ""}</p>
        {canReviewClaims ? <div className="knowledge-actions">
          <label className="field"><span className="field-label">判定</span><select className="text-input" value={verdict} onChange={(e) => setVerdict(e.target.value)}><option value="correct">正确</option><option value="wrong">错误</option><option value="expired">过期</option><option value="unconfirmed">无法确认</option></select></label>
          <label className="field"><span className="field-label">判定说明</span><input className="text-input" value={verdictNote} onChange={(e) => setVerdictNote(e.target.value)}/></label>
          <Button disabled={busy} onClick={() => void reviewClaim()}>保存判定</Button>
        </div> : <p className="knowledge-empty">当前账号没有事实复核权限。</p>}
      </DetailModal>}
    </>}
  </div>;
}
