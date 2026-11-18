"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, CollapsibleItem, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { EngineConnectionResult, EngineEntryRecord, EngineRecord } from "@/lib/workbench/types";

interface EntryDraft {
  entry_type: string; name: string; entry_url: string; protocol: string; model_name: string;
  credential_ref: string; supports_search: boolean; access_note: string; is_active: boolean;
  /** 系统内直接填的密钥（提交后加密落库，列表不回显）；留空表示不改动已保存的值 */
  api_key: string; api_key_secondary: string;
  /** 编辑态：勾选后清除系统内保存的密钥，改回读环境变量 */
  clear_api_key: boolean;
}

const blankEntry = (): EntryDraft => ({ entry_type: "api", name: "", entry_url: "", protocol: "custom", model_name: "", credential_ref: "", supports_search: false, access_note: "", is_active: true, api_key: "", api_key_secondary: "", clear_api_key: false });
const fromEntry = (entry: EngineEntryRecord): EntryDraft => ({ entry_type: entry.entry_type, name: entry.name, entry_url: entry.entry_url ?? "", protocol: entry.protocol, model_name: entry.model_name ?? "", credential_ref: entry.credential_ref ?? "", supports_search: entry.supports_search, access_note: entry.access_note ?? "", is_active: entry.is_active, api_key: "", api_key_secondary: "", clear_api_key: false });
/** 双密钥协议：腾讯元宝是 SecretId（主）+ SecretKey（次） */
const needsSecondaryKey = (protocol: string) => protocol === "yuanbao_search";
const credentialSourceLabel = (source?: string | null) => {
  if (source === "database") return "系统内填写";
  if (source === "environment") return "服务器环境变量";
  return "";
};
const entryTypes = [["web_user", "网页用户端"], ["app_user", "客户端"], ["api", "API"], ["app_search", "应用内搜索"]] as const;
const entryTypeLabel = (value: string) => entryTypes.find(([code]) => code === value)?.[1] ?? value;

/** 人工访问类入口：人打开网页/App 自己提问，程序不直接调用，不需要地址与密钥 */
const manualEntryTypes = ["web_user", "app_user", "app_search"] as const;
const isManualEntry = (entryType: string) => (manualEntryTypes as readonly string[]).includes(entryType);
const entryUrlLabel = (entry: EngineEntryRecord) => entry.entry_url || (entry.config_redacted ? "地址仅管理员可见" : "无入口地址");
const entrySecurityLabel = (entry: EngineEntryRecord) => {
  const verified = entry.last_verified_at ? `最近验证 ${entry.last_verified_at}` : "未验证";
  if (isManualEntry(entry.entry_type)) return verified;
  const source = credentialSourceLabel(entry.credential_source);
  const credential = entry.credential_ref
    ? `凭据：${entry.credential_ref}（${entry.credential_configured ? "已配置" : "未配置"}${source ? `，来源 ${source}` : ""}）`
    : entry.config_redacted
      ? `凭据：仅管理员可见（${entry.credential_configured ? "已配置" : "未配置"}${source ? `，来源 ${source}` : ""}）`
      : entry.credential_configured
        ? `凭据：系统内已填写（${source || "加密保存"}）`
        : "凭据：未指定";
  return `${credential} · ${verified}`;
};

