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
const NAME_MAX = 128;
const DOMAIN_MAX = 255;
const DOMAIN_INPUT_MAX = 2048;
const NOTES_MAX = 5000;
/** 最终落库只保存主机名；输入框允许粘贴完整网址，由 parseDomainInput 自动提取。 */
const DOMAIN_PATTERN = /^(?=.{1,255}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])$/;

function nameError(value: string): string {
  const clean = value.trim();
  if (!clean) return "请填写竞品名称";
  if (/[\r\n\t]/.test(value)) return "名称不能包含换行、回车或制表符";
  return "";
}

/** 接受完整网址或裸域名，统一提取主机名；路径、参数、端口和协议都在这里被丢掉。 */
function parseDomainInput(value: string): { hostname: string; error: string } {
  const raw = value.trim();
  if (!raw) return { hostname: "", error: "" };
  const candidate = raw.startsWith("//")
    ? `https:${raw}`
    : /^[a-z][a-z0-9+.-]*:\/\//i.test(raw)
      ? raw
      : `https://${raw}`;
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return { hostname: "", error: "只支持 http:// 或 https:// 网址" };
    }
    const hostname = parsed.hostname.toLowerCase().replace(/\.$/, "");
    if (!hostname) return { hostname: "", error: "请输入有效网址，如 https://rival.example.com" };
    if (hostname.length > DOMAIN_MAX) return { hostname: "", error: `域名不能超过 ${DOMAIN_MAX} 字` };
    if (!DOMAIN_PATTERN.test(hostname)) return { hostname: "", error: "无法从网址中识别有效域名" };
    return { hostname, error: "" };
  } catch {
    return { hostname: "", error: "请输入有效网址，如 https://rival.example.com" };
  }
}

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
  const [touched, setTouched] = useState({ name: false, domain: false });
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<CompetitorRecord | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");

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

  function resetFieldState() {
    setTouched({ name: false, domain: false });
    setSubmitAttempted(false);
  }

  function startCreate() {
    setEditingId(null);
    setDraft(blank());
    resetFieldState();
  }

  function startEdit(item: CompetitorRecord) {
    setEditingId(item.id);
    setDraft({ name: item.name, domain: item.domain ?? "", notes: item.notes ?? "", is_active: item.is_active });
    resetFieldState();
  }

  function closeEditor() {
    setEditingId(null);
    setDraft(null);
    resetFieldState();
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
    setSubmitAttempted(true);
    const currentNameError = nameError(draft.name);
    const parsedDomain = parseDomainInput(draft.domain);
    if (currentNameError || parsedDomain.error) {
      document.getElementById(currentNameError ? "competitor-name" : "competitor-domain")?.focus();
      return;
    }
    const name = draft.name.trim();
    setSaving(true);
    try {
      await workbenchClient.saveCompetitor(projectId, {
        name,
        domain: parsedDomain.hostname || null,
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

  function askDelete(item: CompetitorRecord) {
    setDeleteError("");
    setDeleteTarget(item);
  }

  function askDeleteEditing() {
    if (!editingId || !draft) return;
    const item = items.find((row) => row.id === editingId) ?? {
      id: editingId,
      name: draft.name.trim() || "未命名竞品",
      domain: draft.domain.trim() || null,
      notes: draft.notes.trim() || null,
      is_active: draft.is_active,
    };
    askDelete(item);
  }

  function closeDelete() {
    if (deleteBusy) return;
    setDeleteTarget(null);
    setDeleteError("");
  }

  async function confirmDelete() {
    if (!deleteTarget || deleteBusy) return;
    const removedId = deleteTarget.id;
    const removedName = deleteTarget.name;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await workbenchClient.deleteCompetitor(projectId, removedId);
      setDeleteTarget(null);
      if (editingId === removedId) closeEditor();
      if (items.length <= 1 && page > 1) setPage((value) => value - 1);
      else setVersion((value) => value + 1);
      onNotice(`已删除竞品「${removedName}」`);
    } catch (cause) {
      setDeleteError(cause instanceof Error ? cause.message : "删除失败");
    } finally { setDeleteBusy(false); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">竞品台账仅在真实接口模式显示。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有竞品查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  const currentNameError = draft ? nameError(draft.name) : "";
  const currentDomain = draft ? parseDomainInput(draft.domain) : { hostname: "", error: "" };
  const currentDomainError = currentDomain.error;
  const showNameError = Boolean(currentNameError) && (submitAttempted || touched.name);
  const showDomainError = Boolean(currentDomainError) && (submitAttempted || touched.domain);

  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>竞品台账</h3><p>共 {total} 个竞品 · 用于答案提及归因与 Share of Voice</p></div>{canWrite && <Button icon="plus" onClick={startCreate}>新增竞品</Button>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="knowledge-list competitor-list">
        {items.map((item) => <div className="knowledge-item competitor-item" key={item.id}>
          <span className="competitor-item-main">
            <strong>{item.name}</strong>
            <small title={`${item.domain || "无官网域名"}${item.notes ? ` · ${item.notes}` : ""}`}>{item.domain || "无官网域名"}{item.notes ? ` · ${item.notes}` : ""}</small>
          </span>
          <span className="knowledge-actions competitor-item-actions">
            {item.is_active ? <Badge tone="green">跟踪中</Badge> : <Badge tone="slate">已停用</Badge>}
            {canWrite && <>
              <Button variant="secondary" onClick={() => startEdit(item)}>编辑</Button>
              <Button variant="secondary" onClick={() => void toggle(item)}>{item.is_active ? "停用" : "启用"}</Button>
              <Button variant="danger" onClick={() => askDelete(item)}>删除</Button>
            </>}
          </span>
        </div>)}
        {loading && !items.length && <p className="knowledge-empty">正在加载竞品…</p>}
        {!loading && !items.length && !error && <p className="knowledge-empty">当前项目暂无竞品，点击右上角新增。</p>}
      </div>
      <TablePager page={page} total={total} pageSize={PAGE_SIZE} loading={loading} onChange={setPage}/>
    </Panel>
    {draft && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) closeEditor(); }}>
      <div className="modal competitor-modal modal-scroll" role="dialog" aria-modal="true" aria-labelledby="competitor-draft-title">
        <div className="modal-header"><div><p className="eyebrow">COMPETITOR</p><h2 id="competitor-draft-title">{editingId ? "编辑竞品" : "新增竞品"}</h2></div><button className="icon-button" aria-label="关闭" disabled={saving} onClick={closeEditor}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">名称在项目内唯一；停用后不再计入提及归因。官网可直接粘贴完整网址，保存时自动提取域名。</p>
        <form className="competitor-form" onSubmit={save} noValidate>
          <div className="competitor-form-grid">
            <label className="field">
              <span className="field-label">竞品名称 <span className="competitor-required">必填</span></span>
              <input
                id="competitor-name"
                className={`text-input${showNameError ? " is-invalid" : ""}`}
                value={draft.name}
                maxLength={NAME_MAX}
                required
                aria-required="true"
                aria-invalid={showNameError || undefined}
                aria-describedby={showNameError ? "competitor-name-error" : undefined}
                disabled={saving}
                placeholder="例如：某某品牌"
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                onBlur={() => setTouched((value) => ({ ...value, name: true }))}
              />
              <span className="competitor-field-meta"><span>项目内唯一</span><span className="counter">{draft.name.length}/{NAME_MAX}</span></span>
              {showNameError && <span className="competitor-field-error" id="competitor-name-error">{currentNameError}</span>}
            </label>
            <label className="field">
              <span className="field-label">官网域名 / 网址 <span className="competitor-optional">可选</span></span>
              <input
                id="competitor-domain"
                className={`text-input${showDomainError ? " is-invalid" : ""}`}
                value={draft.domain}
                maxLength={DOMAIN_INPUT_MAX}
                aria-invalid={showDomainError || undefined}
                aria-describedby={showDomainError ? "competitor-domain-error" : undefined}
                disabled={saving}
                placeholder="https://rival.example.com"
                onChange={(event) => setDraft({ ...draft, domain: event.target.value })}
                onBlur={() => {
                  setTouched((value) => ({ ...value, domain: true }));
                  setDraft((value) => {
                    if (!value) return value;
                    const parsed = parseDomainInput(value.domain);
                    return parsed.error ? value : { ...value, domain: parsed.hostname };
                  });
                }}
              />
              <span className="competitor-field-meta"><span>可粘贴完整网址，保存时自动提取域名</span><span className="counter">{currentDomain.hostname ? `域名 ${currentDomain.hostname.length}/${DOMAIN_MAX}` : `网址 ${draft.domain.length}/${DOMAIN_INPUT_MAX}`}</span></span>
              {showDomainError && <span className="competitor-field-error" id="competitor-domain-error">{currentDomainError}</span>}
            </label>
          </div>
          <label className="field">
            <span className="field-label">备注 <span className="competitor-optional">可选</span></span>
            <textarea
              className="text-input knowledge-textarea competitor-notes"
              value={draft.notes}
              maxLength={NOTES_MAX}
              disabled={saving}
              placeholder="记录别名、识别线索或竞品关系，便于后续归因复核。"
              onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
            />
            <span className="competitor-field-meta"><span>用于归因复核，不参与名称匹配</span><span className="counter">{draft.notes.length}/{NOTES_MAX}</span></span>
          </label>
          <label className="rounds-checkbox competitor-active-row">
            <input type="checkbox" checked={draft.is_active} disabled={saving} onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })}/>
            <span><strong>启用跟踪</strong><small>停用后不再计入新的提及归因</small></span>
          </label>
          <div className="modal-actions competitor-modal-actions">
            {editingId && <Button type="button" variant="danger" disabled={saving} onClick={askDeleteEditing}>删除竞品</Button>}
            <div className="competitor-modal-actions-right">
              <Button type="button" variant="secondary" disabled={saving} onClick={closeEditor}>取消</Button>
              <Button type="submit" disabled={saving}>{saving ? "保存中…" : editingId ? "保存修改" : "保存竞品"}</Button>
            </div>
          </div>
        </form>
      </div>
    </div>}
    {deleteTarget && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closeDelete(); }}>
      <div className="modal competitor-delete-modal" role="dialog" aria-modal="true" aria-labelledby="competitor-delete-title">
        <div className="modal-header"><div><p className="eyebrow">DELETE</p><h2 id="competitor-delete-title">删除竞品</h2></div><button className="icon-button" aria-label="关闭" disabled={deleteBusy} onClick={closeDelete}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">确定删除竞品「<strong>{deleteTarget.name}</strong>」吗？此操作不可恢复。</p>
        <p className="field-hint">如已有历史提及或引用，系统会阻止删除，建议改用“停用”。</p>
        {deleteError && <p className="form-error" role="alert">{deleteError}</p>}
        <div className="modal-actions">
          <Button type="button" variant="secondary" disabled={deleteBusy} onClick={closeDelete}>取消</Button>
          <Button type="button" variant="danger" disabled={deleteBusy} onClick={() => void confirmDelete()}>{deleteBusy ? "删除中…" : "确认删除"}</Button>
        </div>
      </div>
    </div>}
  </div>;
}
