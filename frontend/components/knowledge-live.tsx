"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Badge, Button, DetailModal, Icon, Panel, SelectInput, TextInput } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import { formatDateTime } from "@/lib/workbench/format";
import type { FaqRecord, MaterialRecord, Project, Tone } from "@/lib/workbench/types";

interface WorkspaceProps {
  mode: "mock" | "live";
  projectId: string;
  projects: Project[];
  canRead: boolean;
  canWrite: boolean;
  canReview?: boolean;
  onNotice: (message: string) => void;
}

const faqLabels: Record<FaqRecord["status"], string> = {
  draft: "草稿",
  pending_review: "待审核",
  rejected: "已驳回",
  published: "已上架",
  unpublished: "已下架",
};

const materialLabels: Record<MaterialRecord["category"], string> = {
  image: "图片",
  video: "视频",
  document: "文档",
  case: "案例",
};

function faqTone(status: FaqRecord["status"]): Tone {
  if (status === "published") return "green";
  if (status === "unpublished") return "slate";
  if (status === "pending_review") return "blue";
  if (status === "rejected") return "red";
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

export function FaqLiveWorkspace({ projectId, canRead, canWrite, canReview = false, onNotice }: WorkspaceProps) {
  const [items, setItems] = useState<FaqRecord[]>([]);
  const [draft, setDraft] = useState<FaqRecord | null>(null);
  const [reviewComment, setReviewComment] = useState("");
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
    const request = filter === "pending_review" && canReview
      ? workbenchClient.faqReviewQueue(targetProject, {
          category: categoryFilter === "all" ? undefined : categoryFilter,
          q: query || undefined,
          page,
          pageSize: FAQ_PAGE_SIZE,
        })
      : workbenchClient.faqs(targetProject, {
          status,
          category: categoryFilter === "all" ? undefined : categoryFilter,
          q: query || undefined,
          page,
          pageSize: FAQ_PAGE_SIZE,
          deleted: filter === "deleted" ? true : undefined,
        });
    request
      .then((result) => {
        if (!active) return;
        setItems(result.data);
        setTotal(result.meta?.total ?? result.data.length);
        if (page === 1) setDraft((current) => current && result.data.some((item) => item.id === current.id) ? current : null);
      })
      .catch((cause) => { if (active) onNotice(cause instanceof Error ? cause.message : "FAQ 加载失败"); })
      .finally(() => { if (active) setLoadedKey(loadKey); });
    return () => { active = false; };
  }, [canRead, canReview, targetProject, filter, categoryFilter, page, query, reloadToken, loadKey, onNotice]);

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

  function selectDraft(item: FaqRecord) {
    setCreatingCategory(false);
    setDraft({ ...item });
    setReviewComment(item.review_comment ?? "");
  }

  function startNew() {
    if (!canWrite) { onNotice("当前账号没有内容编辑权限"); return; }
    setCreatingCategory(false);
    setReviewComment("");
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

  async function save(record = draft) {
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
          sort_order: record.sort_order,
        });
        setDraft(updated);
        setReviewComment(updated.review_comment ?? "");
        refresh();
      } else {
        const created = await workbenchClient.createFaq(targetProject, {
          question: record.question.trim(),
          answer: record.answer.trim(),
          category: record.category?.trim() || null,
          status: "draft",
          sort_order: record.sort_order,
        });
        const result = await workbenchClient.faqs(targetProject, { page: 1, pageSize: 20 });
        setItems(result.data);
        setTotal(result.meta?.total ?? result.data.length);
        const saved = result.data.find((item) => item.id === created.id) ?? result.data[0] ?? null;
        setDraft(saved);
        setReviewComment(saved?.review_comment ?? "");
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

  async function submitReview() {
    if (!draft || !canWrite || !targetProject) return;
    if (!draft.question.trim() || !draft.answer.trim()) { onNotice("请填写问题和答案"); return; }
    setSaving(true);
    try {
      let faqId = draft.id;
      if (faqId) {
        await workbenchClient.updateFaq(targetProject, faqId, {
          question: draft.question.trim(),
          answer: draft.answer.trim(),
          category: draft.category?.trim() || null,
          sort_order: draft.sort_order,
        });
      } else {
        const created = await workbenchClient.createFaq(targetProject, {
          question: draft.question.trim(),
          answer: draft.answer.trim(),
          category: draft.category?.trim() || null,
          status: "draft",
          sort_order: draft.sort_order,
        });
        faqId = created.id;
      }
      const pending = await workbenchClient.submitFaqReview(targetProject, faqId);
      setDraft(pending);
      setReviewComment(pending.review_comment ?? "");
      refresh("pending_review", "all");
      onNotice("FAQ 已提交审核，等待审核角色处理");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "FAQ 提交审核失败");
    } finally {
      setSaving(false);
    }
  }

  async function withdrawReview() {
    if (!draft?.id || !canWrite || !targetProject) return;
    setSaving(true);
    try {
      const updated = await workbenchClient.updateFaq(targetProject, draft.id, { status: "draft" });
      setDraft(updated);
      setReviewComment(updated.review_comment ?? "");
      refresh("draft", "all");
      onNotice("FAQ 已撤回为草稿，可继续修改");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "FAQ 撤回失败");
    } finally {
      setSaving(false);
    }
  }

  async function unpublish() {
    if (!draft?.id || !canWrite || !targetProject || draft.status !== "published") return;
    if (!window.confirm("确认下架这条 FAQ？下架后公开只读接口不再返回它。")) return;
    setSaving(true);
    try {
      const updated = await workbenchClient.updateFaq(targetProject, draft.id, { status: "unpublished" });
      setDraft(updated);
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
      refresh("unpublished", "all");
      onNotice("FAQ 已下架");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "FAQ 下架失败");
    } finally {
      setSaving(false);
    }
  }

  async function review(action: "approve" | "reject") {
    if (!draft?.id || !canReview || draft.status !== "pending_review" || !targetProject) return;
    const comment = reviewComment.trim();
    if (action === "reject" && !comment) { onNotice("驳回 FAQ 必须填写审核意见"); return; }
    if (action === "approve" && !window.confirm("确认通过并上架这条 FAQ？上架后会进入公开只读接口。")) return;
    setSaving(true);
    try {
      const updated = await workbenchClient.reviewFaq(targetProject, draft.id, action, comment || null);
      setDraft(updated);
      setReviewComment(updated.review_comment ?? "");
      refresh(filter === "pending_review" ? "pending_review" : "all", "all");
      onNotice(action === "approve" ? "FAQ 已通过并上架" : "FAQ 已驳回，编辑可修改后重新提交");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "FAQ 审核失败");
    } finally {
      setSaving(false);
    }
  }

  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有 FAQ 查看权限。</p></Panel>;
  if (!targetProject) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先在上方选择具体项目，FAQ 按项目维护。</p></Panel>;

  const isDeleted = Boolean(draft?.deleted_at);
  const isPending = draft?.status === "pending_review";
  const isPublished = draft?.status === "published";
  const contentReadOnly = !canWrite || isDeleted || isPending || isPublished;
  const canEdit = canWrite && !isDeleted && !isPending && !isPublished;
  const canReviewNow = canReview && Boolean(draft?.id) && isPending && !isDeleted;
  const modalTitle = !draft ? "" : !draft.id ? "新增 FAQ" : canReviewNow ? "审核 FAQ" : contentReadOnly ? "查看 FAQ" : "编辑 FAQ";
  const modalSubtitle = !draft ? "" : !draft.id
    ? "保存为草稿后，再提交审核"
    : canReviewNow
      ? "审核角色只判断是否可公开，不修改正文"
      : isDeleted
        ? "该 FAQ 已删除，可恢复为草稿"
        : isPending
          ? "已提交审核，撤回后才能修改正文"
          : isPublished
            ? "已上架内容需先下架再编辑"
            : draft.review_comment
              ? "请按审核意见修改后重新提交"
              : "修改后提交审核，由审核角色发布";

  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading">
        <div><h3>{filter === "pending_review" && canReview ? "FAQ 审核队列" : "FAQ 列表"}</h3><p>{filter === "pending_review" && canReview ? "按提交/更新时间正序，先到先审；通过后进入公司官网" : "已上架内容会展示在公司官网；草稿、待审和下架内容只在内部可见"}</p></div>
        <div className="activity-heading-actions">
          {canReview && <Button variant="secondary" onClick={() => refresh("pending_review", "all")}>审核队列</Button>}
          <Badge tone={filter === "pending_review" ? "amber" : "blue"}>{total} 条</Badge>
          {canWrite && <Button icon="plus" onClick={startNew}>新增 FAQ</Button>}
        </div>
      </div>
      <div className="knowledge-toolbar"><div className="search-field"><Icon name="search" size={16}/><input aria-label="搜索 FAQ" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索问题或答案" /></div><select className="knowledge-filter" aria-label="筛选 FAQ 状态" value={filter} onChange={(event) => refresh(event.target.value, categoryFilter)}><option value="all">全部状态</option><option value="draft">草稿</option><option value="pending_review">待审核</option><option value="rejected">已驳回</option><option value="published">已上架</option><option value="unpublished">已下架</option><option value="deleted">已删除</option></select><select className="knowledge-filter" aria-label="筛选 FAQ 分类" value={categoryFilter} onChange={(event) => refresh(filter, event.target.value)}><option value="all">全部分类</option>{categories.map((category) => <option key={category} value={category}>{category}</option>)}</select></div>
      <div className="knowledge-list">{items.map((item) => <button key={item.id} className={`knowledge-item ${draft?.id === item.id ? "selected" : ""}`} onClick={() => selectDraft(item)}><span><strong>{item.question}</strong><small>{formatDateTime(item.updated_at)}{item.category ? ` · ${item.category}` : ""}{item.sort_order ? ` · 排序 ${item.sort_order}` : ""}</small></span>{item.deleted_at ? <Badge tone="slate">已删除</Badge> : <Badge tone={faqTone(item.status)}>{faqLabels[item.status]}</Badge>}</button>)}{!items.length && !loading && <p className="knowledge-empty">{query ? `没有匹配「${query}」的 FAQ` : filter === "pending_review" && canReview ? "审核队列已清空" : "当前筛选下没有 FAQ"}</p>}{loading && <p className="knowledge-empty">正在加载 FAQ…</p>}</div>
      <div className="knowledge-panel-foot">
        <span>共 {total} 条{total > FAQ_PAGE_SIZE ? ` · 第 ${page} / ${Math.max(1, Math.ceil(total / FAQ_PAGE_SIZE))} 页` : ""}</span>
        {total > FAQ_PAGE_SIZE && <div className="knowledge-panel-foot-actions">
          <Button variant="secondary" disabled={loading || page <= 1} onClick={() => setPage(page - 1)}>上一页</Button>
          <Button variant="secondary" disabled={loading || page * FAQ_PAGE_SIZE >= total} onClick={() => setPage(page + 1)}>下一页</Button>
        </div>}
      </div>
    </Panel>
    {draft && <DetailModal eyebrow="FAQ 详情" title={modalTitle} subtitle={draft.id ? draft.question : modalSubtitle} onClose={() => setDraft(null)}>
      <form onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (canEdit) void save(); }}>
        <TextInput label="问题" value={draft.question} disabled={contentReadOnly} maxLength={QUESTION_MAX} onChange={(event) => setDraft({ ...draft, question: event.target.value })} placeholder="输入客户经常提出的问题" />
        <p className="knowledge-footnote">问题字数 {draft.question.length} / {QUESTION_MAX}</p>
        {canEdit && categories.length > 0 && !creatingCategory
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
          : <TextInput label={creatingCategory ? "新分类名称" : "分类（可选）"} value={draft.category ?? ""} disabled={contentReadOnly} maxLength={CATEGORY_MAX} onChange={(event) => setDraft({ ...draft, category: event.target.value })} placeholder={creatingCategory ? "输入新分类，例如：食宿" : "例如：到校、报名、课程"} />}
        <label className="field"><span className="field-label">答案</span><textarea className="text-input knowledge-textarea" value={draft.answer} disabled={contentReadOnly} maxLength={ANSWER_MAX} onChange={(event) => setDraft({ ...draft, answer: event.target.value })} placeholder="输入准备发布的回答" /></label>
        <p className="knowledge-footnote">答案字数 {draft.answer.length} / {ANSWER_MAX}</p>
        <TextInput label="排序（越小越靠前）" type="number" min={0} max={9999} value={String(draft.sort_order)} disabled={contentReadOnly} onChange={(event) => setDraft({ ...draft, sort_order: Number(event.target.value) || 0 })} />
        <div className="knowledge-status"><span>当前状态</span>{isDeleted ? <Badge tone="slate" dot>已删除</Badge> : <Badge tone={faqTone(draft.status)} dot>{faqLabels[draft.status]}</Badge>}</div>
        {draft.review_comment && <div className="knowledge-notice" role="note"><Icon name="info" size={18}/><div><strong>{isPending ? "上一轮审核意见" : "审核意见"}</strong><p>{draft.review_comment}</p>{draft.reviewed_at && <small>审核时间：{formatDateTime(draft.reviewed_at)}</small>}</div></div>}
        {canReviewNow && <label className="field"><span className="field-label">审核意见（驳回必填）</span><textarea className="text-input knowledge-textarea short" value={reviewComment} maxLength={5000} onChange={(event) => setReviewComment(event.target.value)} placeholder="通过可补充说明；驳回必须写清需要修改的内容" /></label>}
        <div className="knowledge-actions">
          {canEdit && <Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存"}</Button>}
          {canEdit && (!draft.id || ["draft", "rejected", "unpublished"].includes(draft.status)) && <Button type="button" variant="secondary" disabled={saving} onClick={() => void submitReview()}>{draft.id ? "提交审核" : "保存并提交审核"}</Button>}
          {canWrite && draft.id && isPending && !isDeleted && <Button type="button" variant="secondary" disabled={saving} onClick={() => void withdrawReview()}>撤回审核</Button>}
          {canWrite && draft.id && isPublished && !isDeleted && <Button type="button" variant="secondary" disabled={saving} onClick={() => void unpublish()}>下架</Button>}
          {canWrite && draft.id && !isDeleted && <Button type="button" variant="danger" disabled={saving} onClick={() => void remove()}>删除</Button>}
          {canWrite && draft.id && isDeleted && <Button type="button" disabled={saving} onClick={() => void restore()}>{saving ? "恢复中…" : "恢复为草稿"}</Button>}
          {canReviewNow && <Button type="button" disabled={saving} onClick={() => void review("approve")}>通过并上架</Button>}
          {canReviewNow && <Button type="button" variant="danger" disabled={saving} onClick={() => void review("reject")}>驳回</Button>}
        </div>
        {isDeleted && <p className="knowledge-footnote">已删除的 FAQ 不会出现在公司官网；恢复后需要重新提交审核。</p>}
        {isPending && canWrite && <p className="knowledge-footnote">已提交审核，撤回后才能修改正文。</p>}
        {isPublished && canWrite && <p className="knowledge-footnote">已上架内容需先下架再编辑；重新上架需要再次审核。</p>}
        {draft.status === "rejected" && canEdit && <p className="knowledge-footnote">请按审核意见修改后重新提交审核。</p>}
        {!canWrite && canReview && <p className="knowledge-footnote">审核角色只能审核，不能修改正文。</p>}
        {!canWrite && !canReview && <p className="knowledge-footnote">当前账号只能查看 FAQ，不能修改。</p>}
      </form>
    </DetailModal>}
  </div>;
}

