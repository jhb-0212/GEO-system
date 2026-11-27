"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, DetailModal, Panel } from "./ui";
import { WorkTabs } from "./work-tabs";
import { workbenchClient } from "@/lib/workbench/client";
import { formatDateTime } from "@/lib/workbench/format";
import type { ContentVersionRecord, KeywordRecord, QuestionCandidateRecord, QuestionRecord, QuestionVersionRecord } from "@/lib/workbench/types";

type QuestionTab = "questions" | "keywords" | "candidates";

function readTab(value: string | null): QuestionTab {
  if (value === "keywords" || value === "candidates") return value;
  return "questions";
}

const statusNames = { draft: "草稿", active: "已激活", archived: "已归档" };
const candidateStatusNames = { pending: "待确认", accepted: "已入题库", rejected: "已驳回" };
const candidateBucketNames = { category: "品类", purchase: "选购", reputation: "口碑" };
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
  const [keywordEditorOpen, setKeywordEditorOpen] = useState(false);
  const [keywordCategories, setKeywordCategories] = useState<string[]>([]);
  const [contentVersions, setContentVersions] = useState<ContentVersionRecord[]>([]);
  const [candidates, setCandidates] = useState<QuestionCandidateRecord[]>([]);
  const [candidateTotal, setCandidateTotal] = useState(0);
  const [candidatePage, setCandidatePage] = useState(1);
  const [candidateStatus, setCandidateStatus] = useState("pending");
  const [candidateBucket, setCandidateBucket] = useState("");
  const [candidateBusy, setCandidateBusy] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [importText, setImportText] = useState("");
  const [importBucket, setImportBucket] = useState("purchase");

  const refreshQuestions = useCallback(async () => {
    const result = await workbenchClient.questions(projectId, page, questionStatus || undefined, questionType || undefined);
    setQuestions(result.data); setTotal(result.meta?.total ?? result.data.length);
  }, [projectId, page, questionStatus, questionType]);
  const refreshKeywords = useCallback(async () => {
    const result = await workbenchClient.keywords(projectId, keywordPage, appliedKeywordCategory || undefined, keywordActive ? keywordActive === "true" : undefined);
    setKeywords(result.data); setKeywordTotal(result.meta?.total ?? result.data.length);
  }, [projectId, keywordPage, appliedKeywordCategory, keywordActive]);
  const refreshCandidates = useCallback(async () => {
    const result = await workbenchClient.questionCandidates(projectId, candidatePage, candidateStatus || undefined, candidateBucket || undefined);
    setCandidates(result.data); setCandidateTotal(result.meta?.total ?? result.data.length);
  }, [projectId, candidatePage, candidateStatus, candidateBucket]);
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

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all" || activeTab !== "candidates") return;
    let active = true;
    workbenchClient.questionCandidates(projectId, candidatePage, candidateStatus || undefined, candidateBucket || undefined)
      .then((result) => { if (!active) return; setCandidates(result.data); setCandidateTotal(result.meta?.total ?? result.data.length); setError(""); })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "候选池加载失败"); });
    return () => { active = false; };
  }, [mode, canRead, projectId, activeTab, candidatePage, candidateStatus, candidateBucket]);

  async function mineCandidates() {
    if (!canWrite) return;
    setCandidateBusy(true);
    try {
      const result = await workbenchClient.mineQuestionCandidates(projectId, 20);
      setCandidatePage(1); await refreshCandidates();
      const missing = result.missing_context.length ? `；缺少：${result.missing_context.join("、")}` : "";
      onNotice(`新增 ${result.created_count} 条候选，跳过重复 ${result.skipped_count} 条${missing}`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "候选挖掘失败"); }
    finally { setCandidateBusy(false); }
  }

  async function importCandidates(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const texts = importText.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
    if (!texts.length) { onNotice("请先粘贴问句，每行一条"); return; }
    setCandidateBusy(true);
    try {
      const result = await workbenchClient.importQuestionCandidates(projectId, texts, importBucket);
      setImportText(""); setShowImport(false); setCandidatePage(1); await refreshCandidates();
      onNotice(`导入 ${result.created_count} 条，跳过重复 ${result.skipped_count} 条`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "候选导入失败"); }
    finally { setCandidateBusy(false); }
  }

  async function acceptCandidate(candidate: QuestionCandidateRecord) {
    if (!canWrite) return;
    setCandidateBusy(true);
    try {
      const result = await workbenchClient.acceptQuestionCandidate(projectId, candidate.id);
      await Promise.all([refreshCandidates(), refreshQuestions()]);
      onNotice(`已采纳为 ${result.question_code}，状态为草稿，确认后再激活`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "采纳候选失败"); }
    finally { setCandidateBusy(false); }
  }

  async function rejectCandidate(candidate: QuestionCandidateRecord) {
    if (!canWrite) return;
    setCandidateBusy(true);
    try {
      await workbenchClient.rejectQuestionCandidate(projectId, candidate.id);
      await refreshCandidates();
      onNotice("候选已驳回，未写入题库");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "驳回候选失败"); }
    finally { setCandidateBusy(false); }
  }

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

  function openKeywordEditor(keyword: KeywordRecord | null) {
    setEditingKeywordId(keyword?.id ?? null);
    setKeywordDraft(keyword ? {
      name: keyword.name, category: keyword.category ?? "", priority: keyword.priority,
      is_active: keyword.is_active, notes: keyword.notes ?? "", content_version_ids: keyword.content_version_ids ?? [],
    } : { ...blankKeyword });
    setKeywordEditorOpen(true);
    if (typeof window !== "undefined") {
      window.setTimeout(() => document.getElementById("keyword-editor")?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 0);
    }
  }

  function toggleKeywordVersion(versionId: string) {
    setKeywordDraft((current) => ({
      ...current,
      content_version_ids: current.content_version_ids.includes(versionId)
        ? current.content_version_ids.filter((id) => id !== versionId)
        : [...current.content_version_ids, versionId],
    }));
  }

  async function saveKeyword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!keywordDraft.name.trim()) return; setBusy(true);
    try {
      const input = { name: keywordDraft.name.trim(), category: keywordDraft.category.trim() || null,
        priority: keywordDraft.priority, is_active: keywordDraft.is_active, notes: keywordDraft.notes.trim() || null,
        content_version_ids: keywordDraft.content_version_ids };
      if (editingKeywordId) await workbenchClient.updateKeyword(projectId, editingKeywordId, input);
      else await workbenchClient.createKeyword(projectId, input);
      setKeywordDraft({ ...blankKeyword }); setEditingKeywordId(null); setKeywordEditorOpen(false); await refreshKeywords(); onNotice("目标词已保存");
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
    { id: "candidates", label: "候选池", count: candidateTotal },
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
    {activeTab === "candidates" && <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>问题候选池</h3><p>共 {candidateTotal} 条；先挖掘/导入，再人工采纳；采纳后只生成草稿题</p></div>{canWrite && <div className="knowledge-actions"><Button disabled={candidateBusy} onClick={() => void mineCandidates()}>从企业资料挖掘</Button><Button variant="secondary" disabled={candidateBusy} onClick={() => setShowImport((open) => !open)}>{showImport ? "收起导入" : "导入外部问句"}</Button></div>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="knowledge-actions">
        <label className="field"><span className="field-label">状态</span><select className="text-input" value={candidateStatus} onChange={(e) => { setCandidatePage(1); setCandidateStatus(e.target.value); }}><option value="">全部</option><option value="pending">待确认</option><option value="accepted">已入题库</option><option value="rejected">已驳回</option></select></label>
        <label className="field"><span className="field-label">桶</span><select className="text-input" value={candidateBucket} onChange={(e) => { setCandidatePage(1); setCandidateBucket(e.target.value); }}><option value="">全部</option><option value="category">品类</option><option value="purchase">选购</option><option value="reputation">口碑</option></select></label>
      </div>
      <div className="knowledge-list">{candidates.map((candidate) => <div className="knowledge-item" key={candidate.id}><span><strong>{candidate.text}</strong><small>{candidateBucketNames[candidate.bucket]} · {candidate.question_type === "brand" ? "品牌题" : "通用题"} · 优先级 {candidate.priority} · {candidate.source === "rule" ? "规则派生" : "外部导入"}</small><small>{candidate.rationale || candidate.source_ref || "无来源说明"}</small></span><div className="knowledge-actions"><Badge tone={candidate.status === "pending" ? "amber" : candidate.status === "accepted" ? "green" : "slate"}>{candidateStatusNames[candidate.status]}</Badge>{canWrite && candidate.status === "pending" && <><Button disabled={candidateBusy} onClick={() => void acceptCandidate(candidate)}>采纳</Button><Button variant="secondary" disabled={candidateBusy} onClick={() => void rejectCandidate(candidate)}>驳回</Button></>}</div></div>)}{!candidates.length && <p className="knowledge-empty">还没有候选。点「从企业资料挖掘」，或粘贴外部问句导入。</p>}</div>
      {candidateTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={candidatePage <= 1} onClick={() => setCandidatePage(candidatePage - 1)}>上一页</Button><span>{candidatePage} / {Math.ceil(candidateTotal / 20)}</span><Button variant="secondary" disabled={candidatePage * 20 >= candidateTotal} onClick={() => setCandidatePage(candidatePage + 1)}>下一页</Button></div>}
      {canWrite && showImport && <form onSubmit={importCandidates} className="knowledge-editor-panel"><h4>导入外部问句</h4><label className="field"><span className="field-label">问句（每行一条）</span><textarea className="text-input knowledge-textarea" value={importText} onChange={(e) => setImportText(e.target.value)} placeholder="从百度下拉、小红书、抖音评论或人工调研里复制；不要带平台账号信息"/></label><label className="field"><span className="field-label">归入桶</span><select className="text-input" value={importBucket} onChange={(e) => setImportBucket(e.target.value)}><option value="category">品类</option><option value="purchase">选购</option><option value="reputation">口碑</option></select></label><div className="knowledge-actions"><Button type="submit" disabled={candidateBusy}>导入候选</Button><Button variant="secondary" onClick={() => setShowImport(false)}>取消</Button></div><p className="knowledge-footnote">只保存问句文本；平台来源只写备注，不保存账号、Cookie 或个人信息。重复问句会按标点/空格归一化后跳过。</p></form>}
      <p className="knowledge-footnote">候选池不自动扩题、不自动激活；采纳生成的是草稿题，需在监测题库确认后再启用。挖掘只使用企业档案、目标词和竞品库，不调用外部平台。</p>
    </Panel>}
    {activeTab === "keywords" && <>
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>目标词</h3><p>共 {keywordTotal} 个；可关联已有内容版本</p></div>{canWrite && <Button icon="plus" onClick={() => openKeywordEditor(null)}>新增目标词</Button>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <form className="knowledge-actions" onSubmit={(e) => { e.preventDefault(); setKeywordPage(1); setAppliedKeywordCategory(keywordCategory.trim()); }}><label className="field"><span className="field-label">分类筛选</span><select className="text-input" value={keywordCategory} onChange={(e) => setKeywordCategory(e.target.value)}><option value="">全部分类</option>{keywordCategories.map((category) => <option key={category} value={category}>{category}</option>)}</select></label><label className="field"><span className="field-label">启用状态</span><select className="text-input" value={keywordActive} onChange={(e) => { setKeywordPage(1); setKeywordActive(e.target.value); }}><option value="">全部</option><option value="true">已启用</option><option value="false">已停用</option></select></label><Button type="submit" variant="secondary">筛选</Button></form>
      <div className="knowledge-list">{keywords.map((keyword) => <div className="knowledge-item" key={keyword.id}><span><strong>{keyword.name}</strong><small>{keyword.category || "未分类"} · 优先级 {keyword.priority} · 关联 {keyword.content_version_ids?.length ?? 0} 个内容版本</small><small>{keyword.notes || "无备注"}</small></span><div className="knowledge-actions"><Badge tone={keyword.is_active ? "green" : "slate"}>{keyword.is_active ? "启用" : "停用"}</Badge>{canWrite && <><Button variant="secondary" onClick={() => openKeywordEditor(keyword)}>编辑</Button>{keyword.is_active && <Button variant="secondary" disabled={busy} onClick={() => void deactivateKeyword(keyword.id)}>停用</Button>}</>}</div></div>)}{!keywords.length && <p className="knowledge-empty">暂无目标词</p>}</div>
      {keywordTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={keywordPage <= 1} onClick={() => setKeywordPage(keywordPage - 1)}>上一页</Button><span>{keywordPage} / {Math.ceil(keywordTotal / 20)}</span><Button variant="secondary" disabled={keywordPage * 20 >= keywordTotal} onClick={() => setKeywordPage(keywordPage + 1)}>下一页</Button></div>}
      <p className="knowledge-footnote">目标词同时绑定监测题库与内容版本；新增或编辑在下方表单完成，停用后历史关联保留。</p>
    </Panel>
    {canWrite && keywordEditorOpen && <div id="keyword-editor">
      <Panel className="knowledge-editor-panel">
        <div className="panel-heading"><div><h3>{editingKeywordId ? "编辑目标词" : "新增目标词"}</h3><p>名称必填；关联内容版本可多选，不选表示解除关联</p></div></div>
        <form onSubmit={saveKeyword}>
          <div className="form-grid">
            <label className="field"><span className="field-label">名称</span><input className="text-input" required maxLength={128} autoFocus value={keywordDraft.name} onChange={(e) => setKeywordDraft({ ...keywordDraft, name: e.target.value })}/></label>
            <label className="field"><span className="field-label">分类</span><input className="text-input" maxLength={64} value={keywordDraft.category} onChange={(e) => setKeywordDraft({ ...keywordDraft, category: e.target.value })}/></label>
            <label className="field"><span className="field-label">优先级</span><input className="text-input" type="number" min={0} required value={keywordDraft.priority} onChange={(e) => setKeywordDraft({ ...keywordDraft, priority: Number(e.target.value) })}/></label>
            <label className="field"><span className="field-label">启用状态</span><span className="rounds-checkbox"><input type="checkbox" checked={keywordDraft.is_active} onChange={(e) => setKeywordDraft({ ...keywordDraft, is_active: e.target.checked })}/> 启用目标词</span></label>
            <label className="field field-wide"><span className="field-label">备注</span><textarea className="text-input knowledge-textarea short" maxLength={5000} value={keywordDraft.notes} onChange={(e) => setKeywordDraft({ ...keywordDraft, notes: e.target.value })}/></label>
            <div className="field field-wide"><span className="field-label">关联内容版本（可多选）</span><div className="keyword-version-picker">{contentVersions.map((version) => <label key={version.version_id} className="keyword-version-row"><input type="checkbox" checked={keywordDraft.content_version_ids.includes(version.version_id)} onChange={() => toggleKeywordVersion(version.version_id)}/><span className="keyword-version-text">{version.title}</span><small>v{version.version_no} · {version.status}</small></label>)}{!contentVersions.length && <p className="knowledge-footnote">暂无可关联的内容版本，先去内容模块建版本。</p>}</div>{keywordDraft.content_version_ids.length > 0 && <p className="knowledge-footnote keyword-version-selected">已选：{keywordDraft.content_version_ids.map((id) => contentVersions.find((version) => version.version_id === id)?.title ?? `未在列表的版本（${id.slice(0, 8)}）`).join("、")}</p>}<small className="knowledge-footnote">勾选即关联，全部取消表示解除关联；当前已选 {keywordDraft.content_version_ids.length} 个 / 可选 {contentVersions.length} 个。</small></div>
          </div>
          <div className="knowledge-actions"><Button type="submit" disabled={busy}>{editingKeywordId ? "保存修改" : "新增目标词"}</Button><Button variant="secondary" onClick={() => { setEditingKeywordId(null); setKeywordDraft({ ...blankKeyword }); setKeywordEditorOpen(false); }}>取消</Button></div>
        </form>
      </Panel>
    </div>}
    </>}
  </div>;
}
