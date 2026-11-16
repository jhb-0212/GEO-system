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

function EmptyLive({ message }: { message: string }) {
  return <div className="knowledge-empty editor-empty"><Icon name="folder" size={28}/><strong>暂无真实记录</strong><p>{message}</p></div>;
}

export function FaqLiveWorkspace({ projectId, canRead, canWrite, onNotice }: WorkspaceProps) {
  const [items, setItems] = useState<FaqRecord[]>([]);
  const [draft, setDraft] = useState<FaqRecord | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [saving, setSaving] = useState(false);
  const [loadedKey, setLoadedKey] = useState("");

  const targetProject = projectId === "all" ? "" : projectId;
  const loadKey = `${targetProject}:${filter}`;
  const loading = loadedKey !== loadKey;

  useEffect(() => {
    if (!canRead || !targetProject) return;
    let active = true;
    workbenchClient.faqs(targetProject, filter === "all" ? undefined : filter)
      .then((result) => {
        if (!active) return;
        setItems(result.data);
        setDraft((current) => current && result.data.some((item) => item.id === current.id) ? current : result.data[0] ?? null);
        setLoadedKey(loadKey);
      })
      .catch((cause) => { if (active) onNotice(cause instanceof Error ? cause.message : "FAQ 加载失败"); });
    return () => { active = false; };
  }, [canRead, targetProject, filter, loadKey, onNotice]);

  const visible = useMemo(() => items.filter((item) =>
    `${item.question} ${item.answer}`.toLowerCase().includes(query.toLowerCase()),
  ), [items, query]);

  function startNew() {
    if (!canWrite) { onNotice("当前账号没有内容编辑权限"); return; }
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
        setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
        setDraft(updated);
      } else {
        const created = await workbenchClient.createFaq(targetProject, {
          question: record.question.trim(),
          answer: record.answer.trim(),
          category: record.category?.trim() || null,
          status: status ?? record.status,
          sort_order: record.sort_order,
        });
        const result = await workbenchClient.faqs(targetProject);
        setItems(result.data);
        setDraft(result.data.find((item) => item.id === created.id) ?? result.data[0] ?? null);
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
    if (!window.confirm("确认删除这条 FAQ？删除后状态变为已下架，可在“已下架”中查看。")) return;
    setSaving(true);
    try {
      const updated = await workbenchClient.deleteFaq(targetProject, draft.id);
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
      setDraft(updated);
      onNotice("FAQ 已软删，状态改为已下架");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "FAQ 删除失败");
    } finally {
      setSaving(false);
    }
  }

  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有 FAQ 查看权限。</p></Panel>;
  if (!targetProject) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先在上方选择具体项目，FAQ 按项目维护。</p></Panel>;

  return <div className="knowledge-workspace">
    <div className="knowledge-grid">
      <Panel className="knowledge-list-panel">
        <div className="panel-heading"><div><h3>FAQ 列表</h3><p>真实接口 · 已上架条目会进入公开只读接口</p></div><Badge tone="blue">{items.length} 条</Badge></div>
        <div className="knowledge-toolbar"><div className="search-field"><Icon name="search" size={16}/><input aria-label="搜索 FAQ" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索问题或答案" /></div><select className="knowledge-filter" aria-label="筛选 FAQ 状态" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">全部状态</option><option value="draft">草稿</option><option value="published">已上架</option><option value="unpublished">已下架</option></select></div>
        <div className="knowledge-list">{visible.map((item) => <button key={item.id} className={`knowledge-item ${draft?.id === item.id ? "selected" : ""}`} onClick={() => setDraft({ ...item })}><span><strong>{item.question}</strong><small>{item.updated_at ? item.updated_at.slice(0, 10) : "未保存"}{item.category ? ` · ${item.category}` : ""} · 排序 {item.sort_order}</small></span><Badge tone={faqTone(item.status)}>{faqLabels[item.status]}</Badge></button>)}{!visible.length && !loading && <p className="knowledge-empty">当前筛选下没有 FAQ</p>}{loading && <p className="knowledge-empty">正在加载 FAQ…</p>}</div>
        <div className="knowledge-panel-foot"><span>{visible.length} 条真实记录</span>{canWrite && <Button variant="secondary" icon="plus" onClick={startNew}>新增 FAQ</Button>}</div>
      </Panel>
      <Panel className="knowledge-editor-panel">
        <div className="panel-heading"><div><h3>{draft?.id ? "编辑 FAQ" : "新增 FAQ"}</h3><p>保存后由后端校验权限并写审计</p></div><Icon name="blocks" size={20}/></div>
        {draft ? <form onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); void save(); }}>
          <TextInput label="问题" value={draft.question} onChange={(event) => setDraft({ ...draft, question: event.target.value })} placeholder="输入客户经常提出的问题" />
          <TextInput label="分类（可选）" value={draft.category ?? ""} onChange={(event) => setDraft({ ...draft, category: event.target.value })} placeholder="例如：到校、报名、课程" />
          <label className="field"><span className="field-label">答案</span><textarea className="text-input knowledge-textarea" value={draft.answer} onChange={(event) => setDraft({ ...draft, answer: event.target.value })} placeholder="输入准备发布的回答" /></label>
          <TextInput label="排序（越小越靠前）" type="number" value={String(draft.sort_order)} onChange={(event) => setDraft({ ...draft, sort_order: Number(event.target.value) || 0 })} />
          <div className="knowledge-status"><span>当前状态</span><Badge tone={faqTone(draft.status)} dot>{faqLabels[draft.status]}</Badge></div>
          <div className="knowledge-actions">{canWrite && <Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存"}</Button>}{canWrite && draft.id && <Button type="button" variant="secondary" disabled={saving} onClick={() => void save(draft.status === "published" ? "unpublished" : "published")}>{draft.status === "published" ? "下架" : "上架"}</Button>}{canWrite && draft.id && draft.status !== "published" && <Button type="button" variant="danger" disabled={saving} onClick={() => void remove()}>删除（软删）</Button>}</div>
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
  const targetProject = projectId === "all" ? "" : projectId;
  const loading = loadedProject !== targetProject;

  useEffect(() => {
    if (!canRead || !targetProject) return;
    let active = true;
    workbenchClient.materials(targetProject)
      .then((result) => { if (active) { setItems(result.data); setDraft((current) => current && result.data.some((item) => item.id === current.id) ? current : result.data[0] ?? null); setLoadedProject(targetProject); } })
      .catch((cause) => { if (active) onNotice(cause instanceof Error ? cause.message : "素材加载失败"); });
    return () => { active = false; };
  }, [canRead, targetProject, onNotice]);

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
        <div className="knowledge-list">{visible.map((item) => <button key={item.id} className={`knowledge-item ${draft?.id === item.id ? "selected" : ""}`} onClick={() => setDraft({ ...item })}><span className="material-icon"><Icon name={item.category === "image" ? "eye" : "folder"} size={19}/></span><span><strong>{item.title}</strong><small>{item.file_name} · {formatBytes(item.byte_size)}</small></span><Badge tone="blue">{materialLabels[item.category]}</Badge></button>)}{!visible.length && !loading && <p className="knowledge-empty">暂无素材</p>}{loading && <p className="knowledge-empty">正在加载素材…</p>}</div>
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