export function MaterialsLiveWorkspace({ projectId, canRead, canWrite, onNotice }: WorkspaceProps) {
  const [items, setItems] = useState<MaterialRecord[]>([]);
  const [draft, setDraft] = useState<MaterialRecord | null>(null);
  const [query, setQuery] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<MaterialRecord["category"]>("image");
  const [groupName, setGroupName] = useState("");
  const [source, setSource] = useState("");
  const [sortOrder, setSortOrder] = useState("0");
  const [description, setDescription] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<"all" | MaterialRecord["category"]>("all");
  const [groupFilter, setGroupFilter] = useState("all");
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
      .then((result) => { if (active) { setItems(result.data); setDraft((current) => current && result.data.some((item) => item.id === current.id) ? current : null); setLoadError(""); } })
      .catch((cause) => { if (active) { setLoadError(cause instanceof Error ? cause.message : "素材加载失败"); onNotice(cause instanceof Error ? cause.message : "素材加载失败"); } })
      // 失败也要收尾，否则 loading 永远为真、列表一直显示「正在加载」
      .finally(() => { if (active) setLoadedProject(targetProject); });
    return () => { active = false; };
  }, [canRead, targetProject, reloadToken, onNotice]);

  const groups = useMemo(() => Array.from(new Set(items.map((item) => item.group_name || "未分组"))).sort((a, b) => a.localeCompare(b, "zh")), [items]);

  const counts = useMemo(() => ({
    image: items.filter((item) => item.category === "image").length,
    video: items.filter((item) => item.category === "video").length,
    document: items.filter((item) => item.category === "document").length,
    case: items.filter((item) => item.category === "case").length,
  }), [items]);

  const filtered = useMemo(() => items.filter((item) => {
    const text = `${item.title} ${item.description ?? ""} ${item.file_name} ${item.source ?? ""}`.toLowerCase();
    if (!text.includes(query.toLowerCase())) return false;
    if (categoryFilter !== "all" && item.category !== categoryFilter) return false;
    if (groupFilter !== "all" && (item.group_name || "未分组") !== groupFilter) return false;
    return true;
  }), [items, query, categoryFilter, groupFilter]);

  // 分组视图：组内按 sort_order 升序，同值再按上传时间倒序，和后端排序口径一致。
  const sections = useMemo(() => {
    const map = new Map<string, MaterialRecord[]>();
    for (const item of filtered) {
      const key = item.group_name || "未分组";
      map.set(key, [...(map.get(key) ?? []), item]);
    }
    return Array.from(map.entries())
      .map(([name, rows]) => [name, [...rows].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")))] as const)
      .sort((a, b) => a[0].localeCompare(b[0], "zh"));
  }, [filtered]);

  function previewUrl(id: string) {
    return `/internal/workbench/materials/${encodeURIComponent(id)}/preview?project_id=${encodeURIComponent(targetProject)}`;
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canWrite || !targetProject) return;
    if (!title.trim() || !file) { onNotice("请填写素材名称并选择文件"); return; }
    setSaving(true);
    const form = new FormData();
    form.set("title", title.trim());
    form.set("category", category);
    if (groupName.trim()) form.set("group_name", groupName.trim());
    if (source.trim()) form.set("source", source.trim());
    form.set("sort_order", String(Number(sortOrder) || 0));
    if (description.trim()) form.set("description", description.trim());
    form.set("file", file);
    try {
      const created = await workbenchClient.uploadMaterial(targetProject, form);
      setItems((current) => [created, ...current]);
      setDraft(created);
      setUploadOpen(false);
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
        group_name: draft.group_name?.trim() || null,
        source: draft.source?.trim() || null,
        sort_order: Number(draft.sort_order ?? 0),
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

  return <div className="asset-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading">
        <div><h3>素材库</h3><p>按分组归档图片与成片；视频只做存档，不做在线剪辑</p></div>
        <div className="activity-heading-actions"><Badge tone="blue">{items.length} 条</Badge>{canWrite && <Button icon="plus" onClick={() => setUploadOpen(true)}>上传素材</Button>}</div>
      </div>
      <div className="asset-stat-strip">
        <button type="button" className={`asset-stat ${categoryFilter === "all" ? "active" : ""}`} onClick={() => setCategoryFilter("all")}><strong>{items.length}</strong><span>全部素材</span></button>
        <button type="button" className={`asset-stat ${categoryFilter === "image" ? "active" : ""}`} onClick={() => setCategoryFilter("image")}><strong>{counts.image}</strong><span>图片</span></button>
        <button type="button" className={`asset-stat ${categoryFilter === "video" ? "active" : ""}`} onClick={() => setCategoryFilter("video")}><strong>{counts.video}</strong><span>视频</span></button>
        <button type="button" className={`asset-stat ${categoryFilter === "document" ? "active" : ""}`} onClick={() => setCategoryFilter("document")}><strong>{counts.document}</strong><span>文档</span></button>
        <button type="button" className={`asset-stat ${categoryFilter === "case" ? "active" : ""}`} onClick={() => setCategoryFilter("case")}><strong>{counts.case}</strong><span>案例</span></button>
        <div className="asset-group-filter">
          <label className="field"><span className="field-label">分组</span>
            <select className="text-input" value={groupFilter} onChange={(event) => setGroupFilter(event.target.value)}>
              <option value="all">全部分组（{groups.length}）</option>
              {groups.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
        </div>
      </div>
      <div className="knowledge-toolbar"><div className="search-field"><Icon name="search" size={16}/><input aria-label="搜索素材" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称、文件名或来源" /></div></div>
      <div className="asset-groups">
        {sections.map(([name, rows]) => (
          <section key={name} className="asset-group">
            <header className="asset-group-head"><strong>{name}</strong><span>{rows.length} 项</span></header>
            <div className="asset-grid">
              {rows.map((item) => (
                <button key={item.id} type="button" className={`asset-card ${draft?.id === item.id ? "selected" : ""}`} onClick={() => setDraft({ ...item })}>
                  <span className="asset-thumb">
                    {item.category === "image" || item.category === "case"
                      // 预览走鉴权代理、按会话临时签发，next/image 的优化器拿不到 Cookie，只能用原生 img
                      // eslint-disable-next-line @next/next/no-img-element
                      ? <img src={previewUrl(item.id)} alt={item.title} loading="lazy" />
                      : item.category === "video"
                        ? <video src={previewUrl(item.id)} preload="metadata" muted playsInline />
                        : <Icon name="folder" size={22} />}
                    <span className={`asset-tag ${item.category}`}>{materialLabels[item.category]}</span>
                  </span>
                  <span className="asset-meta"><strong>{item.title}</strong><small>{item.file_name} · {formatBytes(item.byte_size)}</small>{item.source && <small className="asset-source">来源：{item.source}</small>}</span>
                </button>
              ))}
            </div>
          </section>
        ))}
        {!sections.length && !loading && loadError && <div className="knowledge-empty"><strong>素材加载失败</strong><p>{loadError}</p><Button variant="secondary" onClick={() => { setLoadError(""); setReloadToken((value) => value + 1); }}>重新加载</Button></div>}
        {!sections.length && !loading && !loadError && <p className="knowledge-empty">{items.length ? "当前筛选下没有素材" : "暂无素材，先上传一张图片试试"}</p>}
        {loading && <p className="knowledge-empty">正在加载素材…</p>}
      </div>
      <div className="knowledge-panel-foot"><span>共 {items.length} 条 · {groups.length} 个分组</span><span>点击卡片查看详情</span></div>
    </Panel>
    {draft && <DetailModal eyebrow="素材详情" title={draft.title} subtitle={`${draft.file_name} · ${formatBytes(draft.byte_size)}`} onClose={() => setDraft(null)}>
      <form onSubmit={saveMetadata}>
        <div className="asset-detail-preview">
          {draft.category === "image" || draft.category === "case"
            // 同上：鉴权预览地址交给原生 img
            // eslint-disable-next-line @next/next/no-img-element
            ? <img src={previewUrl(draft.id)} alt={draft.title} />
            : draft.category === "video"
              ? <video src={previewUrl(draft.id)} controls preload="metadata" />
              : <p className="knowledge-footnote">该素材不支持在线预览，可下载后查看。</p>}
        </div>
        <TextInput label="素材名称" value={draft.title} disabled={!canWrite} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
        <SelectInput label="分类" value={draft.category} disabled={!canWrite} onChange={(event) => setDraft({ ...draft, category: event.target.value as MaterialRecord["category"] })}><option value="image">图片</option><option value="video">视频</option><option value="document">文档</option><option value="case">案例</option></SelectInput>
        <div className="form-grid">
          <TextInput label="所属分组" value={draft.group_name ?? ""} disabled={!canWrite} placeholder="例如：校区环境" onChange={(event) => setDraft({ ...draft, group_name: event.target.value })} />
          <TextInput label="来源" value={draft.source ?? ""} disabled={!canWrite} placeholder="例如：门店采集" onChange={(event) => setDraft({ ...draft, source: event.target.value })} />
          <TextInput label="组内排序" type="number" min={0} max={100000} value={draft.sort_order ?? 0} disabled={!canWrite} onChange={(event) => setDraft({ ...draft, sort_order: Number(event.target.value) || 0 })} />
        </div>
        <label className="field"><span className="field-label">说明</span><textarea className="text-input knowledge-textarea short" value={draft.description ?? ""} disabled={!canWrite} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
        <div className="knowledge-actions">{canWrite && <Button type="submit" disabled={saving}>保存素材信息</Button>}<Button type="button" variant="secondary" onClick={() => void workbenchClient.downloadMaterial(targetProject, draft.id).catch((cause) => onNotice(cause instanceof Error ? cause.message : "下载失败"))}>下载原文件</Button></div>
      </form>
    </DetailModal>}
    {uploadOpen && canWrite && <DetailModal eyebrow="上传素材" title="上传新素材" subtitle="图片 20MB 内，mp4/mov 成片 100MB 内；分类与文件类型必须一致" onClose={() => setUploadOpen(false)}>
      <form onSubmit={upload}>
        <TextInput label="素材名称" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：校区前台实拍" />
        <div className="form-grid">
          <SelectInput label="分类" value={category} onChange={(event) => setCategory(event.target.value as MaterialRecord["category"])}><option value="image">图片</option><option value="video">视频</option><option value="document">文档</option><option value="case">案例</option></SelectInput>
          <TextInput label="所属分组" value={groupName} onChange={(event) => setGroupName(event.target.value)} placeholder="例如：校区环境" />
          <TextInput label="来源" value={source} onChange={(event) => setSource(event.target.value)} placeholder="例如：门店采集" />
          <TextInput label="组内排序" type="number" min={0} max={100000} value={sortOrder} onChange={(event) => setSortOrder(event.target.value)} />
        </div>
        <label className="field"><span className="field-label">说明</span><textarea className="text-input knowledge-textarea short" value={description} onChange={(event) => setDescription(event.target.value)} /></label>
        <label className="field"><span className="field-label">文件</span><input className="text-input" type="file" accept="image/*,video/mp4,video/quicktime,.pdf,.doc,.docx,.txt,.md,.csv,.zip" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
        <div className="knowledge-actions"><Button type="submit" disabled={saving}>{saving ? "上传中…" : "上传素材"}</Button><Button type="button" variant="secondary" disabled={saving} onClick={() => setUploadOpen(false)}>取消</Button></div>
      </form>
    </DetailModal>}
  </div>;
}