"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { MetricDefinitionRecord } from "@/lib/workbench/types";

interface Draft { code: string; name: string; formula: string; description: string; effective_from: string }
const blank = (): Draft => ({ code: "", name: "", formula: "", description: "", effective_from: "" });

export function MetricsWorkspace({ mode, projectId, canRead, canWrite, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean; onNotice: (message: string) => void;
}) {
  const [items, setItems] = useState<MetricDefinitionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [retireTarget, setRetireTarget] = useState<MetricDefinitionRecord | null>(null);
  const [retiring, setRetiring] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.metricDefinitions(projectId).then((result) => {
      if (active) { setItems(result.data); setError(""); }
    }).catch((cause) => {
      if (active) { setItems([]); setError(cause instanceof Error ? cause.message : "指标定义加载失败"); }
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [mode, canRead, projectId, version]);

  async function confirmRetire() {
    if (!retireTarget || !canWrite || retiring) return;
    setRetiring(true);
    try {
      await workbenchClient.saveMetric(projectId, { status: "retired" }, retireTarget.id);
      setItems((rows) => rows.map((row) => row.id === retireTarget.id ? { ...row, status: "retired", effective_to: new Date().toISOString() } : row));
      onNotice(`已停用 ${retireTarget.code} v${retireTarget.rule_version}`);
      setRetireTarget(null);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "操作失败"); }
    finally { setRetiring(false); }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || !canWrite) return;
    if (!draft.code.trim() || !draft.name.trim() || !draft.formula.trim()) { onNotice("口径代码、名称与公式必填"); return; }
    setSaving(true);
    try {
      await workbenchClient.saveMetric(projectId, {
        code: draft.code.trim(),
        name: draft.name.trim(),
        formula: draft.formula.trim(),
        description: draft.description.trim() || null,
        effective_from: draft.effective_from ? new Date(draft.effective_from).toISOString() : undefined,
      });
      setDraft(null);
      setVersion((value) => value + 1);
      onNotice("指标定义新版本已创建（rule_version 自动递增）");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "保存失败"); }
    finally { setSaving(false); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">指标定义仅在真实接口模式显示。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有统计/口径查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;
  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>指标定义</h3><p>共 {items.length} 个版本 · 新版本按 rule_version 累积，历史统计按版本追溯</p></div>{canWrite && <Button icon="plus" onClick={() => setDraft(blank())}>新增口径版本</Button>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="knowledge-list">
        {items.map((item) => <div className="knowledge-item" key={item.id}>
          <span><strong>{item.name} <code>{item.code}</code> · v{item.rule_version}</strong><small>{item.formula}{item.description ? ` · ${item.description}` : ""}</small><small>生效：{(item.effective_from || "").slice(0, 10)}{item.effective_to ? ` → ${item.effective_to.slice(0, 10)}` : " 起"}</small></span>
          <span className="knowledge-actions">{item.status === "active" ? <Badge tone="green">生效中</Badge> : <Badge tone="slate">已停用</Badge>}{canWrite && item.status === "active" && <Button variant="secondary" onClick={() => setRetireTarget(item)}>停用</Button>}</span>
        </div>)}
        {loading && !items.length && <p className="knowledge-empty">正在加载指标定义…</p>}
        {!loading && !items.length && !error && <p className="knowledge-empty">当前项目暂无指标定义。</p>}
      </div>
    </Panel>

    {draft && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) setDraft(null); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="metric-new-title" style={{ maxHeight: "88vh", overflowY: "auto" }}>
        <div className="modal-header"><div><p className="eyebrow">METRIC VERSION</p><h2 id="metric-new-title">新增口径版本</h2></div><button className="icon-button" aria-label="关闭" disabled={saving} onClick={() => setDraft(null)}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">同一代码新建即生成新 rule_version，旧版本保留；历史统计按版本追溯。</p>
        <form onSubmit={save}>
          <label className="field"><span className="field-label">口径代码</span><input className="text-input" value={draft.code} required maxLength={64} disabled={saving} placeholder="brand_mention_rate" onChange={(event) => setDraft({ ...draft, code: event.target.value })}/></label>
          <label className="field"><span className="field-label">口径名称</span><input className="text-input" value={draft.name} required maxLength={128} disabled={saving} onChange={(event) => setDraft({ ...draft, name: event.target.value })}/></label>
          <label className="field"><span className="field-label">计算公式</span><textarea className="text-input knowledge-textarea short" value={draft.formula} required maxLength={5000} disabled={saving} placeholder="品牌提及有效回答 / 有效回答" onChange={(event) => setDraft({ ...draft, formula: event.target.value })}/></label>
          <label className="field"><span className="field-label">口径说明</span><textarea className="text-input knowledge-textarea short" value={draft.description} maxLength={5000} disabled={saving} onChange={(event) => setDraft({ ...draft, description: event.target.value })}/></label>
          <label className="field"><span className="field-label">生效时间（可选，默认立即）</span><input type="datetime-local" className="text-input" value={draft.effective_from} disabled={saving} onChange={(event) => setDraft({ ...draft, effective_from: event.target.value })}/></label>
          <div className="modal-actions"><Button type="submit" disabled={saving}>{saving ? "保存中…" : "创建版本"}</Button><Button variant="secondary" disabled={saving} onClick={() => setDraft(null)}>取消</Button></div>
        </form>
      </div>
    </div>}

    {retireTarget && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !retiring) setRetireTarget(null); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="metric-retire-title">
        <div className="modal-header"><div><p className="eyebrow">DISABLE METRIC</p><h2 id="metric-retire-title">停用口径版本</h2></div><button className="icon-button" aria-label="关闭" disabled={retiring} onClick={() => setRetireTarget(null)}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">确认停用 <strong>{retireTarget.name}</strong>（<code>{retireTarget.code}</code> · v{retireTarget.rule_version}）？停用后该版本不再用于新的统计，历史结果仍按版本追溯。</p>
        <div className="modal-actions"><Button variant="secondary" disabled={retiring} onClick={() => setRetireTarget(null)}>取消</Button><Button variant="danger" disabled={retiring} onClick={() => void confirmRetire()}>{retiring ? "停用中…" : "确认停用"}</Button></div>
      </div>
    </div>}
  </div>;
}
