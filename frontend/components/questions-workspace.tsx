"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, DetailModal, Panel } from "./ui";
import { WorkTabs } from "./work-tabs";
import { workbenchClient } from "@/lib/workbench/client";
import { formatDateTime } from "@/lib/workbench/format";
import type { ContentVersionRecord, KeywordRecord, QuestionRecord, QuestionVersionRecord } from "@/lib/workbench/types";

type QuestionTab = "questions" | "keywords";

function readTab(value: string | null): QuestionTab {
  return value === "keywords" ? "keywords" : "questions";
}

const statusNames = { draft: "草稿", active: "已激活", archived: "已归档" };
const blank = { code: "", title: "", question_type: "general", text: "", audience: "", intent: "", priority: 100 };
const blankKeyword = { name: "", category: "", priority: 100, is_active: true, notes: "", content_version_ids: [] as string[] };
type MetadataDraft = Pick<QuestionRecord, "status" | "audience" | "intent" | "priority">;

export function QuestionsWorkspace({ mode, projectId, canRead, canWrite, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean; onNotice: (message: string) => void;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = readTab(searchParams.get("question_tab"));
  const [questions, setQuestions] = useState<QuestionRecord[]>([]);
  const [keywords, setKeywords] = useState<KeywordRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [keywordTotal, setKeywordTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [keywordPage, setKeywordPage] = useState(1);
  const [versionPage, setVersionPage] = useState(1);
  const [versionTotal, setVersionTotal] = useState(0);
  const [questionStatus, setQuestionStatus] = useState("");
  const [questionType, setQuestionType] = useState("");
  const [keywordCategory, setKeywordCategory] = useState("");
  const [appliedKeywordCategory, setAppliedKeywordCategory] = useState("");
  const [keywordActive, setKeywordActive] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<typeof blank | null>(null);
  const [selected, setSelected] = useState<QuestionRecord | null>(null);
  const [metadataDraft, setMetadataDraft] = useState<MetadataDraft | null>(null);
  const [versions, setVersions] = useState<QuestionVersionRecord[]>([]);
  const [newText, setNewText] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [keywordDraft, setKeywordDraft] = useState({ ...blankKeyword });
  const [editingKeywordId, setEditingKeywordId] = useState<string | null>(null);
  const [keywordCategories, setKeywordCategories] = useState<string[]>([]);
  const [contentVersions, setContentVersions] = useState<ContentVersionRecord[]>([]);

  const refreshQuestions = useCallback(async () => {
    const result = await workbenchClient.questions(projectId, page, questionStatus || undefined, questionType || undefined);
    setQuestions(result.data); setTotal(result.meta?.total ?? result.data.length);
  }, [projectId, page, questionStatus, questionType]);
  const refreshKeywords = useCallback(async () => {
    const result = await workbenchClient.keywords(projectId, keywordPage, appliedKeywordCategory || undefined, keywordActive ? keywordActive === "true" : undefined);
    setKeywords(result.data); setKeywordTotal(result.meta?.total ?? result.data.length);
  }, [projectId, keywordPage, appliedKeywordCategory, keywordActive]);
  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([workbenchClient.questions(projectId, page, questionStatus || undefined, questionType || undefined), workbenchClient.keywords(projectId, keywordPage, appliedKeywordCategory || undefined, keywordActive ? keywordActive === "true" : undefined)])
      .then(([q, k]) => { if (!active) return; setQuestions(q.data); setTotal(q.meta?.total ?? q.data.length); setKeywords(k.data); setKeywordTotal(k.meta?.total ?? k.data.length); setError(""); })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "题库加载失败"); });
    return () => { active = false; };
  }, [mode, canRead, projectId, page, keywordPage, questionStatus, questionType, appliedKeywordCategory, keywordActive]);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([workbenchClient.keywordCategories(projectId), workbenchClient.contentVersionOptions(projectId)])
      .then(([categories, versions]) => { if (active) { setKeywordCategories(categories); setContentVersions(versions.data); } })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "目标词选项加载失败"); });
    return () => { active = false; };
  }, [mode, canRead, projectId]);

  async function saveQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!draft) return; setBusy(true);
    try {
      await workbenchClient.saveQuestion(projectId, { ...draft, audience: draft.audience || null, intent: draft.intent || null });
      setDraft(null); await refreshQuestions(); onNotice("题目已创建");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "创建题目失败"); }
    finally { setBusy(false); }
  }

  async function choose(question: QuestionRecord) {
    setSelected(question); setMetadataDraft({ status: question.status, audience: question.audience, intent: question.intent, priority: question.priority }); setNewText(""); setChangeNote(""); setVersionPage(1);
    try { const result = await workbenchClient.questionVersions(projectId, question.id); setVersions(result.data); setVersionTotal(result.meta?.total ?? result.data.length); setError(""); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "版本加载失败"); }
  }

  async function updateQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected || !metadataDraft) return; setBusy(true);
    try {
      const result = await workbenchClient.saveQuestion(projectId, { ...metadataDraft, audience: metadataDraft.audience?.trim() || null, intent: metadataDraft.intent?.trim() || null }, selected.id);
      setSelected(result); setMetadataDraft({ status: result.status, audience: result.audience, intent: result.intent, priority: result.priority }); await refreshQuestions(); onNotice("题目属性已保存");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "题目更新失败"); }
    finally { setBusy(false); }
  }

  async function appendVersion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected || !newText.trim()) return; setBusy(true);
    try {
      await workbenchClient.addQuestionVersion(projectId, selected.id, newText.trim(), changeNote);
      const [questionList, firstVersions] = await Promise.all([workbenchClient.questions(projectId, page, questionStatus || undefined, questionType || undefined), workbenchClient.questionVersions(projectId, selected.id)]);
      const lastPage = Math.max(1, Math.ceil((firstVersions.meta?.total ?? firstVersions.data.length) / 20));
      const versionList = lastPage > 1 ? await workbenchClient.questionVersions(projectId, selected.id, lastPage) : firstVersions;
      setQuestions(questionList.data); setSelected(questionList.data.find((row) => row.id === selected.id) ?? selected);
      setVersions(versionList.data); setVersionTotal(versionList.meta?.total ?? versionList.data.length); setVersionPage(lastPage); setNewText(""); setChangeNote(""); onNotice("新问法版本已保存，旧版本保留");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "新版本保存失败"); }
    finally { setBusy(false); }
  }

  async function saveKeyword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!keywordDraft.name.trim()) return; setBusy(true);
    try {
      const input = { name: keywordDraft.name.trim(), category: keywordDraft.category.trim() || null,
        priority: keywordDraft.priority, is_active: keywordDraft.is_active, notes: keywordDraft.notes.trim() || null,
        content_version_ids: keywordDraft.content_version_ids };
      if (editingKeywordId) await workbenchClient.updateKeyword(projectId, editingKeywordId, input);
      else await workbenchClient.createKeyword(projectId, input);
      setKeywordDraft({ ...blankKeyword }); setEditingKeywordId(null); await refreshKeywords(); onNotice("目标词已保存");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "目标词保存失败"); }
    finally { setBusy(false); }
  }

  async function deactivateKeyword(id: string) {
    if (!canWrite) return;
    setBusy(true);
    try { await workbenchClient.deactivateKeyword(projectId, id); await refreshKeywords(); onNotice("目标词已停用，历史关联保留"); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "目标词停用失败"); }
    finally { setBusy(false); }
  }

  async function changeVersionPage(nextPage: number) {
    if (!selected) return;
    try { const result = await workbenchClient.questionVersions(projectId, selected.id, nextPage);
      setVersions(result.data); setVersionTotal(result.meta?.total ?? result.data.length); setVersionPage(nextPage); setError(""); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "版本加载失败"); }
  }

  function selectTab(tab: QuestionTab) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("section", "questions");
    if (projectId && projectId !== "all") params.set("project_id", projectId);
    if (tab === "questions") params.delete("question_tab");
    else params.set("question_tab", tab);
    router.push(`/workbench?${params.toString()}`, { scroll: false });
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">题库管理请切换到真实接口模式。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有题库查看权限。</p></Panel>;
  const tabs: { id: QuestionTab; label: string; count: number }[] = [
    { id: "questions", label: "监测题库", count: total },
    { id: "keywords", label: "目标词", count: keywordTotal },
  ];
  return <div className="knowledge-workspace">
    <WorkTabs items={tabs} active={activeTab} onChange={selectTab} ariaLabel="监测问题与关键词视图"/>
    {activeTab === "questions" && <>
    <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>监测题库</h3><p>共 {total} 题；正文修改会新建版本</p></div>{canWrite && <Button icon="plus" onClick={() => setDraft({ ...blank })}>新建题目</Button>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="knowledge-actions"><label className="field"><span className="field-label">状态筛选</span><select className="text-input" value={questionStatus} onChange={(e) => { setPage(1); setQuestionStatus(e.target.value); }}><option value="">全部状态</option><option value="draft">草稿</option><option value="active">已激活</option><option value="archived">已归档</option></select></label><label className="field"><span className="field-label">题型筛选</span><select className="text-input" value={questionType} onChange={(e) => { setPage(1); setQuestionType(e.target.value); }}><option value="">全部题型</option><option value="brand">品牌题</option><option value="general">通用题</option></select></label></div>
      <div className="knowledge-list">{questions.map((question) => <button type="button" className="knowledge-item" key={question.id} onClick={() => void choose(question)}><span><strong>{question.code} · {question.title}</strong><small>{question.current_text || "当前版本缺失"}</small></span><Badge tone={question.status === "active" ? "green" : "amber"}>{statusNames[question.status]}</Badge></button>)}{!questions.length && <p className="knowledge-empty">暂无题目</p>}</div>
      {total > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><span>{page} / {Math.ceil(total / 20)}</span><Button variant="secondary" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>下一页</Button></div>}
    </Panel>
    {draft && <Panel className="knowledge-editor-panel"><div className="panel-heading"><h3>新建题目</h3></div><form onSubmit={saveQuestion}>
      <label className="field"><span className="field-label">代码</span><input className="text-input" required maxLength={32} pattern="[A-Za-z0-9][A-Za-z0-9_-]*" value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })}/></label>
      <label className="field"><span className="field-label">标题</span><input className="text-input" required maxLength={255} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })}/></label>
      <label className="field"><span className="field-label">类型</span><select className="text-input" value={draft.question_type} onChange={(e) => setDraft({ ...draft, question_type: e.target.value })}><option value="general">通用题</option><option value="brand">品牌题</option></select></label>
      <label className="field"><span className="field-label">初版问法</span><textarea className="text-input knowledge-textarea short" required value={draft.text} onChange={(e) => setDraft({ ...draft, text: e.target.value })}/></label>
      <label className="field"><span className="field-label">人群</span><input className="text-input" maxLength={128} value={draft.audience} onChange={(e) => setDraft({ ...draft, audience: e.target.value })}/></label>
      <label className="field"><span className="field-label">意图</span><input className="text-input" maxLength={128} value={draft.intent} onChange={(e) => setDraft({ ...draft, intent: e.target.value })}/></label>
      <label className="field"><span className="field-label">优先级</span><input className="text-input" type="number" min={0} required value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: Number(e.target.value) })}/></label>
      <div className="knowledge-actions"><Button type="submit" disabled={busy}>保存题目</Button><Button variant="secondary" onClick={() => setDraft(null)}>取消</Button></div>
    </form></Panel>}
    {selected && <DetailModal eyebrow="QUESTION DETAIL" title={`${selected.code} · ${selected.title}`} subtitle={`当前 v${selected.current_version_no} · ${statusNames[selected.status]}`} onClose={() => setSelected(null)}>
      <p>当前问法：{selected.current_text || "版本缺失"}</p>
      {canWrite && metadataDraft && <><form onSubmit={updateQuestion}>
        <label className="field"><span className="field-label">状态</span><select className="text-input" value={metadataDraft.status} disabled={busy} onChange={(e) => setMetadataDraft({ ...metadataDraft, status: e.target.value as QuestionRecord["status"] })}><option value={selected.status}>{statusNames[selected.status]}</option>{(selected.status === "draft" ? ["active"] : selected.status === "active" ? ["archived"] : ["active"]).map((status) => <option key={status} value={status}>{statusNames[status as QuestionRecord["status"]]}</option>)}</select></label>
        <label className="field"><span className="field-label">人群</span><input className="text-input" maxLength={128} value={metadataDraft.audience ?? ""} onChange={(e) => setMetadataDraft({ ...metadataDraft, audience: e.target.value })}/></label>
        <label className="field"><span className="field-label">意图</span><input className="text-input" maxLength={128} value={metadataDraft.intent ?? ""} onChange={(e) => setMetadataDraft({ ...metadataDraft, intent: e.target.value })}/></label>
        <label className="field"><span className="field-label">优先级</span><input className="text-input" type="number" min={0} required value={metadataDraft.priority} onChange={(e) => setMetadataDraft({ ...metadataDraft, priority: Number(e.target.value) })}/></label>
        <Button type="submit" disabled={busy}>保存题目属性</Button>
      </form><form onSubmit={appendVersion}><label className="field"><span className="field-label">追加问法版本</span><textarea className="text-input knowledge-textarea short" required value={newText} onChange={(e) => setNewText(e.target.value)}/></label><label className="field"><span className="field-label">变更说明</span><input className="text-input" maxLength={2000} value={changeNote} onChange={(e) => setChangeNote(e.target.value)}/></label><Button type="submit" disabled={busy}>新建版本</Button></form></>}
      <div className="knowledge-list">{versions.map((version) => <div className="knowledge-item" key={version.id}><span><strong>v{version.version_no} · {version.text}</strong><small>{version.change_note || "无变更说明"} · {formatDateTime(version.created_at)}</small></span></div>)}{!versions.length && <p className="knowledge-empty">暂无历史版本</p>}</div>
      {versionTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={versionPage <= 1} onClick={() => void changeVersionPage(versionPage - 1)}>上一页</Button><span>{versionPage} / {Math.ceil(versionTotal / 20)}</span><Button variant="secondary" disabled={versionPage * 20 >= versionTotal} onClick={() => void changeVersionPage(versionPage + 1)}>下一页</Button></div>}
    </DetailModal>}
    </>}
    {activeTab === "keywords" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>目标词</h3><p>共 {keywordTotal} 个；可关联已有内容版本</p></div></div>
      <form className="knowledge-actions" onSubmit={(e) => { e.preventDefault(); setKeywordPage(1); setAppliedKeywordCategory(keywordCategory.trim()); }}><label className="field"><span className="field-label">分类筛选</span><select className="text-input" value={keywordCategory} onChange={(e) => setKeywordCategory(e.target.value)}><option value="">全部分类</option>{keywordCategories.map((category) => <option key={category} value={category}>{category}</option>)}</select></label><label className="field"><span className="field-label">启用状态</span><select className="text-input" value={keywordActive} onChange={(e) => { setKeywordPage(1); setKeywordActive(e.target.value); }}><option value="">全部</option><option value="true">已启用</option><option value="false">已停用</option></select></label><Button type="submit" variant="secondary">筛选</Button></form>
      <div className="knowledge-list">{keywords.map((keyword) => <div className="knowledge-item" key={keyword.id}><span><strong>{keyword.name}</strong><small>{keyword.category || "未分类"} · 优先级 {keyword.priority} · 关联 {keyword.content_version_ids?.length ?? 0} 个内容版本</small><small>{keyword.notes || "无备注"}</small></span><div className="knowledge-actions"><Badge tone={keyword.is_active ? "green" : "slate"}>{keyword.is_active ? "启用" : "停用"}</Badge>{canWrite && <><Button variant="secondary" onClick={() => { setEditingKeywordId(keyword.id); setKeywordDraft({ name: keyword.name, category: keyword.category ?? "", priority: keyword.priority, is_active: keyword.is_active, notes: keyword.notes ?? "", content_version_ids: keyword.content_version_ids ?? [] }); }}>编辑</Button>{keyword.is_active && <Button variant="secondary" disabled={busy} onClick={() => void deactivateKeyword(keyword.id)}>停用</Button>}</>}</div></div>)}{!keywords.length && <p className="knowledge-empty">暂无目标词</p>}</div>
      {keywordTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={keywordPage <= 1} onClick={() => setKeywordPage(keywordPage - 1)}>上一页</Button><span>{keywordPage} / {Math.ceil(keywordTotal / 20)}</span><Button variant="secondary" disabled={keywordPage * 20 >= keywordTotal} onClick={() => setKeywordPage(keywordPage + 1)}>下一页</Button></div>}
      {canWrite && <form onSubmit={saveKeyword}><h4>{editingKeywordId ? "编辑目标词" : "新增目标词"}</h4><label className="field"><span className="field-label">名称</span><input className="text-input" required maxLength={128} value={keywordDraft.name} onChange={(e) => setKeywordDraft({ ...keywordDraft, name: e.target.value })}/></label><label className="field"><span className="field-label">分类</span><input className="text-input" maxLength={64} value={keywordDraft.category} onChange={(e) => setKeywordDraft({ ...keywordDraft, category: e.target.value })}/></label><label className="field"><span className="field-label">优先级</span><input className="text-input" type="number" min={0} required value={keywordDraft.priority} onChange={(e) => setKeywordDraft({ ...keywordDraft, priority: Number(e.target.value) })}/></label><label className="field"><span className="field-label">备注</span><textarea className="text-input knowledge-textarea short" maxLength={5000} value={keywordDraft.notes} onChange={(e) => setKeywordDraft({ ...keywordDraft, notes: e.target.value })}/></label><label className="field"><span className="field-label">关联内容版本（可多选）</span><select className="text-input" multiple size={4} value={keywordDraft.content_version_ids} onChange={(e) => setKeywordDraft({ ...keywordDraft, content_version_ids: Array.from(e.target.selectedOptions, (option) => option.value) })}>{contentVersions.map((version) => <option key={version.version_id} value={version.version_id}>{version.title} · v{version.version_no} · {version.status}</option>)}{keywordDraft.content_version_ids.filter((id) => !contentVersions.some((version) => version.version_id === id)).map((id) => <option key={id} value={id}>未在列表的版本</option>)}</select><small className="knowledge-footnote">按住 Ctrl / Command 多选；不选表示解除关联。</small></label><label className="rounds-checkbox"><input type="checkbox" checked={keywordDraft.is_active} onChange={(e) => setKeywordDraft({ ...keywordDraft, is_active: e.target.checked })}/> 启用目标词</label><div className="knowledge-actions"><Button type="submit" disabled={busy}>{editingKeywordId ? "保存修改" : "新增目标词"}</Button>{editingKeywordId && <Button variant="secondary" onClick={() => { setEditingKeywordId(null); setKeywordDraft({ ...blankKeyword }); }}>取消编辑</Button>}</div></form>}
    </Panel>}
  </div>;
}
