"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel, SelectInput, TextInput } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { FaqRecord, MaterialRecord, Project, Tone } from "@/lib/workbench/types";

interface WorkspaceProps {
  mode: "mock" | "live";
  projectId: string;
  projects: Project[];
  canRead: boolean;
  canWrite: boolean;
  onNotice: (message: string) => void;
}

const faqLabels: Record<FaqRecord["status"], string> = {
  draft: "草稿",
  published: "已上架",
  unpublished: "已下架",
};

const materialLabels: Record<MaterialRecord["category"], string> = {
  image: "图片",
  document: "文档",
  case: "案例",
};

function faqTone(status: FaqRecord["status"]): Tone {
  if (status === "published") return "green";
  if (status === "unpublished") return "slate";
  return "amber";
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

const QUESTION_MAX = 255;
const ANSWER_MAX = 10000;
const CATEGORY_MAX = 64;
const FAQ_PAGE_SIZE = 20;

function formatTime(value: string | null | undefined): string {
  if (!value) return "未保存";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function EmptyLive({ message }: { message: string }) {
  return <div className="knowledge-empty editor-empty"><Icon name="folder" size={28}/><strong>暂无真实记录</strong><p>{message}</p></div>;
}

export function FaqLiveWorkspace({ projectId, canRead, canWrite, onNotice }: WorkspaceProps) {
  const [items, setItems] = useState<FaqRecord[]>([]);
  const [draft, setDraft] = useState<FaqRecord | null>(null);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [categories, setCategories] = useState<string[]>([]);
  const [creatingCategory, setCreatingCategory] = useState(false);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [saving, setSaving] = useState(false);
  const [loadedKey, setLoadedKey] = useState("");
  const [reloadToken, setReloadToken] = useState(0);

  const targetProject = projectId === "all" ? "" : projectId;
  const loadKey = `${targetProject}:${filter}:${categoryFilter}:${page}:${query}:${reloadToken}`;
  const loading = loadedKey !== loadKey;

  // 搜索走服务端：输入停顿后再请求，避免每个字符都发一次，也避免只搜到"已加载的一页"。
  useEffect(() => {
    const timer = setTimeout(() => {
      const next = search.trim();
      if (next === query) return;
      setQuery(next);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search, query]);

  useEffect(() => {
    if (!canRead || !targetProject) return;
    let active = true;
    const status = filter === "all" || filter === "deleted" ? undefined : filter;
    workbenchClient.faqs(targetProject, {
      status,
      category: categoryFilter === "all" ? undefined : categoryFilter,
      q: query || undefined,
      page,
      pageSize: FAQ_PAGE_SIZE,
      deleted: filter === "deleted" ? true : undefined,
    })
      .then((result) => {
        if (!active) return;
        setItems(result.data);
        setTotal(result.meta?.total ?? result.data.length);
        if (page === 1) setDraft((current) => current && result.data.some((item) => item.id === current.id) ? current : result.data[0] ?? null);
      })
      .catch((cause) => { if (active) onNotice(cause instanceof Error ? cause.message : "FAQ 加载失败"); })
      .finally(() => { if (active) setLoadedKey(loadKey); });
    return () => { active = false; };
  }, [canRead, targetProject, filter, categoryFilter, page, query, reloadToken, loadKey, onNotice]);

  useEffect(() => {
    if (!canRead || !targetProject) return;
    let active = true;
    workbenchClient.faqCategories(targetProject)
      .then((list) => { if (active) setCategories(list); })
      .catch(() => { if (active) setCategories([]); });
    return () => { active = false; };
  }, [canRead, targetProject, reloadToken]);

  function refresh(nextFilter = filter, nextCategory = categoryFilter) {
    setFilter(nextFilter);
    setCategoryFilter(nextCategory);
    setPage(1);
    setReloadToken((value) => value + 1);
  }


  function startNew() {
    if (!canWrite) { onNotice("当前账号没有内容编辑权限"); return; }
    setCreatingCategory(false);
    setDraft({
      id: "",
      project_id: targetProject,
      question: "",
      answer: "",
      category: "",
      status: "draft",
      sort_order: 0,
      updated_at: null,
    });
  }

  async function save(status?: FaqRecord["status"], record = draft) {
    if (!record || !canWrite) return;
    if (!targetProject) { onNotice("请先选择项目"); return; }
    if (!record.question.trim() || !record.answer.trim()) { onNotice("请填写问题和答案"); return; }
    setSaving(true);
    try {
      if (record.id) {
        const updated = await workbenchClient.updateFaq(targetProject, record.id, {
          question: record.question.trim(),
          answer: record.answer.trim(),
          category: record.category?.trim() || null,
          status: status ?? record.status,
          sort_order: record.sort_order,
        });
        setDraft(updated);
        refresh();
      } else {
        const created = await workbenchClient.createFaq(targetProject, {
          question: record.question.trim(),
          answer: record.answer.trim(),
          category: record.category?.trim() || null,
          status: status ?? record.status,
          sort_order: record.sort_order,
        });
        const result = await workbenchClient.faqs(targetProject, { page: 1, pageSize: 20 });
        setItems(result.data);
        setTotal(result.meta?.total ?? result.data.length);
        setDraft(result.data.find((item) => item.id === created.id) ?? result.data[0] ?? null);
        setSearch("");
        setQuery("");
        refresh("all", "all");
        setCreatingCategory(false);
      }
      onNotice("FAQ 已保存到服务器");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "FAQ 保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!draft?.id || !canWrite || !targetProject) return;
    if (!window.confirm("确认删除这条 FAQ？删除后可在“已删除”中恢复。")) return;
    setSaving(true);
    try {
      const updated = await workbenchClient.deleteFaq(targetProject, draft.id);
      setDraft(updated);
      refresh("deleted", "all");
      onNotice("FAQ 已删除，可在“已删除”中恢复");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "FAQ 删除失败");
    } finally {
      setSaving(false);
    }
  }

  async function restore() {
    if (!draft?.id || !canWrite || !targetProject) return;
    setSaving(true);
    try {
      const restored = await workbenchClient.restoreFaq(targetProject, draft.id);
      setDraft(restored);
      refresh("draft", "all");
      onNotice("FAQ 已恢复为草稿");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "FAQ 恢复失败");
    } finally {
      setSaving(false);
    }
  }

  async function togglePublish() {
    if (!draft?.id || !canWrite || !targetProject) return;
    const next = draft.status === "published" ? "unpublished" : "published";
    const confirmed = window.confirm(
      next === "unpublished"
        ? "确认下架这条 FAQ？下架后公开只读接口不再返回它，但记录仍保留在「已下架」。"
        : "确认上架这条 FAQ？上架后公开只读接口会返回它。",
    );
    if (!confirmed) return;
    // 只提交 status：用户改了问题/答案但没保存时，切上下架不应顺带把草稿写进库
    setSaving(true);
    try {
      const updated = await workbenchClient.updateFaq(targetProject, draft.id, { status: next });
      setDraft((current) => current && current.id === updated.id ? { ...current, status: updated.status, updated_at: updated.updated_at } : current);
      setItems((current) => current.map((item) => item.id === updated.id ? { ...item, status: updated.status, updated_at: updated.updated_at } : item));
      onNotice(next === "published" ? "FAQ 已上架" : "FAQ 已下架");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "FAQ 状态更新失败");
    } finally {
      setSaving(false);
    }
  }

  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有 FAQ 查看权限。</p></Panel>;
  if (!targetProject) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先在上方选择具体项目，FAQ 按项目维护。</p></Panel>;

  const isDeleted = Boolean(draft?.deleted_at);
  const readOnly = !canWrite || isDeleted;

  return <div className="knowledge-workspace">
    <div className="knowledge-grid">
      <Panel className="knowledge-list-panel">
        <div className="panel-heading"><div><h3>FAQ 列表</h3><p>真实接口 · 已上架且未删除的条目进入公开只读接口</p></div><Badge tone="blue">{total} 条</Badge></div>
        <div className="knowledge-toolbar"><div className="search-field"><Icon name="search" size={16}/><input aria-label="搜索 FAQ" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索问题或答案（服务端搜索）" /></div><select className="knowledge-filter" aria-label="筛选 FAQ 状态" value={filter} onChange={(event) => refresh(event.target.value, categoryFilter)}><option value="all">全部状态</option><option value="draft">草稿</option><option value="published">已上架</option><option value="unpublished">已下架</option><option value="deleted">已删除</option></select><select className="knowledge-filter" aria-label="筛选 FAQ 分类" value={categoryFilter} onChange={(event) => refresh(filter, event.target.value)}><option value="all">全部分类</option>{categories.map((category) => <option key={category} value={category}>{category}</option>)}</select></div>
        <div className="knowledge-list">{items.map((item) => <button key={item.id} className={`knowledge-item ${draft?.id === item.id ? "selected" : ""}`} onClick={() => { setCreatingCategory(false); setDraft({ ...item }); }}><span><strong>{item.question}</strong><small>{formatTime(item.updated_at)}{item.category ? ` · ${item.category}` : ""} · 排序 {item.sort_order}</small></span>{item.deleted_at ? <Badge tone="slate">已删除</Badge> : <Badge tone={faqTone(item.status)}>{faqLabels[item.status]}</Badge>}</button>)}{!items.length && !loading && <p className="knowledge-empty">{query ? `没有匹配「${query}」的 FAQ` : "当前筛选下没有 FAQ"}</p>}{loading && <p className="knowledge-empty">正在加载 FAQ…</p>}</div>
        <div className="knowledge-panel-foot">
          <span>共 {total} 条{total > FAQ_PAGE_SIZE ? ` · 第 ${page} / ${Math.max(1, Math.ceil(total / FAQ_PAGE_SIZE))} 页` : ""}</span>
          {total > FAQ_PAGE_SIZE && <>
            <Button variant="secondary" disabled={loading || page <= 1} onClick={() => setPage(page - 1)}>上一页</Button>
            <Button variant="secondary" disabled={loading || page * FAQ_PAGE_SIZE >= total} onClick={() => setPage(page + 1)}>下一页</Button>
          </>}
          {canWrite && <Button variant="secondary" icon="plus" onClick={startNew}>新增 FAQ</Button>}
        </div>
      </Panel>
      <Panel className="knowledge-editor-panel">
        <div className="panel-heading"><div><h3>{draft?.id ? (readOnly ? "查看 FAQ" : "编辑 FAQ") : "新增 FAQ"}</h3><p>{readOnly ? "只读：当前账号没有 FAQ 编辑权限" : "保存后由后端校验权限并写审计"}</p></div><Icon name="blocks" size={20}/></div>
        {draft ? <form onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); void save(); }}>
          <TextInput label="问题" value={draft.question} disabled={readOnly} maxLength={QUESTION_MAX} onChange={(event) => setDraft({ ...draft, question: event.target.value })} placeholder="输入客户经常提出的问题" />
          <p className="knowledge-footnote">问题字数 {draft.question.length} / {QUESTION_MAX}</p>
          {canWrite && !isDeleted && categories.length > 0 && !creatingCategory
            ? <label className="field"><span className="field-label">分类（可选，从已有分类选择）</span>
                <select className="text-input" value={draft.category ?? ""} onChange={(event) => {
                  const value = event.target.value;
                  if (value === "__new__") { setCreatingCategory(true); setDraft({ ...draft, category: "" }); return; }
                  setDraft({ ...draft, category: value });
                }}>
                  <option value="">未分类</option>
                  {draft.category && !categories.includes(draft.category) && <option value={draft.category}>{draft.category}</option>}
                  {categories.map((category) => <option key={category} value={category}>{category}</option>)}
                  <option value="__new__">＋ 新建分类…</option>
                </select>
              </label>
            : <TextInput label={creatingCategory ? "新分类名称" : "分类（可选）"} value={draft.category ?? ""} disabled={readOnly} maxLength={CATEGORY_MAX} onChange={(event) => setDraft({ ...draft, category: event.target.value })} placeholder={creatingCategory ? "输入新分类，例如：食宿" : "例如：到校、报名、课程"} />}
          <label className="field"><span className="field-label">答案</span><textarea className="text-input knowledge-textarea" value={draft.answer} disabled={readOnly} maxLength={ANSWER_MAX} onChange={(event) => setDraft({ ...draft, answer: event.target.value })} placeholder="输入准备发布的回答" /></label>
          <p className="knowledge-footnote">答案字数 {draft.answer.length} / {ANSWER_MAX}</p>
          <TextInput label="排序（越小越靠前）" type="number" min={0} max={9999} value={String(draft.sort_order)} disabled={readOnly} onChange={(event) => setDraft({ ...draft, sort_order: Number(event.target.value) || 0 })} />
          <div className="knowledge-status"><span>当前状态</span>{isDeleted ? <Badge tone="slate" dot>已删除</Badge> : <Badge tone={faqTone(draft.status)} dot>{faqLabels[draft.status]}</Badge>}</div>
          <div className="knowledge-actions">{canWrite && !isDeleted && <Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存"}</Button>}{canWrite && draft.id && !isDeleted && <Button type="button" variant="secondary" disabled={saving} onClick={() => void togglePublish()}>{draft.status === "published" ? "下架" : "上架"}</Button>}{canWrite && draft.id && !isDeleted && <Button type="button" variant="danger" disabled={saving} onClick={() => void remove()}>删除</Button>}{canWrite && draft.id && isDeleted && <Button type="button" disabled={saving} onClick={() => void restore()}>{saving ? "恢复中…" : "恢复为草稿"}</Button>}</div>
          {isDeleted && <p className="knowledge-footnote">已删除的 FAQ 不进入公开接口；恢复后回到草稿状态，需要重新上架。</p>}
          {!canWrite && <p className="knowledge-footnote">当前账号只能查看 FAQ，不能修改。</p>}
        </form> : <EmptyLive message={loading ? "正在加载…" : "新增一条 FAQ 后会显示在这里。"} />}
      </Panel>
    </div>
  </div>;
}