const protocolLabels: Record<string, string> = {
  custom: "自定义",
  openai_compatible: "OpenAI 兼容（含千帆 ERNIE 对话模型）",
  doubao_search: "豆包搜索",
  deepseek_web_search: "DeepSeek 联网搜索",
  wenxin_search: "千帆 AI 搜索（旧产品）",
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
/** 协议联动只回填地址和密钥变量名；模型名由用户按平台实际模型手填，不自动覆盖。 */
const protocolAutoFill = (protocol: string, clearUnknown = false) => {
  const defaults = protocolDefaults[protocol];
  if (defaults) return { entry_url: defaults.endpoint, credential_ref: defaults.credential };
  return clearUnknown ? { entry_url: "", credential_ref: "" } : {};
};
/** 从有默认值的协议切到无默认值的协议时清空旧地址，避免串用另一家平台的地址；本来就是自定义则保留手填。 */
const protocolTransitionFill = (nextProtocol: string, previousProtocol: string) =>
  protocolAutoFill(nextProtocol, !protocolDefaults[nextProtocol] && !!protocolDefaults[previousProtocol]);
/** 平台名称/厂商只用来推荐协议；用户手动改过协议后不再自动覆盖。 */
const protocolHints: Array<[RegExp, string]> = [
  [/ernie|openai|gpt/i, "openai_compatible"],
  [/字节跳动|字节|豆包|doubao|方舟|火山|bytedance|volcengine/i, "doubao_search"],
  [/深度求索|deepseek/i, "deepseek_web_search"],
  [/元宝|yuanbao/i, "yuanbao_search"],
  [/百度.*(搜|文心)|文心|千帆|wenxin|qianfan/i, "wenxin_search"],
];
const suggestProtocol = (platformName: string, platformVendor = "") => {
  const vendor = platformVendor.trim();
  const name = platformName.trim();
  const fromVendor = vendor ? protocolHints.find(([pattern]) => pattern.test(vendor)) : undefined;
  const fromName = protocolHints.find(([pattern]) => pattern.test(name));
  return (fromVendor ?? fromName)?.[1] ?? "custom";
};
const blankEngineDraft = () => ({ code: "", name: "", vendor: "", supports_search: true, supports_citation: true });
const protocolOptions = [["custom", "自定义（暂不自动调用）"], ["openai_compatible", "OpenAI compatible（含千帆 ERNIE 对话模型）"], ["doubao_search", "豆包搜索（方舟 Responses web_search）"], ["deepseek_web_search", "DeepSeek 联网搜索（Responses 服务端工具）"], ["wenxin_search", "千帆 AI 搜索（旧产品，仅留档）"], ["yuanbao_search", "腾讯元宝搜索（TC3 签名）"]] as const;
/** 专属协议只能挂在对应厂商的平台下；custom / openai_compatible 是通用协议。 */
const protocolVendorPatterns: Record<string, RegExp> = {
  doubao_search: /字节跳动|字节|豆包|doubao|火山|方舟|bytedance|volcengine/i,
  deepseek_web_search: /深度求索|deepseek/i,
  wenxin_search: /百度|文心|千帆|baidu|qianfan/i,
  yuanbao_search: /腾讯|元宝|tencent|yuanbao/i,
};
const genericProtocols = new Set(["custom", "openai_compatible"]);
const protocolAllowedForPlatform = (protocol: string, platformName: string, platformVendor = "") => {
  if (genericProtocols.has(protocol)) return true;
  const pattern = protocolVendorPatterns[protocol];
  if (!pattern) return true;
  // 厂商是硬约束；录入平台时厂商还没填完，才退回平台名称做提示性判断。
  return pattern.test(platformVendor.trim() || platformName.trim());
};
const protocolOptionsForPlatform = (platformName: string, platformVendor = "") =>
  protocolOptions.filter(([value]) => protocolAllowedForPlatform(value, platformName, platformVendor));

/** AI 平台清单固定展示顺序：首轮4个 → 扩展6个 → 探测5个；其余平台按名称排在最后。 */
const PLATFORM_DISPLAY_ORDER = ["豆包", "腾讯元宝", "DeepSeek", "百度文心", "Kimi", "千问", "夸克", "秘塔AI搜索", "百度AI搜", "360纳米AI", "智谱清言", "讯飞星火", "微信搜一搜AI", "知乎直答", "小红书点点"];
const platformOrderIndex = (name: string) => {
  const index = PLATFORM_DISPLAY_ORDER.indexOf(name);
  return index === -1 ? PLATFORM_DISPLAY_ORDER.length : index;
};
const sortPlatforms = (list: EngineRecord[]) => [...list].sort((a, b) => {
  const diff = platformOrderIndex(a.name) - platformOrderIndex(b.name);
  if (diff !== 0) return diff;
  return `${a.name} ${a.code}`.localeCompare(`${b.name} ${b.code}`, "zh-Hans-CN");
});

/** 入口字段的显隐与必填规则；入口弹窗与「新增平台」里的入口区块共用 */
const entryRulesOf = (draft: EntryDraft | null) => {
  const manual = draft ? (manualEntryTypes as readonly string[]).includes(draft.entry_type) : false;
  return {
    manual,
    defaults: draft ? protocolDefaults[draft.protocol] ?? emptyDefaults : emptyDefaults,
    endpointRequired: draft?.protocol === "openai_compatible",
    credentialRequired: !!draft && (draft.protocol === "openai_compatible" || draft.protocol === "yuanbao_search"),
    modelRequired: !!draft && (draft.protocol === "openai_compatible" || draft.protocol === "doubao_search"),
  };
};

export function EnginesWorkspace({ mode, canManage, canVerify, onNotice }: { mode: "mock" | "live"; canManage: boolean; canVerify: boolean; onNotice: (message: string) => void }) {
  const [engines, setEngines] = useState<EngineRecord[]>([]);
  const [enginePage, setEnginePage] = useState(1);
  const [engineTotal, setEngineTotal] = useState(0);
  const [entriesByEngine, setEntriesByEngine] = useState<Record<string, EngineEntryRecord[]>>({});
  const [revision, setRevision] = useState(0);
  const [loadingEngines, setLoadingEngines] = useState(true);
  const [error, setError] = useState("");
  const [newEngine, setNewEngine] = useState(false);
  const [engineDraft, setEngineDraft] = useState(blankEngineDraft());
  const [withPlatformEntry, setWithPlatformEntry] = useState(true);
  const [platformEntryDraft, setPlatformEntryDraft] = useState<EntryDraft>(blankEntry());
  const [platformEntryNameAuto, setPlatformEntryNameAuto] = useState(true);
  const [platformProtocolAuto, setPlatformProtocolAuto] = useState(true);
  const [entryDraft, setEntryDraft] = useState<EntryDraft | null>(null);
  const [entryNameAuto, setEntryNameAuto] = useState(true);
  const [editingEntryId, setEditingEntryId] = useState<string | null>(null);
  const [entryEngineId, setEntryEngineId] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [deletingEntryId, setDeletingEntryId] = useState<string | null>(null);
  const [deletingEngineId, setDeletingEngineId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<EngineConnectionResult | null>(null);

  useEffect(() => {
    if (mode !== "live") return;
    let active = true;
    workbenchClient.engines(enginePage).then(async (result) => {
      if (!active) return;
      setEngines(sortPlatforms(result.data)); setEngineTotal(result.meta?.total ?? result.data.length);
      const groups: Record<string, EngineEntryRecord[]> = {};
      await Promise.all(result.data.map(async (engine) => {
        try {
          const entries = await workbenchClient.engineEntries(engine.id, 1);
          groups[engine.id] = entries.data;
        } catch {
          groups[engine.id] = [];
        }
      }));
      if (active) setEntriesByEngine(groups);
      setError("");
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "平台目录加载失败"); })
      .finally(() => { if (active) setLoadingEngines(false); });
    return () => { active = false; };
  }, [mode, enginePage, revision]);

  function closeNewEngine() {
    setNewEngine(false); setEngineDraft(blankEngineDraft()); setPlatformEntryDraft(blankEntry()); setPlatformEntryNameAuto(true); setPlatformProtocolAuto(true); setWithPlatformEntry(true);
  }

  function openNewEngine() {
    closeNewEngine(); setNewEngine(true); setEntryDraft(null); setTestResult(null);
  }

  function openEntryFor(engineId: string) {
    setEditingEntryId(null); setEntryNameAuto(true); setEntryDraft(blankEntry()); setEntryEngineId(engineId); setNewEngine(false); setTestResult(null);
  }

  function openEditEntry(engineId: string, entry: EngineEntryRecord) {
    setEntryNameAuto(false); setEntryDraft(fromEntry(entry)); setEditingEntryId(entry.id); setEntryEngineId(engineId); setTestResult(null);
  }

  async function deleteEntry(engineId: string, entry: EngineEntryRecord) {
    if (!canManage) return;
    if (!window.confirm(`确认删除入口「${entry.name}」？删除后不可恢复。`)) return;
    setDeletingEntryId(entry.id);
    try {
      await workbenchClient.deleteEngineEntry(engineId, entry.id);
      onNotice(`已删除入口「${entry.name}」`);
      setRevision((value) => value + 1);
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "删除失败");
    } finally {
      setDeletingEntryId(null);
    }
  }

  async function deletePlatform(engine: EngineRecord) {
    if (!canManage) return;
    if (!window.confirm(`确认删除平台「${engine.name}」？平台下还有入口时需要先删除入口。`)) return;
    setDeletingEngineId(engine.id);
    try {
      await workbenchClient.deleteEngine(engine.id);
      onNotice(`已删除平台「${engine.name}」`);
      setRevision((value) => value + 1);
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "删除平台失败");
    } finally {
      setDeletingEngineId(null);
    }
  }

  async function saveEngine(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!canManage) return;
    if (withPlatformEntry && !protocolAllowedForPlatform(platformEntryDraft.protocol, engineDraft.name, engineDraft.vendor)) {
      onNotice("当前调用协议与平台厂商不匹配，请改选协议"); return;
    }
    const rules = entryRulesOf(platformEntryDraft);
    const autoName = engineDraft.name.trim() ? suggestEntryName(platformEntryDraft.protocol, platformEntryDraft.entry_type, engineDraft.name.trim()) : "";
    setSaving(true);
    try {
      const created = await workbenchClient.createEngine({ ...engineDraft, code: engineDraft.code.trim(), name: engineDraft.name.trim(), vendor: engineDraft.vendor.trim() });
      let notice = `已新增平台「${created.name}」`;
      if (withPlatformEntry) {
        const entryName = (platformEntryNameAuto ? autoName : platformEntryDraft.name).trim()
          || `${created.name} · ${rules.manual ? entryTypeLabel(platformEntryDraft.entry_type) : protocolLabels[platformEntryDraft.protocol] ?? platformEntryDraft.protocol}`;
        // 密钥只在有值时提交；空串不传，避免把“没填”当成“改成了空”
        const entryInput = {
          entry_type: platformEntryDraft.entry_type, name: entryName, entry_url: platformEntryDraft.entry_url.trim() || null,
          protocol: platformEntryDraft.protocol, model_name: platformEntryDraft.model_name.trim() || null,
          credential_ref: platformEntryDraft.credential_ref.trim() || null,
          supports_search: engineDraft.supports_search, access_note: platformEntryDraft.access_note.trim() || null,
          is_active: platformEntryDraft.is_active,
          ...(platformEntryDraft.api_key.trim() ? { api_key: platformEntryDraft.api_key.trim() } : {}),
          ...(needsSecondaryKey(platformEntryDraft.protocol) && platformEntryDraft.api_key_secondary.trim() ? { api_key_secondary: platformEntryDraft.api_key_secondary.trim() } : {}),
        };
        try {
          await workbenchClient.saveEngineEntry(created.id, entryInput);
          notice += `，并登记了入口「${entryName}」`;
        } catch (cause) {
          notice += `；但入口没存上（${cause instanceof Error ? cause.message : "未知错误"}），请到该平台下手动补一条`;
        }
      } else {
        notice += `，接着在该平台下登记它的调用方式`;
      }
      closeNewEngine();
      setEnginePage(1); setRevision((value) => value + 1);
      onNotice(notice);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "创建平台失败"); }
    finally { setSaving(false); }
  }

  async function saveEntry(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!canManage || !entryDraft || !entryEngineId) return;
    if (!protocolAllowedForPlatform(entryDraft.protocol, entryEngineName, entryEngineVendor)) {
      onNotice("当前调用协议与所属平台厂商不匹配，请改选协议"); return;
    }
    setSaving(true);
    const { api_key, api_key_secondary, clear_api_key, ...entryRest } = entryDraft;
    const input: Record<string, unknown> = {
      ...entryRest, name: entryDraft.name.trim(), entry_url: entryDraft.entry_url.trim() || null,
      model_name: entryDraft.model_name.trim() || null, credential_ref: entryDraft.credential_ref.trim() || null,
      access_note: entryDraft.access_note.trim() || null,
    };
    // 编辑态语义：留空=不改；填了=覆盖；勾了清除=回落环境变量（三者互斥）
    if (clear_api_key) input.clear_api_key = true;
    else {
      if (api_key.trim()) input.api_key = api_key.trim();
      if (needsSecondaryKey(entryDraft.protocol) && api_key_secondary.trim()) input.api_key_secondary = api_key_secondary.trim();
    }
    try {
      await workbenchClient.saveEngineEntry(entryEngineId, input, editingEntryId ?? undefined);
      setEntryDraft(null); setEditingEntryId(null); setEntryEngineId("");
      setRevision((value) => value + 1); onNotice("平台入口已保存");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "保存入口失败"); }
    finally { setSaving(false); }
  }

  async function testEntry(engineId: string, entryId: string) {
    if (!canManage) return;
    setTestingId(entryId); setTestResult(null);
    try {
      const result = await workbenchClient.testEngineEntry(engineId, entryId);
      setTestResult(result); setRevision((value) => value + 1);
      onNotice(result.success ? "连接测试通过" : `连接测试未通过：${result.message}`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "连接测试失败"); }
    finally { setTestingId(null); }
  }

  async function verifyEntry(engineId: string, entryId: string) {
    if (!canVerify) return;
    const raw = window.prompt("本次核验备注（可选，例如：官网可访问，需登录；未返回引用来源）", "");
    if (raw === null) return;
    setVerifyingId(entryId);
    try {
      await workbenchClient.verifyEngineEntry(engineId, entryId, raw.trim() || undefined);
      setRevision((value) => value + 1);
      onNotice("入口已标记为人工核验");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "人工核验失败"); }
    finally { setVerifyingId(null); }
  }

  const entryEngine = engines.find((engine) => engine.id === entryEngineId);
  const entryEngineName = entryEngine?.name ?? "";
  const entryEngineVendor = entryEngine?.vendor ?? "";
  const suggestEntryName = (protocol: string, entryType: string, platformName = entryEngineName) => {
    if (!platformName) return "";
    if ((manualEntryTypes as readonly string[]).includes(entryType)) return `${platformName} · ${entryTypeLabel(entryType)}`;
    return `${platformName} · ${protocolLabels[protocol] ?? protocol}`;
  };
  const entryRules = entryRulesOf(entryDraft);
  const manualEntry = entryRules.manual;
  const currentDefaults = entryRules.defaults;
  const endpointRequired = entryRules.endpointRequired;
  const credentialRequired = entryRules.credentialRequired;
  const modelRequired = entryRules.modelRequired;
  const suggestedEntryName = entryDraft ? suggestEntryName(entryDraft.protocol, entryDraft.entry_type) : "";
  const entryProtocols = protocolOptionsForPlatform(entryEngineName, entryEngineVendor);
  const entryProtocolMismatch = !!entryDraft && !protocolAllowedForPlatform(entryDraft.protocol, entryEngineName, entryEngineVendor);
  const editingEntryRecord = editingEntryId ? (entriesByEngine[entryEngineId] ?? []).find((entry) => entry.id === editingEntryId) : undefined;
  const platformRules = entryRulesOf(platformEntryDraft);
  const platformSuggestedName = engineDraft.name.trim() ? suggestEntryName(platformEntryDraft.protocol, platformEntryDraft.entry_type, engineDraft.name.trim()) : "";
  const platformEntryNameValue = platformEntryNameAuto ? platformSuggestedName : platformEntryDraft.name;
  const platformProtocols = protocolOptionsForPlatform(engineDraft.name, engineDraft.vendor);
  const platformProtocolMismatch = !protocolAllowedForPlatform(platformEntryDraft.protocol, engineDraft.name, engineDraft.vendor);

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">AI 平台入口仅在真实接口模式显示。</p></Panel>;
  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>AI 平台清单</h3><p>共 {engineTotal} 个平台；每个平台下展示其接入入口、凭据配置与验证状态</p></div>{canManage && <Button icon="plus" onClick={openNewEngine}>新增平台</Button>}</div>
      <div className="knowledge-list">
        {engines.map((engine) => {
          const entries = entriesByEngine[engine.id] ?? [];
          return <CollapsibleItem key={engine.id} storageKey={`engine-platform:${engine.id}`} className="engine-row" title={<span className="engine-platform-main"><strong>{engine.name}</strong><small>{engine.code} · {engine.vendor}</small></span>} actions={<div className="engine-platform-side">
            <Badge tone={engine.is_active ? "green" : "slate"}>{engine.is_active ? "启用" : "停用"}</Badge>
            {canManage && <Button variant="secondary" icon="plus" onClick={() => openEntryFor(engine.id)}>新增入口</Button>}
            {canManage && <Button variant="danger" disabled={deletingEngineId === engine.id} onClick={() => void deletePlatform(engine)}>{deletingEngineId === engine.id ? "删除中…" : "删除"}</Button>}
          </div>}>
            <div className="engine-entry-group">
              {entries.map((entry) => <CollapsibleItem
                key={entry.id}
                storageKey={`engine-entry:${entry.id}`}
                className="engine-entry-row"
                title={<span className="engine-entry-main">
                  <strong>{entry.name}</strong>
                  <small>{entryTypeLabel(entry.entry_type)} · {entry.protocol} · {entry.model_name || "无模型"}</small>
                </span>}
                actions={<div className="knowledge-actions">
                  {!protocolAllowedForPlatform(entry.protocol, engine.name, engine.vendor) && <Badge tone="red">跨厂商</Badge>}
                  <Badge tone={entry.is_active ? "green" : "slate"}>{entry.is_active ? "启用" : "停用"}</Badge>
                  {canManage && <Button variant="secondary" onClick={() => openEditEntry(engine.id, entry)}>编辑</Button>}
                  {canManage && <Button variant="danger" disabled={deletingEntryId === entry.id} onClick={() => void deleteEntry(engine.id, entry)}>{deletingEntryId === entry.id ? "删除中…" : "删除"}</Button>}
                  {entry.entry_type === "web_user" || entry.entry_type === "app_search" ? (canVerify && <Button variant="secondary" disabled={verifyingId === entry.id} onClick={() => void verifyEntry(engine.id, entry.id)}>{verifyingId === entry.id ? "核验中…" : "标记已核验"}</Button>) : (canManage && <Button variant="secondary" disabled={testingId === entry.id} onClick={() => void testEntry(engine.id, entry.id)}>{testingId === entry.id ? "测试中…" : "测试连接"}</Button>)}
                </div>}
              >
                <div className="engine-entry-detail">
                  <small>{entryUrlLabel(entry)}</small>
                  <small>{entrySecurityLabel(entry)}</small>
                  {entry.access_note && <small>{entry.access_note}</small>}
                </div>
              </CollapsibleItem>)}
              {!entries.length && <p className="engine-entry-empty">未配置入口</p>}
            </div>
          </CollapsibleItem>;
        })}
        {!loadingEngines && !engines.length && !error && <p className="knowledge-empty">暂无平台</p>}
        {loadingEngines && <p className="knowledge-empty">正在加载平台…</p>}
      </div>
      {engineTotal > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={enginePage <= 1} onClick={() => { setLoadingEngines(true); setEnginePage(enginePage - 1); }}>上一页</Button><span>{enginePage} / {Math.ceil(engineTotal / 20)}</span><Button variant="secondary" disabled={enginePage * 20 >= engineTotal} onClick={() => { setLoadingEngines(true); setEnginePage(enginePage + 1); }}>下一页</Button></div>}
      {testResult && <p className="knowledge-footnote" role="status">{testResult.success ? "连接成功" : "连接失败"} · {testResult.message} · {testResult.latency_ms == null ? "无耗时" : `${Math.round(testResult.latency_ms)} ms`}</p>}
    </Panel>
    {newEngine && canManage && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) closeNewEngine(); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="new-engine-title" style={{ maxHeight: "88vh", overflowY: "auto" }}>
      <div className="modal-header"><div><p className="eyebrow">AI PLATFORM</p><h2 id="new-engine-title">新增 AI 平台</h2></div><button className="icon-button" aria-label="关闭" disabled={saving} onClick={closeNewEngine}><Icon name="close" size={19}/></button></div>
      <p className="modal-description">把一家 AI 产品登记进来（例如豆包、腾讯元宝、DeepSeek、百度文心）。登记之后，监测任务就会拿它去提问，并把它的回答和引用来源收回来。</p>
      <form onSubmit={saveEngine}>
        <div className="form-grid">
          <label className="field"><span className="field-label">平台代号 *（英文短名，创建后不能改）</span><input className="text-input" required minLength={2} maxLength={32} placeholder="例如 doubao" value={engineDraft.code} onChange={(e) => setEngineDraft({ ...engineDraft, code: e.target.value })}/></label>
          <label className="field"><span className="field-label">平台名称 *（页面上显示的名字）</span><input className="text-input" required maxLength={64} placeholder="例如 豆包" value={engineDraft.name} onChange={(e) => { const nextName = e.target.value; setEngineDraft({ ...engineDraft, name: nextName }); if (platformProtocolAuto) { const nextProtocol = suggestProtocol(nextName, engineDraft.vendor); setPlatformEntryDraft({ ...platformEntryDraft, protocol: nextProtocol, ...protocolTransitionFill(nextProtocol, platformEntryDraft.protocol) }); } }}/></label>
          <label className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">厂商 *（这家产品属于哪家公司）</span><input className="text-input" required maxLength={64} placeholder="例如 字节跳动" value={engineDraft.vendor} onChange={(e) => { const nextVendor = e.target.value; setEngineDraft({ ...engineDraft, vendor: nextVendor }); if (platformProtocolAuto) { const nextProtocol = suggestProtocol(engineDraft.name, nextVendor); setPlatformEntryDraft({ ...platformEntryDraft, protocol: nextProtocol, ...protocolTransitionFill(nextProtocol, platformEntryDraft.protocol) }); } }}/></label>
        </div>
        <label className="rounds-checkbox" style={{ marginTop: 10 }}><input type="checkbox" checked={engineDraft.supports_search} onChange={(e) => setEngineDraft({ ...engineDraft, supports_search: e.target.checked })}/> 这家平台能返回搜索/问答结果（能用来提问采集）</label>
        <label className="rounds-checkbox" style={{ marginTop: 6 }}><input type="checkbox" checked={engineDraft.supports_citation} onChange={(e) => setEngineDraft({ ...engineDraft, supports_citation: e.target.checked })}/> 这家平台会给出引用来源（能统计它引用了谁）</label>
        <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
          <label className="rounds-checkbox"><input type="checkbox" checked={withPlatformEntry} onChange={(e) => setWithPlatformEntry(e.target.checked)}/> 顺便登记一条调用方式（推荐，省得再回平台下补一次）</label>
          {withPlatformEntry && <>
            <div className="form-grid" style={{ marginTop: 12 }}>
              <label className="field"><span className="field-label">入口类型（从哪儿调它）</span><select className="text-input" value={platformEntryDraft.entry_type} onChange={(e) => { const nextType = e.target.value; const manual = (manualEntryTypes as readonly string[]).includes(nextType); const nextProtocol = manual ? "custom" : platformProtocolAuto ? suggestProtocol(engineDraft.name, engineDraft.vendor) : platformEntryDraft.protocol; setPlatformEntryDraft({ ...platformEntryDraft, entry_type: nextType, protocol: nextProtocol, ...(!manual && platformProtocolAuto ? protocolTransitionFill(nextProtocol, platformEntryDraft.protocol) : {}) }); }}>{entryTypes.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>
              <label className="field"><span className="field-label">入口名称（这条调用的别名）</span><input className="text-input" maxLength={64} placeholder={platformSuggestedName ? `例如 ${platformSuggestedName}` : "填好平台名称后这里会自动补"} value={platformEntryNameValue} onChange={(e) => { setPlatformEntryNameAuto(false); setPlatformEntryDraft({ ...platformEntryDraft, name: e.target.value }); }}/></label>
              {platformRules.manual ? <p className="field-note" style={{ gridColumn: "1 / -1" }}>人工访问类入口：人是自己打开网页或 App 提问的，程序不直接调用，所以地址、模型、密钥都不用填，写清怎么访问就行。</p> : <>
                <label className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">接口地址（程序把问题发给谁）{platformRules.endpointRequired ? " *" : "（可留空）"}</span><input className="text-input" type="url" required={platformRules.endpointRequired} maxLength={2048} placeholder={platformRules.defaults.endpoint || "https://example.com/api/v1"} value={platformEntryDraft.entry_url} onChange={(e) => setPlatformEntryDraft({ ...platformEntryDraft, entry_url: e.target.value })}/><span className="field-hint">{platformRules.defaults.endpoint ? `留空就用官方默认地址：${platformRules.defaults.endpoint}` : "选「OpenAI 兼容」必须填完整地址；「自定义」可以留空"}</span></label>
                <label className="field"><span className="field-label">调用协议（按哪种接口格式发请求）</span><select className="text-input" value={platformEntryDraft.protocol} onChange={(e) => { const nextProtocol = e.target.value; setPlatformProtocolAuto(false); setPlatformEntryDraft({ ...platformEntryDraft, protocol: nextProtocol, ...protocolAutoFill(nextProtocol) }); }}>{platformProtocols.map(([value, text]) => <option key={value} value={value} disabled={!protocolAllowedForPlatform(value, engineDraft.name, engineDraft.vendor)}>{text}</option>)}{!platformProtocols.some(([value]) => value === platformEntryDraft.protocol) && <option value={platformEntryDraft.protocol}>{protocolLabels[platformEntryDraft.protocol] ?? platformEntryDraft.protocol}（跨厂商，需修改）</option>}</select>{platformProtocolMismatch && <span className="form-error" role="alert">当前协议与平台厂商不匹配，请改选</span>}{platformRules.defaults.endpoint ? <span className="field-hint"><button type="button" className="text-link" onClick={() => setPlatformEntryDraft({ ...platformEntryDraft, ...protocolAutoFill(platformEntryDraft.protocol) })}>按这套协议填入默认地址和密钥</button></span> : <span className="field-hint">自定义协议不会自动调用，填不填都不影响监测</span>}</label>
                <label className="field"><span className="field-label">模型名（对方要求的模型标识）{platformRules.modelRequired ? " *" : "（可留空）"}</span><input className="text-input" required={platformRules.modelRequired} maxLength={128} placeholder={platformRules.defaults.model || "例如 doubao-seed-2-1-pro-260915"} value={platformEntryDraft.model_name} onChange={(e) => setPlatformEntryDraft({ ...platformEntryDraft, model_name: e.target.value })}/><span className="field-hint">{platformRules.modelRequired ? `必须填，官方默认：${platformRules.defaults.model || "参考对方文档"}` : platformRules.defaults.model ? `留空就用默认：${platformRules.defaults.model}` : "选「OpenAI 兼容」时必须填"}（模型名不随协议自动填，请按实际模型填写）</span></label>
                <label className="field"><span className="field-label">密钥变量名（只填环境变量名，不填密钥本身）{platformRules.credentialRequired ? " *" : "（可留空）"}</span><input className="text-input" required={platformRules.credentialRequired && !platformEntryDraft.api_key.trim()} maxLength={64} pattern="[A-Z][A-Z0-9_]*" placeholder={platformRules.defaults.credential || "ARK_API_KEY"} value={platformEntryDraft.credential_ref} onChange={(e) => setPlatformEntryDraft({ ...platformEntryDraft, credential_ref: e.target.value })}/><span className="field-hint">{platformRules.credentialRequired ? `必须填，官方默认：${platformRules.defaults.credential || "参考对方文档"}` : platformRules.defaults.credential ? `留空就用默认：${platformRules.defaults.credential}` : "填服务器里配好的环境变量名，例如 XXXX_API_KEY"}</span></label>
                <label className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">API Key（直接在系统里填，加密保存，不用改服务器配置）</span><input className="text-input" type="text" autoComplete="new-password" maxLength={4096} placeholder="粘贴密钥；留空则读上面的环境变量" value={platformEntryDraft.api_key} onChange={(e) => setPlatformEntryDraft({ ...platformEntryDraft, api_key: e.target.value })}/><span className="field-hint">输入时直接可见，方便粘贴核对；保存后只以密文存库，列表与接口都不回显。</span></label>
                {needsSecondaryKey(platformEntryDraft.protocol) && <label className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">SecretKey（元宝的第二把密钥，也在这里填）</span><input className="text-input" type="text" autoComplete="new-password" maxLength={4096} placeholder="粘贴 SecretKey；留空则读环境变量 YUANBAO_SECRET_KEY" value={platformEntryDraft.api_key_secondary} onChange={(e) => setPlatformEntryDraft({ ...platformEntryDraft, api_key_secondary: e.target.value })}/></label>}
              </>}
            </div>
            <label className="rounds-checkbox" style={{ marginTop: 10 }}><input type="checkbox" checked={platformEntryDraft.is_active} onChange={(e) => setPlatformEntryDraft({ ...platformEntryDraft, is_active: e.target.checked })}/> 启用这条入口（停用后监测不会用它）</label>
          </>}
        </div>
        <div className="modal-actions"><Button type="submit" disabled={saving}>{saving ? "保存中…" : "创建平台"}</Button><Button variant="secondary" disabled={saving} onClick={closeNewEngine}>取消</Button></div>
      </form>
    </div></div>}
    {entryDraft && canManage && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) { setEntryDraft(null); setEditingEntryId(null); setEntryEngineId(""); } }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="entry-modal-title" style={{ maxHeight: "86vh", overflowY: "auto" }}>
      <div className="modal-header"><div><p className="eyebrow">PLATFORM ENTRY</p><h2 id="entry-modal-title">{editingEntryId ? "编辑入口" : "新增入口"}</h2></div><button className="icon-button" aria-label="关闭" disabled={saving} onClick={() => { setEntryDraft(null); setEditingEntryId(null); setEntryEngineId(""); }}><Icon name="close" size={19}/></button></div>
      <p className="modal-description">{entryEngineName ? `所属平台：${entryEngineName}。` : ""}同一个平台往往有好几种用法（网页版、App、开放接口）。这里登记其中一种「怎么调它」，填好后可以在这条入口上点「测试连接」验证能不能接通。</p>
      <form onSubmit={saveEntry}>
        <div className="form-grid">
          <label className="field"><span className="field-label">入口类型（从哪儿调它）</span><select className="text-input" value={entryDraft.entry_type} onChange={(e) => { const nextType = e.target.value; const nextProtocol = (manualEntryTypes as readonly string[]).includes(nextType) ? "custom" : entryDraft.protocol; setEntryDraft({ ...entryDraft, entry_type: nextType, protocol: nextProtocol, name: entryNameAuto ? suggestEntryName(nextProtocol, nextType) : entryDraft.name }); }}>{entryTypes.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>
          <label className="field"><span className="field-label">入口名称 *（这条调用的别名）</span><input className="text-input" required maxLength={64} placeholder={suggestedEntryName ? `例如 ${suggestedEntryName}` : "例如 豆包搜索（方舟 Responses）"} value={entryDraft.name} onChange={(e) => { setEntryNameAuto(false); setEntryDraft({ ...entryDraft, name: e.target.value }); }}/></label>
          {manualEntry && <p className="field-note" style={{ gridColumn: "1 / -1" }}>这类入口是人打开网页或 App 自己提问，程序不直接调用，因此不用填接口地址、调用协议、模型名和密钥变量名。在备注里写清楚怎么访问、要不要登录就够了；保存后在列表里点「标记已核验」记一次人工确认。</p>}
          {!manualEntry && <>
            <label className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">接口地址（程序把问题发给谁）{endpointRequired ? " *" : "（可留空）"}</span><input className="text-input" type="url" required={endpointRequired} maxLength={2048} placeholder={currentDefaults.endpoint || "https://example.com/api/v1"} value={entryDraft.entry_url} onChange={(e) => setEntryDraft({ ...entryDraft, entry_url: e.target.value })}/><span className="field-hint">{currentDefaults.endpoint ? `留空就用官方默认地址：${currentDefaults.endpoint}` : "选「OpenAI 兼容」必须填完整地址；「自定义」可以留空"}</span></label>
            <label className="field"><span className="field-label">调用协议（按哪种接口格式发请求）</span><select className="text-input" value={entryDraft.protocol} onChange={(e) => { const nextProtocol = e.target.value; setEntryDraft({ ...entryDraft, protocol: nextProtocol, ...protocolAutoFill(nextProtocol), name: entryNameAuto || !entryDraft.name.trim() ? suggestEntryName(nextProtocol, entryDraft.entry_type) : entryDraft.name }); }}>{entryProtocols.map(([value, text]) => <option key={value} value={value} disabled={!protocolAllowedForPlatform(value, entryEngineName, entryEngineVendor)}>{text}</option>)}{!entryProtocols.some(([value]) => value === entryDraft.protocol) && <option value={entryDraft.protocol}>{protocolLabels[entryDraft.protocol] ?? entryDraft.protocol}（跨厂商，需修改）</option>}</select>{entryProtocolMismatch && <span className="form-error" role="alert">当前协议与所属平台厂商不匹配，请改选</span>}{currentDefaults.endpoint ? <span className="field-hint"><button type="button" className="text-link" onClick={() => setEntryDraft({ ...entryDraft, ...protocolAutoFill(entryDraft.protocol), name: entryNameAuto || !entryDraft.name.trim() ? suggestedEntryName : entryDraft.name })}>按这套协议填入默认地址和密钥</button></span> : <span className="field-hint">自定义协议不会自动调用，填不填都不影响监测</span>}</label>
            <label className="field"><span className="field-label">模型名（对方要求的模型标识）{modelRequired ? " *" : "（可留空）"}</span><input className="text-input" required={modelRequired} maxLength={128} placeholder={currentDefaults.model || "例如 doubao-seed-2-1-pro-260915"} value={entryDraft.model_name} onChange={(e) => setEntryDraft({ ...entryDraft, model_name: e.target.value })}/><span className="field-hint">{modelRequired ? `必须填，官方默认：${currentDefaults.model || "参考对方文档"}` : currentDefaults.model ? `留空就用默认：${currentDefaults.model}` : "选「OpenAI 兼容」时必须填"}（模型名不随协议自动填，请按实际模型填写）</span></label>
            <label className="field"><span className="field-label">密钥变量名（只填环境变量名，不填密钥本身）{credentialRequired ? " *" : "（可留空）"}</span><input className="text-input" required={credentialRequired && !entryDraft.api_key.trim()} maxLength={64} pattern="[A-Z][A-Z0-9_]*" placeholder={currentDefaults.credential || "ARK_API_KEY"} value={entryDraft.credential_ref} onChange={(e) => setEntryDraft({ ...entryDraft, credential_ref: e.target.value })}/><span className="field-hint">{credentialRequired ? `必须填，官方默认：${currentDefaults.credential || "参考对方文档"}` : currentDefaults.credential ? `留空就用默认：${currentDefaults.credential}` : "填服务器里配好的环境变量名，例如 XXXX_API_KEY"}</span></label>
            <label className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">API Key（直接在系统里填，加密保存）{editingEntryRecord?.credential_source === "database" ? "（当前已保存，改这里即更换）" : ""}</span><input className="text-input" type="text" autoComplete="new-password" maxLength={4096} placeholder={editingEntryId ? "留空=不改动；要换 Key 就粘贴新的" : "粘贴密钥；留空则读上面的环境变量"} disabled={entryDraft.clear_api_key} value={entryDraft.api_key} onChange={(e) => setEntryDraft({ ...entryDraft, api_key: e.target.value })}/><span className="field-hint">{editingEntryRecord?.credential_source === "database" ? "当前凭据来自系统内填写（密文存储）。" : editingEntryRecord?.credential_source === "environment" ? "当前凭据来自服务器环境变量；在这里填 Key 会改为优先用系统内的。" : "保存后只以密文存库，接口不回显。"}</span></label>
            {needsSecondaryKey(entryDraft.protocol) && <label className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">SecretKey（元宝的第二把密钥）</span><input className="text-input" type="text" autoComplete="new-password" maxLength={4096} placeholder={editingEntryId ? "留空=不改动" : "粘贴 SecretKey；留空则读环境变量 YUANBAO_SECRET_KEY"} disabled={entryDraft.clear_api_key} value={entryDraft.api_key_secondary} onChange={(e) => setEntryDraft({ ...entryDraft, api_key_secondary: e.target.value })}/></label>}
            {editingEntryId && <label className="rounds-checkbox" style={{ gridColumn: "1 / -1" }}><input type="checkbox" checked={entryDraft.clear_api_key} onChange={(e) => setEntryDraft({ ...entryDraft, clear_api_key: e.target.checked, api_key: "", api_key_secondary: "" })}/> 清除系统里保存的密钥（改回读服务器环境变量）</label>}
          </>}
          <label className="field" style={{ gridColumn: "1 / -1" }}><span className="field-label">{manualEntry ? "备注（怎么访问、要不要登录）" : "备注（怎么申请、有什么限制）"}</span><textarea className="text-input knowledge-textarea short" maxLength={2000} placeholder={manualEntry ? "例如：官网可直接访问，无需登录；回答里会带引用来源" : "例如：在控制台申请 key，需要开通联网搜索权限"} value={entryDraft.access_note} onChange={(e) => setEntryDraft({ ...entryDraft, access_note: e.target.value })}/></label>
        </div>
        <label className="rounds-checkbox"><input type="checkbox" checked={entryDraft.supports_search} onChange={(e) => setEntryDraft({ ...entryDraft, supports_search: e.target.checked })}/> 这条入口能返回搜索结果（能用来提问采集）</label>
        <label className="rounds-checkbox"><input type="checkbox" checked={entryDraft.is_active} onChange={(e) => setEntryDraft({ ...entryDraft, is_active: e.target.checked })}/> 启用这条入口（停用后监测不会用它）</label>
        <div className="modal-actions"><Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存入口"}</Button><Button variant="secondary" disabled={saving} onClick={() => { setEntryDraft(null); setEditingEntryId(null); setEntryEngineId(""); }}>取消</Button></div>
      </form>
    </div></div>}
  </div>;
}
