"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, Panel } from "./ui";
import { WorkTabs } from "./work-tabs";
import { workbenchClient } from "@/lib/workbench/client";
import type { ChannelRecord, ContentVersionDetail, ContentVersionRecord, OAuthConnectionRecord, OAuthProviderRecord, PublishAccountRecord, PublishTaskRecord } from "@/lib/workbench/types";

type PublishTab = "tasks" | "accounts" | "create" | "oauth";

function readTab(value: string | null, oauthCallback = false): PublishTab {
  if (value === "accounts" || value === "create" || value === "oauth") return value;
  return oauthCallback ? "oauth" : "tasks";
}

function oauthErrorLabel(code: string | null): string {
  const labels: Record<string, string> = {
    oauth_state_invalid: "授权状态已失效，请重新发起",
    oauth_code_missing: "平台没有返回授权码",
    oauth_provider_not_configured: "该平台尚未完成服务端配置",
    oauth_connection_failed: "平台账号绑定失败，请稍后重试",
    oauth_channel_inactive: "绑定渠道已停用",
    oauth_project_forbidden: "项目权限不匹配",
  };
  return code ? labels[code] || `授权未完成（${code}）` : "授权未完成";
}

function formatOAuthTime(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

export function PublishingWorkspace({ mode, projectId, canRead, canExecute, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canExecute: boolean; onNotice: (message: string) => void;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const oauthState = searchParams.get("oauth");
  const activeTab = readTab(searchParams.get("publish_tab"), Boolean(oauthState));
  const [tasks, setTasks] = useState<PublishTaskRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [accounts, setAccounts] = useState<PublishAccountRecord[]>([]);
  const [channels, setChannels] = useState<ChannelRecord[]>([]);
  const [versions, setVersions] = useState<ContentVersionRecord[]>([]);
  const [versionId, setVersionId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [accountName, setAccountName] = useState("");
  const [accountChannelId, setAccountChannelId] = useState("");
  const [providers, setProviders] = useState<OAuthProviderRecord[]>([]);
  const [connections, setConnections] = useState<OAuthConnectionRecord[]>([]);
  const [oauthChannelId, setOauthChannelId] = useState("");
  const [oauthLoading, setOauthLoading] = useState(false);
  const [oauthLoaded, setOauthLoaded] = useState(false);
  const oauthNoticeRef = useRef("");
  const fallbackTaskKey = useRef("");
  const [selected, setSelected] = useState<PublishTaskRecord | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<ContentVersionDetail | null>(null);
  const [versionLoading, setVersionLoading] = useState(false);
  const [publishedUrl, setPublishedUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function currentBatchKey() {
    try {
      const storageKey = `geo-publish-batch:${projectId}`;
      const current = window.localStorage.getItem(storageKey) || crypto.randomUUID();
      window.localStorage.setItem(storageKey, current);
      return current;
    } catch {
      if (!fallbackTaskKey.current) fallbackTaskKey.current = crypto.randomUUID();
      return fallbackTaskKey.current;
    }
  }

  function newBatch() {
    const next = crypto.randomUUID();
    try { window.localStorage.setItem(`geo-publish-batch:${projectId}`, next); } catch { /* Current tab still works. */ }
    fallbackTaskKey.current = next;
    onNotice("已开始新的发布批次");
  }

  const refresh = useCallback(async () => {
    const [result, accountList, approved, channelList] = await Promise.all([
      workbenchClient.publishTasks(projectId, page), workbenchClient.publishAccounts(projectId),
      workbenchClient.approvedVersions(projectId), workbenchClient.channels(projectId, 1, 100),
    ]);
    setTasks(result.data); setTotal(result.meta?.total ?? result.data.length);
      setAccounts(accountList.data); setVersions(approved.data.filter((item) => item.kind === "channel")); setChannels(channelList.data);
  }, [projectId, page]);

  const loadOAuth = useCallback(() => {
    return Promise.all([
      workbenchClient.oauthProviders(projectId),
      workbenchClient.oauthConnections(projectId),
    ]).then(([providerList, connectionList]) => {
      setProviders(providerList);
      setConnections(connectionList);
      setError("");
    }).catch((cause) => {
      setError(cause instanceof Error ? cause.message : "平台授权信息加载失败");
    }).finally(() => {
      setOauthLoaded(true);
    });
  }, [projectId]);

  async function refreshOAuth() {
    setOauthLoading(true);
    try {
      await loadOAuth();
    } finally {
      setOauthLoading(false);
    }
  }

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all" || activeTab !== "oauth") return;
    void loadOAuth();
  }, [mode, canRead, projectId, activeTab, loadOAuth]);

  useEffect(() => {
    if (oauthState !== "connected" && oauthState !== "error") return;
    const errorCode = searchParams.get("oauth_error");
    const key = `${oauthState}:${errorCode ?? ""}:${searchParams.get("connection_id") ?? ""}`;
    if (oauthNoticeRef.current === key) return;
    oauthNoticeRef.current = key;
    if (oauthState === "connected") {
      onNotice("平台账号已连接，令牌已加密托管");
    } else {
      onNotice(`平台授权失败：${oauthErrorLabel(errorCode)}`);
    }
    const params = new URLSearchParams(searchParams.toString());
    for (const name of ["oauth", "oauth_error", "provider", "connection_id"]) params.delete(name);
    params.set("section", "publishing");
    params.set("publish_tab", "oauth");
    if (projectId && projectId !== "all") params.set("project_id", projectId);
    router.replace(`/workbench?${params.toString()}`, { scroll: false });
  }, [oauthState, searchParams, onNotice, projectId, router]);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([
      workbenchClient.publishTasks(projectId, page), workbenchClient.publishAccounts(projectId),
      workbenchClient.approvedVersions(projectId), workbenchClient.channels(projectId, 1, 100),
    ]).then(([result, accountList, approved, channelList]) => {
      if (!active) return;
      setTasks(result.data); setTotal(result.meta?.total ?? result.data.length);
      setAccounts(accountList.data); setVersions(approved.data.filter((item) => item.kind === "channel")); setChannels(channelList.data); setError("");
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "发布数据加载失败"); });
    return () => { active = false; };
  }, [mode, projectId, canRead, page]);

  useEffect(() => {
    if (!selected || mode !== "live" || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.contentVersion(projectId, selected.version_id)
      .then((detail) => { if (active) setSelectedVersion(detail); })
      .catch((cause) => { if (active) onNotice(cause instanceof Error ? cause.message : "读取发布正文失败"); })
      .finally(() => { if (active) setVersionLoading(false); });
    return () => { active = false; };
  }, [selected, mode, projectId, onNotice]);

  async function copyBody() {
    if (!selectedVersion) return;
    try {
      await navigator.clipboard.writeText(selectedVersion.body);
      onNotice("正文已复制，可粘贴到平台编辑器");
    } catch {
      onNotice("浏览器拒绝剪贴板访问，请手动选中正文复制");
    }
  }

  function openUrl(url?: string | null, label = "发布后台") {
    if (!url) { onNotice(`当前渠道没有配置${label}地址，请先在渠道台账补充`); return; }
    window.open(url, "_blank", "noopener,noreferrer");
  }

  async function addAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!accountChannelId || !accountName.trim()) return; setBusy(true);
    try {
      await workbenchClient.createPublishAccount(projectId, { account_name: accountName.trim(), channel_id: accountChannelId });
      setAccountName(""); await refresh(); onNotice("发布账号已登记");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "账号登记失败"); }
    finally { setBusy(false); }
  }

  async function addTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const account = accounts.find((item) => item.id === accountId);
    if (!account || !versionId) return; setBusy(true);
    try {
      const result = await workbenchClient.publishAction(projectId, "publish-task", {
        account_id: account.id, channel_id: account.channel_id, version_id: versionId,
        task_key: currentBatchKey(), publish_mode: "manual",
      }) as { reused?: boolean };
      await refresh(); onNotice(result.reused ? "已复用现有发布任务" : "发布任务已创建");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "发布任务创建失败"); }
    finally { setBusy(false); }
  }

  async function action(kind: "publish-attempt" | "publish-receipt" | "publish-verify", input: Record<string, unknown>) {
    if (!selected) return; setBusy(true);
    try {
      await workbenchClient.publishAction(projectId, kind, input, selected.id);
      const result = await workbenchClient.publishTasks(projectId, page);
      setTasks(result.data); setSelected(result.data.find((row) => row.id === selected.id) ?? null);
      setPublishedUrl(""); onNotice("发布状态已更新");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "发布操作失败"); }
    finally { setBusy(false); }
  }

  async function connectProvider(providerCode: string) {
    setBusy(true); setError("");
    try {
      const result = await workbenchClient.authorizeOAuth(projectId, {
        provider_code: providerCode,
        ...(oauthChannelId ? { channel_id: oauthChannelId } : {}),
        return_path: "/workbench?section=publishing&publish_tab=oauth",
      });
      window.location.assign(result.authorization_url);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "发起平台授权失败");
    } finally {
      setBusy(false);
    }
  }

  async function oauthAction(connectionId: string, kind: "refresh" | "revoke") {
    const connection = connections.find((item) => item.id === connectionId);
    if (kind === "revoke" && !window.confirm(`确认撤销「${connection?.external_account_name || connection?.external_account_id || "该账号"}」的平台授权？撤销后需要重新授权才能恢复发布能力。`)) return;
    setBusy(true); setError("");
    try {
      if (kind === "refresh") await workbenchClient.refreshOAuthConnection(projectId, connectionId);
      else await workbenchClient.revokeOAuthConnection(projectId, connectionId);
      await refreshOAuth();
      onNotice(kind === "refresh" ? "令牌已刷新" : "平台授权已撤销");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (kind === "refresh" ? "令牌刷新失败" : "撤销授权失败"));
    } finally {
      setBusy(false);
    }
  }

  function selectTab(tab: PublishTab) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("section", "publishing");
    if (projectId && projectId !== "all") params.set("project_id", projectId);
    if (tab === "tasks") params.delete("publish_tab");
    else params.set("publish_tab", tab);
    router.push(`/workbench?${params.toString()}`, { scroll: false });
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">发布闭环请切换到真实接口模式。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有发布查看权限。</p></Panel>;
  const selectedChannel = selected ? channels.find((row) => row.id === selected.channel_id) : undefined;
  const selectedPublishUrl = selectedChannel?.publish_url || (selectedChannel?.primary_domain ? `https://${selectedChannel.primary_domain}` : "");
  const tabs: { id: PublishTab; label: string; count?: number }[] = [
    { id: "tasks", label: "发布任务", count: total },
    { id: "oauth", label: "平台授权" },
    ...(canExecute ? [{ id: "accounts" as PublishTab, label: "登记账号", count: accounts.length }, { id: "create" as PublishTab, label: "新建任务" }] : []),
  ];
  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    {!canExecute && <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号可以查看发布任务，但没有执行权限。登记发布账号、创建任务需要运营编辑（publish.execute）；项目管理员负责内容审批。</p></Panel>}
    <WorkTabs items={tabs} active={canExecute ? activeTab : "tasks"} onChange={selectTab} ariaLabel="内容发布视图"/>
    {activeTab === "oauth" && <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>平台授权</h3><p>通用 OAuth 授权码 + PKCE；令牌只保存在服务端并加密，支持刷新与撤销</p></div><Button variant="secondary" disabled={oauthLoading} onClick={() => void refreshOAuth()}>{oauthLoading ? "读取中…" : "刷新"}</Button></div>
      {!canExecute && <p className="knowledge-footnote">当前账号可以查看授权状态；连接、刷新和撤销需要运营编辑（publish.execute）。</p>}
      <label className="field oauth-channel-field"><span className="field-label">绑定渠道（可选）</span><select className="text-input" value={oauthChannelId} onChange={(e) => setOauthChannelId(e.target.value)}><option value="">不绑定，作为项目级账号</option>{channels.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><span className="field-hint">绑定后该连接只用于对应渠道；不绑定则可用于该项目下的发布任务。</span></label>
      {!oauthLoaded ? <div className="oauth-empty"><strong>正在读取平台授权…</strong><span>正在同步 provider 配置与已授权账号。</span></div> : providers.length ? <div className="oauth-provider-grid">{providers.map((provider) => <div className="oauth-provider-card" key={provider.code}>
        <div className="oauth-provider-head"><div><strong>{provider.name}</strong><small>{provider.code}</small></div><Badge tone="blue">OAuth 2.0</Badge></div>
        <div className="oauth-scope-list">{provider.scopes.length ? provider.scopes.map((scope) => <span className="oauth-scope" key={scope}>{scope}</span>) : <span className="oauth-scope">默认授权范围</span>}</div>
        <Button disabled={busy || !canExecute} onClick={() => void connectProvider(provider.code)}>{busy ? "处理中…" : "连接账号"}</Button>
      </div>)}</div> : <div className="oauth-empty"><strong>尚未配置平台</strong><span>服务端还没有可用的 OAuth provider。配置平台地址、客户端凭据和回调地址后，这里会出现可连接的平台。</span></div>}
      <div className="oauth-section-title"><h4>已授权账号</h4><span>{oauthLoaded ? `${connections.length} 个连接` : "读取中"}</span></div>
      {!oauthLoaded ? <p className="knowledge-empty">正在读取已授权账号…</p> : connections.length ? <div className="oauth-connection-list">{connections.map((connection) => <div className={`oauth-connection-card oauth-status-${connection.status}`} key={connection.id}>
        <div className="oauth-connection-head"><div><strong>{connection.external_account_name || connection.external_account_id}</strong><small>{connection.provider_name} · {connection.external_account_id}{connection.external_account_email ? ` · ${connection.external_account_email}` : ""}</small></div><Badge tone={connection.status === "connected" ? "green" : connection.status === "error" ? "red" : "slate"}>{connection.status === "connected" ? "已连接" : connection.status === "revoked" ? "已撤销" : "异常"}</Badge></div>
        <div className="oauth-meta">
          <div><span>绑定渠道</span><strong>{connection.channel_id ? channels.find((row) => row.id === connection.channel_id)?.name || connection.channel_id.slice(0, 8) : "项目级账号"}</strong></div>
          <div><span>授权范围</span><strong>{connection.scopes.length ? connection.scopes.join("、") : "—"}</strong></div>
          <div><span>令牌到期</span><strong>{formatOAuthTime(connection.expires_at)}</strong></div>
          <div><span>最近刷新</span><strong>{formatOAuthTime(connection.last_refreshed_at)}</strong></div>
        </div>
        <div className="oauth-connection-actions">
          {connection.status === "connected" && canExecute && <Button variant="secondary" disabled={busy} onClick={() => void oauthAction(connection.id, "refresh")}>刷新令牌</Button>}
          {connection.status === "connected" && canExecute && <Button variant="danger" disabled={busy} onClick={() => void oauthAction(connection.id, "revoke")}>撤销授权</Button>}
          {connection.status === "revoked" && <span className="knowledge-footnote">已撤销，重新连接会更新同一账号的授权。</span>}
          {connection.status === "error" && <span className="knowledge-footnote">连接异常，请撤销后重新授权或检查平台配置。</span>}
        </div>
      </div>)}</div> : <div className="oauth-empty oauth-empty-compact"><strong>还没有已授权账号</strong><span>选择上方平台并完成授权后，连接会出现在这里。</span></div>}
    </Panel>}
    {(activeTab === "tasks" || (!canExecute && activeTab !== "oauth")) && <>
      <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>发布任务</h3><p>共 {total} 条；回执不明时先核实，再决定是否重试</p></div></div>
        <div className="knowledge-list">{tasks.map((task) => <button className="knowledge-item" type="button" key={task.id} onClick={() => { setSelected(task); setSelectedVersion(null); setVersionLoading(true); setPublishedUrl(""); }}><span><strong>{task.id.slice(0, 8)}</strong><small>内容版本 {task.version_id.slice(0, 8)} · 渠道 {channels.find((row) => row.id === task.channel_id)?.name || task.channel_id.slice(0, 8)} · trace {task.trace_id ? `${task.trace_id.slice(0, 12)}…` : "未继承"}</small></span><Badge tone={task.status === "published" ? "green" : task.status === "unknown" ? "amber" : task.status === "failed" ? "red" : "blue"}>{task.status}</Badge></button>)}{!tasks.length && <p className="knowledge-empty">暂无发布任务</p>}</div>
        {total > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><span>{page} / {Math.ceil(total / 20)}</span><Button variant="secondary" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>下一页</Button></div>}
      </Panel>
      {selected && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>任务 {selected.id.slice(0, 8)}</h3><p>状态 {selected.status} · 手动发布台账，不调用平台 API</p></div><Button variant="secondary" onClick={() => setSelected(null)}>关闭</Button></div>
        <p className="knowledge-footnote">渠道：{selectedChannel?.name || selected.channel_id.slice(0, 8)} · 发布入口：{selectedPublishUrl || "未配置"}</p>
        {selectedVersion && <div style={{ border: "1px solid #d7dce3", borderRadius: 10, padding: 12, margin: "10px 0", background: "#fbfcfd" }}>
          <strong>{selectedVersion.title} · v{selectedVersion.version_no}</strong>
          <p className="knowledge-footnote">hash {selectedVersion.content_hash.slice(0, 16)}… · {selectedVersion.body.length} 字符</p>
          <div style={{ maxHeight: 260, overflow: "auto", whiteSpace: "pre-wrap", lineHeight: 1.7, fontSize: 13, margin: "8px 0" }}>{selectedVersion.body}</div>
          <div className="knowledge-actions"><Button variant="secondary" disabled={!selectedVersion.body} onClick={() => void copyBody()}>复制正文</Button><Button variant="secondary" onClick={() => openUrl(selectedPublishUrl, "发布后台地址")}>打开发布后台</Button><Button variant="secondary" onClick={() => openUrl(selectedChannel?.login_url, "登录地址")}>打开登录页</Button></div>
        </div>}
        {versionLoading && <p className="knowledge-empty">正在读取已审批正文…</p>}
        {!selectedVersion && !versionLoading && <p className="knowledge-footnote">正文读取失败或版本不可用，仍可按原始流程记录发布结果。</p>}
        <p className="knowledge-footnote">trace_id：{selected.trace_id || "未继承（内容版本没有唯一监测引用 trace）"}</p>
        {canExecute && ["pending", "needs_review"].includes(selected.status) && <><p className="knowledge-footnote">完成实际发布操作后，按真实结果记录尝试。</p><div className="knowledge-actions"><Button disabled={busy} onClick={() => void action("publish-attempt", { result: "success", mode: "manual" })}>记录已发出</Button><Button variant="secondary" disabled={busy} onClick={() => void action("publish-attempt", { result: "unknown", mode: "manual" })}>回执不明</Button><Button variant="secondary" disabled={busy} onClick={() => void action("publish-attempt", { result: "failed", mode: "manual" })}>记录失败</Button></div></>}
        {canExecute && ["publishing", "unknown"].includes(selected.status) && <label className="field"><span className="field-label">真实发布 URL</span><input className="text-input" type="url" placeholder="https://..." value={publishedUrl} onChange={(e) => setPublishedUrl(e.target.value)}/></label>}
        {canExecute && selected.status === "publishing" && <Button disabled={busy || !publishedUrl} onClick={() => void action("publish-receipt", { published_url: publishedUrl })}>回填回执并结案</Button>}
        {canExecute && selected.status === "unknown" && <div className="knowledge-actions"><Button disabled={busy || !publishedUrl} onClick={() => void action("publish-verify", { outcome: "published", published_url: publishedUrl })}>核实已发出</Button><Button variant="secondary" disabled={busy} onClick={() => void action("publish-verify", { outcome: "not_published" })}>核实未发出，回待执行</Button></div>}
      </Panel>}
    </>}
    {activeTab === "accounts" && canExecute && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>登记发布账号</h3><p>仅登记账号名称和渠道；密钥由服务端管理</p></div></div>
      {!!accounts.length && <div className="knowledge-list">{accounts.map((account) => <div className="knowledge-item" key={account.id}><span><strong>{account.account_name}</strong><small>{channels.find((row) => row.id === account.channel_id)?.name || account.channel_id.slice(0, 8)}</small></span><Badge tone={account.is_active ? "green" : "slate"}>{account.is_active ? "启用" : "停用"}</Badge></div>)}</div>}
      {!accounts.length && <p className="knowledge-empty">还没有登记发布账号</p>}
      <form onSubmit={addAccount}>
        <label className="field"><span className="field-label">渠道</span><select className="text-input" required value={accountChannelId} onChange={(e) => setAccountChannelId(e.target.value)}><option value="">选择渠道</option>{channels.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="field"><span className="field-label">发布账号名称</span><input className="text-input" required value={accountName} onChange={(e) => setAccountName(e.target.value)}/></label>
        <Button type="submit" disabled={busy}>登记账号</Button>
      </form>
    </Panel>}
    {activeTab === "create" && canExecute && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>新建发布任务</h3><p>同一表单再次提交会复用任务；新一轮发布请先新建批次</p></div></div><form onSubmit={addTask}>
      <label className="field"><span className="field-label">已审批内容版本</span><select className="text-input" required value={versionId} onChange={(e) => setVersionId(e.target.value)}><option value="">选择版本</option>{versions.map((item) => <option key={item.version_id} value={item.version_id}>{item.title} · v{item.version_no}</option>)}</select></label>
      <label className="field"><span className="field-label">发布账号</span><select className="text-input" required value={accountId} onChange={(e) => setAccountId(e.target.value)}><option value="">选择账号</option>{accounts.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.account_name} · {channels.find((row) => row.id === item.channel_id)?.name || "渠道"}</option>)}</select></label>
      <div className="knowledge-actions"><Button type="submit" disabled={busy}>创建任务</Button><Button type="button" variant="secondary" disabled={busy} onClick={newBatch}>新建批次</Button></div>
    </form></Panel>}
  </div>;
}