export function MaterialsLiveWorkspace({ projectId, canRead, canWrite, onNotice }: WorkspaceProps) {
  const [items, setItems] = useState<MaterialRecord[]>([]);
  const [draft, setDraft] = useState<MaterialRecord | null>(null);
  const [query, setQuery] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<MaterialRecord["category"]>("document");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [loadedProject, setLoadedProject] = useState("");
  const [loadError, setLoadError] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const targetProject = projectId === "all" ? "" : projectId;
  const loading = loadedProject !== targetProject;

  useEffect(() => {
    if (!canRead || !targetProject) return;
    let active = true;
    workbenchClient.materials(targetProject)
      .then((result) => { if (active) { setItems(result.data); setDraft((current) => current && result.data.some((item) => item.id === current.id) ? current : result.data[0] ?? null); setLoadError(""); } })
      .catch((cause) => { if (active) { setLoadError(cause instanceof Error ? cause.message : "素材加载失败"); onNotice(cause instanceof Error ? cause.message : "素材加载失败"); } })
      // 失败也要收尾，否则 loading 永远为真、列表一直显示「正在加载」
      .finally(() => { if (active) setLoadedProject(targetProject); });
    return () => { active = false; };
  }, [canRead, targetProject, reloadToken, onNotice]);

  const visible = useMemo(() => items.filter((item) =>
    `${item.title} ${item.description ?? ""} ${item.file_name}`.toLowerCase().includes(query.toLowerCase()),
  ), [items, query]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canWrite || !targetProject) return;
    if (!title.trim() || !file) { onNotice("请填写素材名称并选择文件"); return; }
    setSaving(true);
    const form = new FormData();
    form.set("title", title.trim());
    form.set("category", category);
    if (description.trim()) form.set("description", description.trim());
    form.set("file", file);
    try {
      const created = await workbenchClient.uploadMaterial(targetProject, form);
      setItems((current) => [created, ...current]);
      setDraft(created);
      setTitle("");
      setDescription("");
      setFile(null);
      onNotice("素材已上传到服务器");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "素材上传失败");
    } finally {
      setSaving(false);
    }
  }

  async function saveMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || !canWrite || !targetProject) return;
    if (!draft.title.trim()) { onNotice("请填写素材名称"); return; }
    setSaving(true);
    try {
      const updated = await workbenchClient.updateMaterial(targetProject, draft.id, {
        title: draft.title.trim(),
        category: draft.category,
        description: draft.description?.trim() || null,
      });
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
      setDraft(updated);
      onNotice("素材信息已保存");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "素材保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有素材查看权限。</p></Panel>;
  if (!targetProject) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先在上方选择具体项目，素材按项目维护。</p></Panel>;

  return <div className="knowledge-workspace">
    <div className="knowledge-grid">
      <Panel className="knowledge-list-panel">
        <div className="panel-heading"><div><h3>素材库</h3><p>真实接口 · 文件由服务端存到受控目录</p></div><Badge tone="blue">{items.length} 条</Badge></div>
        <div className="knowledge-toolbar"><div className="search-field"><Icon name="search" size={16}/><input aria-label="搜索素材" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称或文件" /></div></div>
        <div className="knowledge-list">{visible.map((item) => <button key={item.id} className={`knowledge-item ${draft?.id === item.id ? "selected" : ""}`} onClick={() => setDraft({ ...item })}><span className="material-icon"><Icon name={item.category === "image" ? "eye" : "folder"} size={19}/></span><span><strong>{item.title}</strong><small>{item.file_name} · {formatBytes(item.byte_size)}</small></span><Badge tone="blue">{materialLabels[item.category]}</Badge></button>)}{!visible.length && !loading && loadError && <div className="knowledge-empty"><strong>素材加载失败</strong><p>{loadError}</p><Button variant="secondary" onClick={() => { setLoadError(""); setReloadToken((value) => value + 1); }}>重新加载</Button></div>}{!visible.length && !loading && !loadError && <p className="knowledge-empty">暂无素材</p>}{loading && <p className="knowledge-empty">正在加载素材…</p>}</div>
      </Panel>
      <div className="knowledge-side-stack">
        {draft && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>{draft.title}</h3><p>{draft.file_name} · {formatBytes(draft.byte_size)}</p></div><Icon name="folder" size={20}/></div>
          <form onSubmit={saveMetadata}>
            <TextInput label="素材名称" value={draft.title} disabled={!canWrite} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
            <SelectInput label="分类" value={draft.category} disabled={!canWrite} onChange={(event) => setDraft({ ...draft, category: event.target.value as MaterialRecord["category"] })}><option value="image">图片</option><option value="document">文档</option><option value="case">案例</option></SelectInput>
            <label className="field"><span className="field-label">说明</span><textarea className="text-input knowledge-textarea short" value={draft.description ?? ""} disabled={!canWrite} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
            <p className="knowledge-footnote">校验值：{draft.checksum.slice(0, 16)}…</p>
            <div className="knowledge-actions">{canWrite && <Button type="submit" disabled={saving}>保存素材信息</Button>}<Button type="button" variant="secondary" onClick={() => void workbenchClient.downloadMaterial(targetProject, draft.id).catch((cause) => onNotice(cause instanceof Error ? cause.message : "下载失败"))}>下载文件</Button></div>
          </form>
        </Panel>}
        {canWrite && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>上传新素材</h3><p>支持图片、PDF、Office 文档、文本、zip，单文件 20MB 内</p></div><Icon name="plus" size={20}/></div>
          <form onSubmit={upload}>
            <TextInput label="素材名称" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：2026 招生简章" />
            <SelectInput label="分类" value={category} onChange={(event) => setCategory(event.target.value as MaterialRecord["category"])}><option value="document">文档</option><option value="image">图片</option><option value="case">案例</option></SelectInput>
            <label className="field"><span className="field-label">说明</span><textarea className="text-input knowledge-textarea short" value={description} onChange={(event) => setDescription(event.target.value)} /></label>
            <label className="field"><span className="field-label">文件</span><input className="text-input" type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
            <div className="knowledge-actions"><Button type="submit" disabled={saving}>{saving ? "上传中…" : "上传素材"}</Button></div>
          </form>
        </Panel>}
      </div>
    </div>
  </div>;
}
