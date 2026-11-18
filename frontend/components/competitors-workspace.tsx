"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { TablePager } from "./table-pager";
import { workbenchClient } from "@/lib/workbench/client";
import type { CompetitorRecord } from "@/lib/workbench/types";

interface Draft { name: string; domain: string; notes: string; is_active: boolean }
const blank = (): Draft => ({ name: "", domain: "", notes: "", is_active: true });
/** 与 client.competitors 的 page_size 保持一致，翻页控件按这个页大小算页数。 */
const PAGE_SIZE = 50;

export function CompetitorsWorkspace({ mode, projectId, canRead, canWrite, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean; onNotice: (message: string) => void;
}) {
  const [items, setItems] = useState<CompetitorRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  // 编辑态复用新增表单：后端 PATCH 早就支持改名/域名/备注，之前界面只能新增和启停，
  // 名字打错一个字只能停用重建，会在台账里留下一条废记录。
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.competitors(projectId, page).then((result) => {
      if (!active) return;
      setItems(result.data);
      // 总数取后端 meta.total：之前用 items.length，超过一页时标题会把当页条数当成总数。
      setTotal(result.meta?.total ?? result.data.length);
      setError("");
    }).catch((cause) => {
      if (active) { setItems([]); setTotal(0); setError(cause instanceof Error ? cause.message : "竞品加载失败"); }
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [mode, canRead, projectId, page, version]);

  function startCreate() {
    setEditingId(null);
    setDraft(blank());
  }

  function startEdit(item: CompetitorRecord) {
    setEditingId(item.id);
    setDraft({ name: item.name, domain: item.domain ?? "", notes: item.notes ?? "", is_active: item.is_active });
  }

  function closeEditor() {
    setEditingId(null);
    setDraft(null);
  }

  async function toggle(item: CompetitorRecord) {
    if (!canWrite) return;
    try {
      await workbenchClient.saveCompetitor(projectId, { is_active: !item.is_active }, item.id);
      setItems((rows) => rows.map((row) => row.id === item.id ? { ...row, is_active: !row.is_active } : row));
      onNotice(item.is_active ? "已停用该竞品" : "已启用该竞品");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "操作失败"); }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || !canWrite) return;
    const name = draft.name.trim();
    if (!name) { onNotice("请填写竞品名称"); return; }
    setSaving(true);
    try {
      await workbenchClient.saveCompetitor(projectId, {
        name,
        domain: draft.domain.trim() || null,
        notes: draft.notes.trim() || null,
        is_active: draft.is_active,
      }, editingId ?? undefined);
      const wasEditing = Boolean(editingId);
      closeEditor();
      setVersion((value) => value + 1);
      onNotice(wasEditing ? "竞品已更新" : "竞品已保存");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "保存失败"); }
    finally { setSaving(false); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">竞品台账仅在真实接口模式显示。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有竞品查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;
  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>竞品台账</h3><p>共 {total} 个竞品 · 用于答案提及归因与 Share of Voice</p></div>{canWrite && <Button icon="plus" onClick={startCreate}>新增竞品</Button>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="knowledge-list">
        {items.map((item) => <div className="knowledge-item" key={item.id}>
          <span><strong>{item.name}</strong><small>{item.domain || "无官网域名"}{item.notes ? ` · ${item.notes}` : ""}</small></span>
          <span className="knowledge-actions">{item.is_active ? <Badge tone="green">跟踪中</Badge> : <Badge tone="slate">已停用</Badge>}{canWrite && <><Button variant="secondary" onClick={() => startEdit(item)}>编辑</Button><Button variant="secondary" onClick={() => void toggle(item)}>{item.is_active ? "停用" : "启用"}</Button></>}</span>
        </div>)}
        {loading && !items.length && <p className="knowledge-empty">正在加载竞品…</p>}
        {!loading && !items.length && !error && <p className="knowledge-empty">当前项目暂无竞品，点击右上角新增。</p>}
      </div>
      <TablePager page={page} total={total} pageSize={PAGE_SIZE} loading={loading} onChange={setPage}/>
    </Panel>
    {draft && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) closeEditor(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="competitor-draft-title" style={{ maxHeight: "88vh", overflowY: "auto" }}>
        <div className="modal-header"><div><p className="eyebrow">COMPETITOR</p><h2 id="competitor-draft-title">{editingId ? "编辑竞品" : "新增竞品"}</h2></div><button className="icon-button" aria-label="关闭" disabled={saving} onClick={closeEditor}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">名称在项目内唯一；停用后不再计入提及归因。</p>
        <form onSubmit={save}>
          <label className="field"><span className="field-label">竞品名称</span><input className="text-input" value={draft.name} required maxLength={128} disabled={saving} onChange={(event) => setDraft({ ...draft, name: event.target.value })}/></label>
          <label className="field"><span className="field-label">官网域名</span><input className="text-input" value={draft.domain} maxLength={255} disabled={saving} placeholder="rival.example.com" onChange={(event) => setDraft({ ...draft, domain: event.target.value })}/></label>
          <label className="field"><span className="field-label">备注</span><textarea className="text-input knowledge-textarea short" value={draft.notes} maxLength={5000} disabled={saving} onChange={(event) => setDraft({ ...draft, notes: event.target.value })}/></label>
          <label className="rounds-checkbox"><input type="checkbox" checked={draft.is_active} disabled={saving} onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })}/> 启用跟踪</label>
          <div className="modal-actions"><Button type="submit" disabled={saving}>{saving ? "保存中…" : editingId ? "保存修改" : "保存竞品"}</Button><Button variant="secondary" disabled={saving} onClick={closeEditor}>取消</Button></div>
        </form>
      </div>
    </div>}
  </div>;
}