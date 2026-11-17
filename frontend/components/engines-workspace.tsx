"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
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

/** 人工访问类入口：人打开网页/App 自己提问，程序不直接调用，不需要地址与密钥 */
const manualEntryTypes = ["web_user", "app_user", "app_search"] as const;

const protocolLabels: Record<string, string> = {
  custom: "自定义",
  openai_compatible: "OpenAI 兼容",
  doubao_search: "豆包搜索",
  deepseek_web_search: "DeepSeek 联网搜索",
  wenxin_search: "文心搜索",
  yuanbao_search: "腾讯元宝搜索",
};

/** 与后端 adapter 的 DEFAULT_ENDPOINT / DEFAULT_MODEL / DEFAULT_CREDENTIAL_REF 保持一致 */
const protocolDefaults: Record<string, { endpoint: string; credential: string; model: string }> = {
  doubao_search: { endpoint: "https://ark.cn-beijing.volces.com/api/v3/responses", credential: "ARK_API_KEY", model: "doubao-seed-2-1-pro-260915" },
  wenxin_search: { endpoint: "https://qianfan.baidubce.com/v2/ai_search/web_search", credential: "QIANFAN_API_KEY", model: "wenxin-search" },
  deepseek_web_search: { endpoint: "https://api.deepseek.com/responses", credential: "DEEPSEEK_API_KEY", model: "deepseek-flash" },
  yuanbao_search: { endpoint: "https://wsa.tencentcloudapi.com", credential: "YUANBAO_SECRET_ID", model: "yuanbao-search" },
};
const emptyDefaults = { endpoint: "", credential: "", model: "" };

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
  const [entryNameAuto, setEntryNameAuto] = useState(true);
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
      setEnginePage(1); setSelectedEngineId(created.id); setLoadingEngines(true); setLoadingEntries(true); setRevision((value) => value + 1); onNotice(`已新增平台「${created.name}」，接着在「平台入口」里登记它的调用方式`);
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

  const selectedEngineName = engines.find((engine) => engine.id === selectedEngineId)?.name ?? "";
  const manualEntry = entryDraft ? (manualEntryTypes as readonly string[]).includes(entryDraft.entry_type) : false;
  const currentDefaults = entryDraft ? protocolDefaults[entryDraft.protocol] ?? emptyDefaults : emptyDefaults;
  const endpointRequired = entryDraft?.protocol === "openai_compatible";
  const credentialRequired = entryDraft ? entryDraft.protocol === "openai_compatible" || entryDraft.protocol === "yuanbao_search" : false;
  const modelRequired = entryDraft ? entryDraft.protocol === "openai_compatible" || entryDraft.protocol === "doubao_search" : false;
  const suggestEntryName = (protocol: string, entryType: string) => {
    if (!selectedEngineName) return "";
    if ((manualEntryTypes as readonly string[]).includes(entryType)) return `${selectedEngineName} · ${entryTypeLabel(entryType)}`;
    return `${selectedEngineName} · ${protocolLabels[protocol] ?? protocol}`;
  };
  const suggestedEntryName = entryDraft ? suggestEntryName(entryDraft.protocol, entryDraft.entry_type) : "";

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">AI 平台入口仅在真实接口模式显示。</p></Panel>;
  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>AI 平台目录</h3><p>共 {engineTotal} 个平台；所有登录用户可查看</p></div>{canManage && <Button icon="plus" onClick={() => { setNewEngine(true); setEntryDraft(null); }}>新增平台</Button>}</div>
      <div className="knowledge-list">{engines.map((engine) => <button type="button" className="knowledge-item" key={engine.id} onClick={() => { setSelectedEngineId(engine.id); setEntryPage(1); setEntryDraft(null); setTestResult(null); setLoadingEntries(true); }} aria-pressed={selectedEngineId === engine.id}><span><strong>{engine.name}</strong><small>{engine.code} · {engine.vendor}</small></span><Badge tone={engine.is_active ? "green" : "slate"}>{engine.is_active ? "启用" : "停用"}</Badge></button>)}{!loadingEngines && !engines.length && !error && <p className="knowledge-empty">暂无平台</p>}{loadingEngines && <p className="knowledge-empty">正在加载平台…</p>}</div>
      {engineTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={enginePage <= 1} onClick={() => { setLoadingEngines(true); setEnginePage(enginePage - 1); }}>上一页</Button><span>{enginePage} / {Math.ceil(engineTotal / 20)}</span><Button variant="secondary" disabled={enginePage * 20 >= engineTotal} onClick={() => { setLoadingEngines(true); setEnginePage(enginePage + 1); }}>下一页</Button></div>}
    </Panel>
    {newEngine && canManage && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) setNewEngine(false); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="new-engine-title">
      <div className="modal-header"><div><p className="eyebrow">AI PLATFORM</p><h2 id="new-engine-title">新增 AI 平台</h2></div><button className="icon-button" aria-label="关闭" disabled={saving} onClick={() => setNewEngine(false)}><Icon name="close" size={19}/></button></div>
      <p className="modal-description">把一家 AI 产品登记进来（例如豆包、腾讯元宝、DeepSeek、百度文心）。登记之后，监测任务就会拿它去提问，并把它的回答和引用来源收回来。</p>
      <form onSubmit={saveEngine}>
        <div className="form-grid">
          <label className="field"><span className="field-label">平台代号 *（英文短名，创建后不能改）</span><input className="text-input" required minLength={2} maxLength={32} placeholder="例如 doubao" value={engineDraft.code} onChange={(e) => setEngineDraft({ ...engineDraft, code: e.target.value })}/></label>
          <label className="field"><span className="field-label">平台名称 *（页面上显示的名字）</span><input className="text-input" required maxLength={64} placeholder="例如 豆包" value={engineDraft.name} onChange={(e) => setEngineDraft({ ...engineDraft, name: e.target.value })}/></label>
          <label className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">厂商 *（这家产品属于哪家公司）</span><input className="text-input" required maxLength={64} placeholder="例如 字节跳动" value={engineDraft.vendor} onChange={(e) => setEngineDraft({ ...engineDraft, vendor: e.target.value })}/></label>
        </div>
        <label className="rounds-checkbox"><input type="checkbox" checked={engineDraft.supports_search} onChange={(e) => setEngineDraft({ ...engineDraft, supports_search: e.target.checked })}/> 这家平台能返回搜索/问答结果（能用来提问采集）</label>
        <label className="rounds-checkbox"><input type="checkbox" checked={engineDraft.supports_citation} onChange={(e) => setEngineDraft({ ...engineDraft, supports_citation: e.target.checked })}/> 这家平台会给出引用来源（能统计它引用了谁）</label>
        <div className="modal-actions"><Button type="submit" disabled={saving}>{saving ? "保存中…" : "创建平台"}</Button><Button variant="secondary" disabled={saving} onClick={() => setNewEngine(false)}>取消</Button></div>
      </form>
    </div></div>}
    {selectedEngineId && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>平台入口</h3><p>共 {entryTotal} 个；凭据仅显示环境变量名和配置状态</p></div>{canManage && <Button icon="plus" onClick={() => { setEditingEntryId(null); setEntryNameAuto(true); setEntryDraft(blankEntry()); setNewEngine(false); }}>新增入口</Button>}</div>
      <div className="knowledge-list">{entries.map((entry) => <div className="knowledge-item" key={entry.id}><span><strong>{entry.name}</strong><small>{entryTypeLabel(entry.entry_type)} · {entry.protocol} · {entry.model_name || "无模型"}</small><small>{entry.entry_url || "无入口地址"}</small><small>凭据：{entry.credential_ref || "未指定"}（{entry.credential_configured ? "已配置" : "未配置"}） · {entry.last_verified_at ? `最近验证 ${entry.last_verified_at}` : "未验证"}</small>{entry.access_note && <small>{entry.access_note}</small>}</span><div className="knowledge-actions"><Badge tone={entry.is_active ? "green" : "slate"}>{entry.is_active ? "启用" : "停用"}</Badge>{canManage && <Button variant="secondary" onClick={() => { setEntryNameAuto(false); setEntryDraft(fromEntry(entry)); setEditingEntryId(entry.id); setTestResult(null); }}>编辑</Button>}{entry.entry_type === "web_user" || entry.entry_type === "app_search" ? (canVerify && <Button variant="secondary" disabled={verifyingId === entry.id} onClick={() => void verifyEntry(entry.id)}>{verifyingId === entry.id ? "核验中…" : "标记已核验"}</Button>) : (canManage && <Button variant="secondary" disabled={testingId === entry.id} onClick={() => void testEntry(entry.id)}>{testingId === entry.id ? "测试中…" : "测试连接"}</Button>)}</div></div>)}{!loadingEntries && !entries.length && <p className="knowledge-empty">当前平台暂无入口</p>}{loadingEntries && <p className="knowledge-empty">正在加载入口…</p>}</div>
      {entryTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={entryPage <= 1} onClick={() => { setLoadingEntries(true); setEntryPage(entryPage - 1); }}>上一页</Button><span>{entryPage} / {Math.ceil(entryTotal / 20)}</span><Button variant="secondary" disabled={entryPage * 20 >= entryTotal} onClick={() => { setLoadingEntries(true); setEntryPage(entryPage + 1); }}>下一页</Button></div>}
      {testResult && <p className="knowledge-footnote" role="status">{testResult.success ? "连接成功" : "连接失败"} · {testResult.message} · {testResult.latency_ms == null ? "无耗时" : `${Math.round(testResult.latency_ms)} ms`}</p>}
    </Panel>}
    {entryDraft && canManage && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) { setEntryDraft(null); setEditingEntryId(null); } }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="entry-modal-title" style={{ maxHeight: "86vh", overflowY: "auto" }}>
      <div className="modal-header"><div><p className="eyebrow">PLATFORM ENTRY</p><h2 id="entry-modal-title">{editingEntryId ? "编辑入口" : "新增入口"}</h2></div><button className="icon-button" aria-label="关闭" disabled={saving} onClick={() => { setEntryDraft(null); setEditingEntryId(null); }}><Icon name="close" size={19}/></button></div>
      <p className="modal-description">同一个平台往往有好几种用法（网页版、App、开放接口）。这里登记其中一种「怎么调它」，填好后可以在这条入口上点「测试连接」验证能不能接通。</p>
      <form onSubmit={saveEntry}>
        <div className="form-grid">
          <label className="field"><span className="field-label">入口类型（从哪儿调它）</span><select className="text-input" value={entryDraft.entry_type} onChange={(e) => { const nextType = e.target.value; const nextProtocol = (manualEntryTypes as readonly string[]).includes(nextType) ? "custom" : entryDraft.protocol; setEntryDraft({ ...entryDraft, entry_type: nextType, protocol: nextProtocol, name: entryNameAuto ? suggestEntryName(nextProtocol, nextType) : entryDraft.name }); }}>{entryTypes.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>
          <label className="field"><span className="field-label">入口名称 *（这条调用的别名）</span><input className="text-input" required maxLength={64} placeholder={suggestedEntryName ? `例如 ${suggestedEntryName}` : "例如 豆包搜索（方舟 Responses）"} value={entryDraft.name} onChange={(e) => { setEntryNameAuto(false); setEntryDraft({ ...entryDraft, name: e.target.value }); }}/></label>
          {manualEntry && <p className="field-note" style={{ gridColumn: "1 / -1" }}>这类入口是人打开网页或 App 自己提问，程序不直接调用，因此不用填接口地址、调用协议、模型名和密钥变量名。在备注里写清楚怎么访问、要不要登录就够了；保存后在列表里点「标记已核验」记一次人工确认。</p>}
          {!manualEntry && <>
            <label className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">接口地址（程序把问题发给谁）{endpointRequired ? " *" : "（可留空）"}</span><input className="text-input" type="url" required={endpointRequired} maxLength={2048} placeholder={currentDefaults.endpoint || "https://example.com/api/v1"} value={entryDraft.entry_url} onChange={(e) => setEntryDraft({ ...entryDraft, entry_url: e.target.value })}/><span className="field-hint">{currentDefaults.endpoint ? `留空就用官方默认地址：${currentDefaults.endpoint}` : "选「OpenAI 兼容」必须填完整地址；「自定义」可以留空"}</span></label>
            <label className="field"><span className="field-label">调用协议（按哪种接口格式发请求）</span><select className="text-input" value={entryDraft.protocol} onChange={(e) => { const nextProtocol = e.target.value; setEntryDraft({ ...entryDraft, protocol: nextProtocol, name: entryNameAuto || !entryDraft.name.trim() ? suggestEntryName(nextProtocol, entryDraft.entry_type) : entryDraft.name }); }}>{!["custom", "openai_compatible", "deepseek_search", "deepseek_web_search", "doubao_search", "wenxin_search", "yuanbao_search"].includes(entryDraft.protocol) && <option value={entryDraft.protocol}>{entryDraft.protocol}</option>}<option value="custom">自定义（暂不自动调用）</option><option value="openai_compatible">OpenAI compatible</option><option value="doubao_search">豆包搜索（方舟 Responses web_search）</option><option value="deepseek_search">DeepSeek 官方搜索（/v1/tools/search）</option><option value="deepseek_web_search">DeepSeek 联网搜索（Responses 服务端工具）</option><option value="wenxin_search">文心搜索（千帆 AI 搜索）</option><option value="yuanbao_search">腾讯元宝搜索（TC3 签名）</option></select>{currentDefaults.endpoint ? <span className="field-hint"><button type="button" className="text-link" onClick={() => setEntryDraft({ ...entryDraft, entry_url: currentDefaults.endpoint, model_name: currentDefaults.model, credential_ref: currentDefaults.credential, name: entryNameAuto || !entryDraft.name.trim() ? suggestedEntryName : entryDraft.name })}>按这套协议填好推荐值</button></span> : <span className="field-hint">自定义协议不会自动调用，填不填都不影响监测</span>}</label>
            <label className="field"><span className="field-label">模型名（对方要求的模型标识）{modelRequired ? " *" : "（可留空）"}</span><input className="text-input" required={modelRequired} maxLength={128} placeholder={currentDefaults.model || "例如 doubao-seed-2-1-pro-260915"} value={entryDraft.model_name} onChange={(e) => setEntryDraft({ ...entryDraft, model_name: e.target.value })}/><span className="field-hint">{currentDefaults.model ? `留空就用默认：${currentDefaults.model}` : "选「OpenAI 兼容」时必须填"}</span></label>
            <label className="field"><span className="field-label">密钥变量名（只填环境变量名，不填密钥本身）{credentialRequired ? " *" : "（可留空）"}</span><input className="text-input" required={credentialRequired} maxLength={64} pattern="[A-Z][A-Z0-9_]*" placeholder={currentDefaults.credential || "ARK_API_KEY"} value={entryDraft.credential_ref} onChange={(e) => setEntryDraft({ ...entryDraft, credential_ref: e.target.value })}/><span className="field-hint">{currentDefaults.credential ? `留空就用默认：${currentDefaults.credential}` : "填服务器里配好的环境变量名，例如 XXXX_API_KEY"}</span></label>
          </>}
          <label className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">{manualEntry ? "备注（怎么访问、要不要登录）" : "备注（怎么申请、有什么限制）"}</span><textarea className="text-input knowledge-textarea short" maxLength={2000} placeholder={manualEntry ? "例如：官网可直接访问，无需登录；回答里会带引用来源" : "例如：在控制台申请 key，需要开通联网搜索权限"} value={entryDraft.access_note} onChange={(e) => setEntryDraft({ ...entryDraft, access_note: e.target.value })}/></label>
        </div>
        <label className="rounds-checkbox"><input type="checkbox" checked={entryDraft.supports_search} onChange={(e) => setEntryDraft({ ...entryDraft, supports_search: e.target.checked })}/> 这条入口能返回搜索结果（能用来提问采集）</label>
        <label className="rounds-checkbox"><input type="checkbox" checked={entryDraft.is_active} onChange={(e) => setEntryDraft({ ...entryDraft, is_active: e.target.checked })}/> 启用这条入口（停用后监测不会用它）</label>
        <div className="modal-actions"><Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存入口"}</Button><Button variant="secondary" disabled={saving} onClick={() => { setEntryDraft(null); setEditingEntryId(null); }}>取消</Button></div>
      </form>
    </div></div>}
  </div>;
}
