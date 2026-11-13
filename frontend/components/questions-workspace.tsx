"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { KeywordRecord, QuestionRecord, QuestionVersionRecord } from "@/lib/workbench/types";

const statusNames = { draft: "草稿", active: "已激活", archived: "已归档" };
const blank = { code: "", title: "", question_type: "general", initial_text: "", audience: "", intent: "", priority: 100, status: "draft" };

export function QuestionsWorkspace({ mode, projectId, canRead, canWrite, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean; onNotice: (message: string) => void;
}) {
  const [questions, setQuestions] = useState<QuestionRecord[]>([]);
  const [keywords, setKeywords] = useState<KeywordRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [keywordTotal, setKeywordTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [keywordPage, setKeywordPage] = useState(1);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<typeof blank | null>(null);
  const [selected, setSelected] = useState<QuestionRecord | null>(null);
  const [versions, setVersions] = useState<QuestionVersionRecord[]>([]);
  const [newText, setNewText] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [keywordName, setKeywordName] = useState("");
  const [keywordQuestionId, setKeywordQuestionId] = useState("");
  const [contentVersionId, setContentVersionId] = useState("");

  const refreshQuestions = useCallback(async () => {
    const result = await workbenchClient.questions(projectId, page);
    setQuestions(result.data); setTotal(result.meta?.total ?? result.data.length);
  }, [projectId, page]);
  const refreshKeywords = useCallback(async () => {
    const result = await workbenchClient.keywords(projectId, keywordPage);
    setKeywords(result.data); setKeywordTotal(result.meta?.total ?? result.data.length);
  }, [projectId, keywordPage]);
  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([workbenchClient.questions(projectId, page), workbenchClient.keywords(projectId, keywordPage)])
      .then(([q, k]) => { if (!active) return; setQuestions(q.data); setTotal(q.meta?.total ?? q.data.length); setKeywords(k.data); setKeywordTotal(k.meta?.total ?? k.data.length); setError(""); })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "题库加载失败"); });
    return () => { active = false; };
  }, [mode, canRead, projectId, page, keywordPage]);

  async function saveQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!draft) return; setBusy(true);
    try {
      await workbenchClient.saveQuestion(projectId, { ...draft, audience: draft.audience || null, intent: draft.intent || null });
      setDraft(null); await refreshQuestions(); onNotice("题目已创建");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "创建题目失败"); }
    finally { setBusy(false); }
  }

  async function choose(question: QuestionRecord) {
    setSelected(question); setNewText(""); setChangeNote("");
    try { setVersions((await workbenchClient.questionVersions(projectId, question.id)).data); setError(""); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "版本加载失败"); }
  }

  async function updateQuestion(changes: Record<string, unknown>) {
    if (!selected) return; setBusy(true);
    try {
      const result = await workbenchClient.saveQuestion(projectId, changes, selected.id);
      setSelected(result); await refreshQuestions(); onNotice("题目属性已保存");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "题目更新失败"); }
    finally { setBusy(false); }
  }

  async function appendVersion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected || !newText.trim()) return; setBusy(true);
    try {
      await workbenchClient.addQuestionVersion(projectId, selected.id, newText.trim(), changeNote);
      const [questionList, versionList] = await Promise.all([workbenchClient.questions(projectId, page), workbenchClient.questionVersions(projectId, selected.id)]);
      setQuestions(questionList.data); setSelected(questionList.data.find((row) => row.id === selected.id) ?? selected);
      setVersions(versionList.data); setNewText(""); setChangeNote(""); onNotice("新问法版本已保存，旧版本保留");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "新版本保存失败"); }
    finally { setBusy(false); }
  }

  async function addKeyword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!keywordName.trim()) return; setBusy(true);
    try {
      await workbenchClient.createKeyword(projectId, {
        name: keywordName.trim(), question_ids: keywordQuestionId ? [keywordQuestionId] : [],
        content_version_ids: contentVersionId.trim() ? [contentVersionId.trim()] : [],
      });
      setKeywordName(""); setKeywordQuestionId(""); setContentVersionId(""); await refreshKeywords(); onNotice("目标词已保存");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "目标词保存失败"); }
    finally { setBusy(false); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">题库管理请切换到真实接口模式。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有题库查看权限。</p></Panel>;
  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>监测题库</h3><p>共 {total} 题；正文修改会新建版本</p></div>{canWrite && <Button icon="plus" onClick={() => setDraft({ ...blank })}>新建题目</Button>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="knowledge-list">{questions.map((question) => <button type="button" className="knowledge-item" key={question.id} onClick={() => void choose(question)}><span><strong>{question.code} · {question.title}</strong><small>{question.current_text || "当前版本缺失"}</small></span><Badge tone={question.status === "active" ? "green" : "amber"}>{statusNames[question.status]}</Badge></button>)}{!questions.length && <p className="knowledge-empty">暂无题目</p>}</div>
      {total > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><span>{page} / {Math.ceil(total / 20)}</span><Button variant="secondary" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>下一页</Button></div>}
    </Panel>
    {draft && <Panel className="knowledge-editor-panel"><div className="panel-heading"><h3>新建题目</h3></div><form onSubmit={saveQuestion}>
      <label className="field"><span className="field-label">代码</span><input className="text-input" required value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })}/></label>
      <label className="field"><span className="field-label">标题</span><input className="text-input" required value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })}/></label>
      <label className="field"><span className="field-label">类型</span><select className="text-input" value={draft.question_type} onChange={(e) => setDraft({ ...draft, question_type: e.target.value })}><option value="general">通用题</option><option value="brand">品牌题</option></select></label>
      <label className="field"><span className="field-label">初版问法</span><textarea className="text-input knowledge-textarea short" required value={draft.initial_text} onChange={(e) => setDraft({ ...draft, initial_text: e.target.value })}/></label>
      <label className="field"><span className="field-label">人群</span><input className="text-input" value={draft.audience} onChange={(e) => setDraft({ ...draft, audience: e.target.value })}/></label>
      <label className="field"><span className="field-label">意图</span><input className="text-input" value={draft.intent} onChange={(e) => setDraft({ ...draft, intent: e.target.value })}/></label>
      <div className="knowledge-actions"><Button type="submit" disabled={busy}>保存题目</Button><Button variant="secondary" onClick={() => setDraft(null)}>取消</Button></div>
    </form></Panel>}
    {selected && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>{selected.code} · {selected.title}</h3><p>当前 v{selected.current_version_no} · {statusNames[selected.status]}</p></div><Button variant="secondary" onClick={() => setSelected(null)}>关闭</Button></div>
      <p>当前问法：{selected.current_text || "版本缺失"}</p>
      {canWrite && <><label className="field"><span className="field-label">状态</span><select className="text-input" value={selected.status} disabled={busy} onChange={(e) => void updateQuestion({ status: e.target.value })}><option value="draft">草稿</option><option value="active">已激活</option><option value="archived">已归档</option></select></label>
        <label className="field"><span className="field-label">人群</span><input className="text-input" defaultValue={selected.audience ?? ""} onBlur={(e) => { if (e.target.value !== (selected.audience ?? "")) void updateQuestion({ audience: e.target.value || null }); }}/></label>
        <label className="field"><span className="field-label">意图</span><input className="text-input" defaultValue={selected.intent ?? ""} onBlur={(e) => { if (e.target.value !== (selected.intent ?? "")) void updateQuestion({ intent: e.target.value || null }); }}/></label>
        <form onSubmit={appendVersion}><label className="field"><span className="field-label">追加问法版本</span><textarea className="text-input knowledge-textarea short" required value={newText} onChange={(e) => setNewText(e.target.value)}/></label><label className="field"><span className="field-label">变更说明</span><input className="text-input" value={changeNote} onChange={(e) => setChangeNote(e.target.value)}/></label><Button type="submit" disabled={busy}>新建版本</Button></form></>}
      <p className="knowledge-footnote">历史版本：{versions.map((version) => `v${version.version_no} ${version.text}`).join(" · ") || "无"}</p>
    </Panel>}
    <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>目标词</h3><p>共 {keywordTotal} 个；可关联题目和内容版本</p></div></div>
      <div className="knowledge-list">{keywords.map((keyword) => <div className="knowledge-item" key={keyword.id}><span><strong>{keyword.name}</strong><small>关联 {keyword.question_ids.length} 题 · {keyword.content_version_ids.length} 个内容版本</small></span></div>)}{!keywords.length && <p className="knowledge-empty">暂无目标词</p>}</div>
      {keywordTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={keywordPage <= 1} onClick={() => setKeywordPage(keywordPage - 1)}>上一页</Button><span>{keywordPage} / {Math.ceil(keywordTotal / 20)}</span><Button variant="secondary" disabled={keywordPage * 20 >= keywordTotal} onClick={() => setKeywordPage(keywordPage + 1)}>下一页</Button></div>}
      {canWrite && <form onSubmit={addKeyword}><label className="field"><span className="field-label">新目标词</span><input className="text-input" required value={keywordName} onChange={(e) => setKeywordName(e.target.value)}/></label><label className="field"><span className="field-label">关联题目</span><select className="text-input" value={keywordQuestionId} onChange={(e) => setKeywordQuestionId(e.target.value)}><option value="">暂不关联</option>{questions.map((item) => <option key={item.id} value={item.id}>{item.code} · {item.title}</option>)}</select></label><label className="field"><span className="field-label">关联内容版本 ID（可选）</span><input className="text-input" value={contentVersionId} onChange={(e) => setContentVersionId(e.target.value)}/></label><Button type="submit" disabled={busy}>新增目标词</Button></form>}
    </Panel>
  </div>;
}
