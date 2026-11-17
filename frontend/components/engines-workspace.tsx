"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { EngineConnectionResult, EngineEntryRecord, EngineRecord } from "@/lib/workbench/types";

interface EntryDraft {
  entry_type: string; name: string; entry_url: string; protocol: string; model_name: string;
  credential_ref: string; supports_search: boolean; access_note: string; is_active: boolean;
}

const blankEntry = (): EntryDraft => ({ entry_type: "api", name: "", entry_url: "", protocol: "custom", model_name: "", credential_ref: "", supports_search: false, access_note: "", is_active: true });
const fromEntry = (entry: EngineEntryRecord): EntryDraft => ({ entry_type: entry.entry_type, name: entry.name, entry_url: entry.entry_url ?? "", protocol: entry.protocol, model_name: entry.model_name ?? "", credential_ref: entry.credential_ref ?? "", supports_search: entry.supports_search, access_note: entry.access_note ?? "", is_active: entry.is_active });
const entryTypes = [["web_user", "网页用户端"], ["app_user", "客户端"], ["api", "API"], ["app_search", "应用内搜索"]] as const;
const entryTypeLabel = (value: string) => entryTypes.find(([code]) => code === value)?.[1] ?? value;

export function EnginesWorkspace({ mode, canManage, canVerify, onNotice }: { mode: "mock" | "live"; canManage: boolean; canVerify: boolean; onNotice: (message: string) => void }) {
  const [engines, setEngines] = useState<EngineRecord[]>([]);
  const [enginePage, setEnginePage] = useState(1);
  const [engineTotal, setEngineTotal] = useState(0);
  const [selectedEngineId, setSelectedEngineId] = useState("");
  const [entries, setEntries] = useState<EngineEntryRecord[]>([]);
  const [entryPage, setEntryPage] = useState(1);
  const [entryTotal, setEntryTotal] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loadingEngines, setLoadingEngines] = useState(true);
  const [loadingEntries, setLoadingEntries] = useState(false);
  const [error, setError] = useState("");
  const [newEngine, setNewEngine] = useState(false);
  const [engineDraft, setEngineDraft] = useState({ code: "", name: "", vendor: "", supports_search: true, supports_citation: true });
  const [entryDraft, setEntryDraft] = useState<EntryDraft | null>(null);
  const [editingEntryId, setEditingEntryId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<EngineConnectionResult | null>(null);

  useEffect(() => {
    if (mode !== "live") return;
    let active = true;
    workbenchClient.engines(enginePage).then((result) => {
      if (!active) return;
      setEngines(result.data); setEngineTotal(result.meta?.total ?? result.data.length);
      if (!result.data.length) { setEntries([]); setEntryTotal(0); }
      else setLoadingEntries(true);
      setSelectedEngineId((current) => result.data.some((item) => item.id === current) ? current : result.data[0]?.id ?? "");
      setError("");
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "平台目录加载失败"); })
      .finally(() => { if (active) setLoadingEngines(false); });
    return () => { active = false; };
  }, [mode, enginePage, revision]);

  useEffect(() => {
    if (mode !== "live" || !selectedEngineId) return;
    let active = true;
    workbenchClient.engineEntries(selectedEngineId, entryPage).then((result) => {
      if (!active) return;
      setEntries(result.data); setEntryTotal(result.meta?.total ?? result.data.length); setError("");
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "入口列表加载失败"); })
      .finally(() => { if (active) setLoadingEntries(false); });
    return () => { active = false; };
  }, [mode, selectedEngineId, entryPage, revision]);

  async function saveEngine(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!canManage) return;
    setSaving(true);
    try {
      const created = await workbenchClient.createEngine({ ...engineDraft, code: engineDraft.code.trim(), name: engineDraft.name.trim(), vendor: engineDraft.vendor.trim() });
      setNewEngine(false); setEngineDraft({ code: "", name: "", vendor: "", supports_search: true, supports_citation: true });
      setEnginePage(1); setSelectedEngineId(created.id); setLoadingEngines(true); setLoadingEntries(true); setRevision((value) => value + 1); onNotice("AI 平台已创建");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "创建平台失败"); }
    finally { setSaving(false); }
  }

  async function saveEntry(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!canManage || !entryDraft || !selectedEngineId) return;
    setSaving(true);
    const input = {
      ...entryDraft, name: entryDraft.name.trim(), entry_url: entryDraft.entry_url.trim() || null,
      model_name: entryDraft.model_name.trim() || null, credential_ref: entryDraft.credential_ref.trim() || null,
      access_note: entryDraft.access_note.trim() || null,
    };
    try {
      await workbenchClient.saveEngineEntry(selectedEngineId, input, editingEntryId ?? undefined);
      setEntryDraft(null); setEditingEntryId(null); setLoadingEntries(true); setRevision((value) => value + 1); onNotice("平台入口已保存");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "保存入口失败"); }
    finally { setSaving(false); }
  }

  async function testEntry(entryId: string) {
    if (!canManage || !selectedEngineId) return;
    setTestingId(entryId); setTestResult(null);
    try {
      const result = await workbenchClient.testEngineEntry(selectedEngineId, entryId);
      setTestResult(result); setLoadingEntries(true); setRevision((value) => value + 1);
      onNotice(result.success ? "连接测试通过" : `连接测试未通过：${result.message}`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "连接测试失败"); }
    finally { setTestingId(null); }
  }

  async function verifyEntry(entryId: string) {
    if (!canVerify || !selectedEngineId) return;
    const raw = window.prompt("本次核验备注（可选，例如：官网可访问，需登录；未返回引用来源）", "");
    if (raw === null) return;
    setVerifyingId(entryId);
    try {
      await workbenchClient.verifyEngineEntry(selectedEngineId, entryId, raw.trim() || undefined);
      setLoadingEntries(true); setRevision((value) => value + 1);
      onNotice("入口已标记为人工核验");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "人工核验失败"); }
    finally { setVerifyingId(null); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">AI 平台入口仅在真实接口模式显示。</p></Panel>;
  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>AI 平台目录</h3><p>共 {engineTotal} 个平台；所有登录用户可查看</p></div>{canManage && <Button icon="plus" onClick={() => { setNewEngine(true); setEntryDraft(null); }}>新增平台</Button>}</div>
      <div className="knowledge-list">{engines.map((engine) => <button type="button" className="knowledge-item" key={engine.id} onClick={() => { setSelectedEngineId(engine.id); setEntryPage(1); setEntryDraft(null); setTestResult(null); setLoadingEntries(true); }} aria-pressed={selectedEngineId === engine.id}><span><strong>{engine.name}</strong><small>{engine.code} · {engine.vendor}</small></span><Badge tone={engine.is_active ? "green" : "slate"}>{engine.is_active ? "启用" : "停用"}</Badge></button>)}{!loadingEngines && !engines.length && !error && <p className="knowledge-empty">暂无平台</p>}{loadingEngines && <p className="knowledge-empty">正在加载平台…</p>}</div>
      {engineTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={enginePage <= 1} onClick={() => { setLoadingEngines(true); setEnginePage(enginePage - 1); }}>上一页</Button><span>{enginePage} / {Math.ceil(engineTotal / 20)}</span><Button variant="secondary" disabled={enginePage * 20 >= engineTotal} onClick={() => { setLoadingEngines(true); setEnginePage(enginePage + 1); }}>下一页</Button></div>}
    </Panel>
    {newEngine && canManage && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>新增 AI 平台</h3><p>平台代码创建后不可修改</p></div></div><form onSubmit={saveEngine}>
      <label className="field"><span className="field-label">平台代码</span><input className="text-input" required minLength={2} maxLength={32} value={engineDraft.code} onChange={(e) => setEngineDraft({ ...engineDraft, code: e.target.value })}/></label>
      <label className="field"><span className="field-label">平台名称</span><input className="text-input" required maxLength={64} value={engineDraft.name} onChange={(e) => setEngineDraft({ ...engineDraft, name: e.target.value })}/></label>
      <label className="field"><span className="field-label">供应商</span><input className="text-input" required maxLength={64} value={engineDraft.vendor} onChange={(e) => setEngineDraft({ ...engineDraft, vendor: e.target.value })}/></label>
      <label className="rounds-checkbox"><input type="checkbox" checked={engineDraft.supports_search} onChange={(e) => setEngineDraft({ ...engineDraft, supports_search: e.target.checked })}/> 支持搜索</label>
      <label className="rounds-checkbox"><input type="checkbox" checked={engineDraft.supports_citation} onChange={(e) => setEngineDraft({ ...engineDraft, supports_citation: e.target.checked })}/> 支持引用</label>
      <div className="knowledge-actions"><Button type="submit" disabled={saving}>{saving ? "保存中…" : "创建平台"}</Button><Button variant="secondary" onClick={() => setNewEngine(false)}>取消</Button></div>
    </form></Panel>}
    {selectedEngineId && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>平台入口</h3><p>共 {entryTotal} 个；凭据仅显示环境变量名和配置状态</p></div>{canManage && <Button icon="plus" onClick={() => { setEditingEntryId(null); setEntryDraft(blankEntry()); setNewEngine(false); }}>新增入口</Button>}</div>
      <div className="knowledge-list">{entries.map((entry) => <div className="knowledge-item" key={entry.id}><span><strong>{entry.name}</strong><small>{entryTypeLabel(entry.entry_type)} · {entry.protocol} · {entry.model_name || "无模型"}</small><small>{entry.entry_url || "无入口地址"}</small><small>凭据：{entry.credential_ref || "未指定"}（{entry.credential_configured ? "已配置" : "未配置"}） · {entry.last_verified_at ? `最近验证 ${entry.last_verified_at}` : "未验证"}</small>{entry.access_note && <small>{entry.access_note}</small>}</span><div className="knowledge-actions"><Badge tone={entry.is_active ? "green" : "slate"}>{entry.is_active ? "启用" : "停用"}</Badge>{canManage && <Button variant="secondary" onClick={() => { setEntryDraft(fromEntry(entry)); setEditingEntryId(entry.id); setTestResult(null); }}>编辑</Button>}{entry.entry_type === "web_user" || entry.entry_type === "app_search" ? (canVerify && <Button variant="secondary" disabled={verifyingId === entry.id} onClick={() => void verifyEntry(entry.id)}>{verifyingId === entry.id ? "核验中…" : "标记已核验"}</Button>) : (canManage && <Button variant="secondary" disabled={testingId === entry.id} onClick={() => void testEntry(entry.id)}>{testingId === entry.id ? "测试中…" : "测试连接"}</Button>)}</div></div>)}{!loadingEntries && !entries.length && <p className="knowledge-empty">当前平台暂无入口</p>}{loadingEntries && <p className="knowledge-empty">正在加载入口…</p>}</div>
      {entryTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={entryPage <= 1} onClick={() => { setLoadingEntries(true); setEntryPage(entryPage - 1); }}>上一页</Button><span>{entryPage} / {Math.ceil(entryTotal / 20)}</span><Button variant="secondary" disabled={entryPage * 20 >= entryTotal} onClick={() => { setLoadingEntries(true); setEntryPage(entryPage + 1); }}>下一页</Button></div>}
      {testResult && <p className="knowledge-footnote" role="status">{testResult.success ? "连接成功" : "连接失败"} · {testResult.message} · {testResult.latency_ms == null ? "无耗时" : `${Math.round(testResult.latency_ms)} ms`}</p>}
    </Panel>}
    {entryDraft && canManage && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>{editingEntryId ? "编辑入口" : "新增入口"}</h3><p>凭据填写服务端环境变量名，不填写密钥内容</p></div></div><form onSubmit={saveEntry}>
      <label className="field"><span className="field-label">入口类型</span><select className="text-input" value={entryDraft.entry_type} onChange={(e) => setEntryDraft({ ...entryDraft, entry_type: e.target.value })}>{entryTypes.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>
      <label className="field"><span className="field-label">入口名称</span><input className="text-input" required maxLength={64} value={entryDraft.name} onChange={(e) => setEntryDraft({ ...entryDraft, name: e.target.value })}/></label>
      <label className="field"><span className="field-label">入口地址</span><input className="text-input" type="url" maxLength={2048} placeholder="https://example.com/v1" value={entryDraft.entry_url} onChange={(e) => setEntryDraft({ ...entryDraft, entry_url: e.target.value })}/></label>
      <label className="field"><span className="field-label">调用协议</span><select className="text-input" value={entryDraft.protocol} onChange={(e) => setEntryDraft({ ...entryDraft, protocol: e.target.value })}>{!["custom", "openai_compatible", "deepseek_search", "doubao_search", "wenxin_search", "yuanbao_search"].includes(entryDraft.protocol) && <option value={entryDraft.protocol}>{entryDraft.protocol}</option>}<option value="custom">自定义（暂不自动调用）</option><option value="openai_compatible">OpenAI compatible</option><option value="doubao_search">豆包搜索（方舟 Responses web_search）</option><option value="deepseek_search">DeepSeek 官方搜索（/v1/tools/search）</option><option value="wenxin_search">文心搜索（千帆 AI 搜索）</option><option value="yuanbao_search">腾讯元宝搜索（TC3 签名）</option></select></label>
      <label className="field"><span className="field-label">模型名称</span><input className="text-input" maxLength={128} value={entryDraft.model_name} onChange={(e) => setEntryDraft({ ...entryDraft, model_name: e.target.value })}/></label>
      <label className="field"><span className="field-label">凭据环境变量名</span><input className="text-input" maxLength={64} pattern="[A-Z][A-Z0-9_]*" placeholder="ENGINE_API_KEY" value={entryDraft.credential_ref} onChange={(e) => setEntryDraft({ ...entryDraft, credential_ref: e.target.value })}/></label>
      <label className="field"><span className="field-label">访问说明</span><textarea className="text-input knowledge-textarea short" maxLength={2000} value={entryDraft.access_note} onChange={(e) => setEntryDraft({ ...entryDraft, access_note: e.target.value })}/></label>
      <label className="rounds-checkbox"><input type="checkbox" checked={entryDraft.supports_search} onChange={(e) => setEntryDraft({ ...entryDraft, supports_search: e.target.checked })}/> 支持搜索</label>
      <label className="rounds-checkbox"><input type="checkbox" checked={entryDraft.is_active} onChange={(e) => setEntryDraft({ ...entryDraft, is_active: e.target.checked })}/> 启用入口</label>
      <div className="knowledge-actions"><Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存入口"}</Button><Button variant="secondary" onClick={() => { setEntryDraft(null); setEditingEntryId(null); }}>取消</Button></div>
    </form></Panel>}
  </div>;
}
