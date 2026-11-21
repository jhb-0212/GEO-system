"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, Icon, Panel } from "./ui";
import { WorkTabs } from "./work-tabs";
import { PageApprovalsPanel } from "./page-approvals-panel";
import { workbenchClient, WORKBENCH_PAGE_SIZE } from "@/lib/workbench/client";
import { formatSerialNo } from "@/lib/workbench/format";
import type { ChannelRecord, ContentVersionDetail, ContentVersionRecord, OAuthConnectionRecord, OAuthProviderRecord, PublishAccountRecord, PublishReceiptRecord, PublishTaskRecord } from "@/lib/workbench/types";

type PublishTab = "tasks" | "receipts" | "accounts" | "approvals" | "create" | "oauth";

function readTab(value: string | null, oauthCallback = false): PublishTab {
  if (value === "receipts" || value === "accounts" || value === "approvals" || value === "create" || value === "oauth") return value;
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

const PUBLISH_TASK_STATUS_LABELS: Record<string, string> = {
  pending: "待发布",
  publishing: "待补链接",
  published: "已发布",
  unknown: "待确认",
  failed: "发布失败",
  needs_review: "待复核",
  cancelled: "已取消",
};

function publishTaskStatusLabel(status: string) {
  return PUBLISH_TASK_STATUS_LABELS[status] ?? status;
}

const PUBLISH_HANDOFF_LABELS: Record<string, string> = {
  qr_required: "平台要求扫码，已转人工",
  captcha_required: "平台要求验证码，已转人工",
  session_expired: "平台登录态已失效，已转人工",
  login_blocked: "平台登录被阻断，已转人工",
  rate_limited: "平台限流，已转人工",
  browser_session_required: "需浏览器登录态，已转人工",
  oauth_connection_missing: "未绑定平台授权，已转人工",
  oauth_connection_revoked: "平台授权已撤销，已转人工",
  oauth_connection_error: "平台授权异常，已转人工",
  oauth_token_missing: "平台令牌缺失，已转人工",
  oauth_token_expired: "平台令牌已过期，已转人工",
  other: "已转人工",
};

function publishHandoffLabel(reason?: string | null) {
  return reason ? PUBLISH_HANDOFF_LABELS[reason] ?? `已转人工：${reason}` : "";
}

/** 发布用纯文本：去掉 Markdown 标记（# 标题、** 加粗、* 斜体、> 引用、分隔线），复制后可直接粘进平台编辑器。 */
function plainPublishText(body: string): string {
  return body
    .replace(/^[ \t]*\*\*(.+?)\*\*[ \t]*$/gm, "$1\n")
    .replace(/^[ \t]{0,3}#{1,6}[ \t]+/gm, "")
    .replace(/^[ \t]{0,3}>[ \t]?/gm, "")
    .replace(/^[ \t]*[-*_]{3,}[ \t]*$/gm, "")
    .replace(/\*\*|__|~~|`/g, "")
    .replace(/\*/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** 发布流程里只显示账号名，去掉“（官方API适配器已接）/（人工发布）”这类实现备注；账号管理页仍保留全名。 */
function operatorAccountName(name: string | null | undefined): string {
  if (!name) return "";
  return name.replace(/[（(][^（）()]*(?:API|人工发布)[^（）()]*[）)]/g, "").trim() || name;
}

export function PublishingWorkspace({ mode, projectId, canRead, canExecute, canCancel, canApprove, canDeleteAccounts, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canExecute: boolean; canCancel: boolean; canApprove: boolean; canDeleteAccounts: boolean; onNotice: (message: string) => void;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const oauthState = searchParams.get("oauth");
  const activeTab = readTab(searchParams.get("publish_tab"), Boolean(oauthState));
  const [tasks, setTasks] = useState<PublishTaskRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [receipts, setReceipts] = useState<PublishReceiptRecord[]>([]);
  const [receiptTotal, setReceiptTotal] = useState(0);
  const [receiptPage, setReceiptPage] = useState(1);
  const [receiptLoadedPage, setReceiptLoadedPage] = useState<number | null>(null);
  const [receiptError, setReceiptError] = useState("");
  const [accounts, setAccounts] = useState<PublishAccountRecord[]>([]);
  const [channels, setChannels] = useState<ChannelRecord[]>([]);
  const [versions, setVersions] = useState<ContentVersionRecord[]>([]);
  const [versionId, setVersionId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [accountName, setAccountName] = useState("");
  const [accountChannelId, setAccountChannelId] = useState("");
  const [accountOauthId, setAccountOauthId] = useState("");
  const [editingAccountId, setEditingAccountId] = useState("");
  const [editAccountName, setEditAccountName] = useState("");
  const [editAccountNotes, setEditAccountNotes] = useState("");
  const [editAccountOauthId, setEditAccountOauthId] = useState("");
  const [editAccountActive, setEditAccountActive] = useState(true);
  const [providers, setProviders] = useState<OAuthProviderRecord[]>([]);
  const [connections, setConnections] = useState<OAuthConnectionRecord[]>([]);
  const [oauthChannelId, setOauthChannelId] = useState("");
  const [oauthLoading, setOauthLoading] = useState(false);
  const [oauthLoaded, setOauthLoaded] = useState(false);
  const oauthNoticeRef = useRef("");
  const fallbackTaskKey = useRef("");
  const [selected, setSelected] = useState<PublishTaskRecord | null>(null);
  const [cancelConfirm, setCancelConfirm] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState<ContentVersionDetail | null>(null);
  const [versionLoading, setVersionLoading] = useState(false);
  const [publishedUrl, setPublishedUrl] = useState("");
  const [bodyExpanded, setBodyExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [deleteAccountTarget, setDeleteAccountTarget] = useState<PublishAccountRecord | null>(null);
  const [deleteAccountBusy, setDeleteAccountBusy] = useState(false);
  const [deleteAccountError, setDeleteAccountError] = useState("");

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

  function connectionsForChannel(channelId: string) {
    if (!channelId) return connections.filter((item) => item.status === "connected");
    return connections.filter((item) => item.status === "connected" && (!item.channel_id || item.channel_id === channelId));
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
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    if (!["accounts", "create"].includes(activeTab) || oauthLoaded) return;
    void loadOAuth();
  }, [mode, canRead, projectId, activeTab, oauthLoaded, loadOAuth]);

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
    if (mode !== "live" || !canRead || !projectId || projectId === "all" || activeTab !== "receipts") return;
    let active = true;
    workbenchClient.publishReceipts(projectId, receiptPage, {}, WORKBENCH_PAGE_SIZE)
      .then((result) => {
        if (!active) return;
        setReceipts(result.data);
        setReceiptTotal(result.meta?.total ?? result.data.length);
        setReceiptLoadedPage(receiptPage);
        setReceiptError("");
      })
      .catch((cause) => {
        if (!active) return;
        setReceipts([]);
        setReceiptLoadedPage(receiptPage);
        setReceiptError(cause instanceof Error ? cause.message : "发布结果加载失败");
      });
    return () => { active = false; };
  }, [mode, canRead, projectId, activeTab, receiptPage]);

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
      await navigator.clipboard.writeText(plainPublishText(selectedVersion.body));
      onNotice("正文已按纯文本复制（无 # / * 等标记），可直接粘贴发布");
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
      await workbenchClient.createPublishAccount(projectId, {
        account_name: accountName.trim(),
        channel_id: accountChannelId,
        oauth_connection_id: accountOauthId || null,
      });
      setAccountName(""); setAccountOauthId(""); await refresh(); onNotice("发布账号已登记");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "账号登记失败"); }
    finally { setBusy(false); }
  }

  function startEditAccount(account: PublishAccountRecord) {
    setEditingAccountId(account.id);
    setEditAccountName(account.account_name);
    setEditAccountNotes(account.notes ?? "");
    setEditAccountOauthId(account.oauth_connection_id ?? "");
    setEditAccountActive(account.is_active);
    setError("");
  }

  function cancelEditAccount() {
    setEditingAccountId(""); setEditAccountName(""); setEditAccountNotes(""); setEditAccountOauthId(""); setEditAccountActive(true);
  }

  function askDeleteAccount(account: PublishAccountRecord) {
    if (!canDeleteAccounts) return;
    setDeleteAccountError("");
    setDeleteAccountTarget(account);
  }

  function closeDeleteAccount() {
    if (deleteAccountBusy) return;
    setDeleteAccountTarget(null);
    setDeleteAccountError("");
  }

  async function confirmDeleteAccount() {
    const target = deleteAccountTarget;
    if (!target || !canDeleteAccounts || deleteAccountBusy) return;
    setDeleteAccountBusy(true);
    setDeleteAccountError("");
    try {
      const result = await workbenchClient.deletePublishAccount(projectId, target.id);
      if (editingAccountId === target.id) cancelEditAccount();
      setDeleteAccountTarget(null);
      await refresh();
      onNotice(`已删除发布账号「${result.name || target.account_name}」`);
    } catch (cause) {
      setDeleteAccountError(cause instanceof Error ? cause.message : "删除发布账号失败");
    } finally {
      setDeleteAccountBusy(false);
    }
  }

  async function saveAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingAccountId || !editAccountName.trim()) return;
    setBusy(true); setError("");
    try {
      await workbenchClient.updatePublishAccount(projectId, editingAccountId, {
        account_name: editAccountName.trim(),
        notes: editAccountNotes.trim() || null,
        is_active: editAccountActive,
        oauth_connection_id: editAccountOauthId || null,
      });
      cancelEditAccount(); await refresh(); onNotice("发布账号已更换");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "账号更换失败"); }
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

  async function reloadTask(taskId: string, message: string) {
    const result = await workbenchClient.publishTasks(projectId, page);
    setTasks(result.data);
    setSelected(result.data.find((row) => row.id === taskId) ?? null);
    setPublishedUrl("");
    setBodyExpanded(false);
    onNotice(message);
  }

  async function cancelSelectedTask() {
    if (!selected || !canCancel || busy) return;
    setBusy(true); setError("");
    try {
      await workbenchClient.cancelPublishTask(projectId, selected.id);
      setCancelConfirm(false);
      await reloadTask(selected.id, "发布任务已取消；任务记录保留，可重新建一条发布");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "取消任务失败");
    } finally {
      setBusy(false);
    }
  }

  async function handoffSelectedTask(reason: "qr_required" | "captcha_required") {
    if (!selected || !canExecute || busy) return;
    const label = reason === "qr_required" ? "二维码" : "验证码";
    if (!window.confirm(`确认「${label}阻断」并转人工？任务会进入待复核，不会自动重发。`)) return;
    setBusy(true); setError("");
    try {
      await workbenchClient.publishAction(
        projectId,
        "publish-handoff",
        { reason, note: `平台要求${label}，转人工处理` },
        selected.id,
      );
      await reloadTask(selected.id, `已转人工：平台要求${label}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "转人工失败");
    } finally {
      setBusy(false);
    }
  }

  async function completePublish() {
    if (!selected) return;
    const url = publishedUrl.trim();
    if (!url) {
      setError("发布完成后，把文章链接粘贴到这里，再点完成发布。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (selected.status === "pending" || selected.status === "needs_review") {
        await workbenchClient.publishAction(projectId, "publish-attempt", { result: "success", mode: "manual" }, selected.id);
        await workbenchClient.publishAction(projectId, "publish-receipt", { published_url: url }, selected.id);
      } else if (selected.status === "publishing") {
        await workbenchClient.publishAction(projectId, "publish-receipt", { published_url: url }, selected.id);
      } else if (selected.status === "unknown") {
        await workbenchClient.publishAction(projectId, "publish-verify", { outcome: "published", published_url: url }, selected.id);
      } else {
        return;
      }
      await reloadTask(selected.id, "发布记录已完成");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "发布记录完成失败");
    } finally {
      setBusy(false);
    }
  }

  async function markUncertain() {
    if (!selected || !["pending", "needs_review"].includes(selected.status)) return;
    setBusy(true); setError("");
    try {
      await workbenchClient.publishAction(projectId, "publish-attempt", { result: "unknown", mode: "manual" }, selected.id);
      await reloadTask(selected.id, "已标记为待确认，稍后可以回来核实");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "状态更新失败");
    } finally {
      setBusy(false);
    }
  }

  async function markNotPublished() {
    if (!selected || !["pending", "needs_review"].includes(selected.status)) return;
    setBusy(true); setError("");
    try {
      await workbenchClient.publishAction(projectId, "publish-attempt", { result: "failed", mode: "manual" }, selected.id);
      await reloadTask(selected.id, "已记录为发布失败");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "状态更新失败");
    } finally {
      setBusy(false);
    }
  }

  async function confirmNotPublished() {
    if (!selected || selected.status !== "unknown") return;
    setBusy(true); setError("");
    try {
      await workbenchClient.publishAction(projectId, "publish-verify", { outcome: "not_published" }, selected.id);
      await reloadTask(selected.id, "已确认没有发出，任务回到待发布");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "核实失败");
    } finally {
      setBusy(false);
    }
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
  const selectedOrdinal = selected ? formatSerialNo(selected.serial_no) : "";
  const canViewAccounts = canExecute || canDeleteAccounts;
  const tabs: { id: PublishTab; label: string; count?: number }[] = [
    { id: "tasks", label: "发布任务", count: total },
    { id: "receipts", label: "发布结果", count: receiptLoadedPage === null ? undefined : receiptTotal },
    { id: "approvals", label: "页面审批" },
    ...(canViewAccounts ? [{ id: "accounts" as PublishTab, label: "发布账号", count: accounts.length }] : []),
    ...(canExecute ? [{ id: "create" as PublishTab, label: "新建发布" }] : []),
  ];
  const currentTab: PublishTab = activeTab === "accounts" && !canViewAccounts ? "tasks" : activeTab === "create" && !canExecute ? "tasks" : activeTab;
  const receiptLoading = activeTab === "receipts" && receiptLoadedPage !== receiptPage;
  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    {!canExecute && <div className="knowledge-notice" role="status"><Icon name="lock" size={18}/><div><strong>当前账号没有发布执行权限</strong><p>{canCancel ? "可以查看发布任务、取消待发布任务" : "可以查看发布任务"}{canDeleteAccounts ? "、删除没有任务引用的发布账号" : ""}；新建发布和登记发布账号需要运营编辑权限。</p></div></div>}
    <WorkTabs items={tabs} active={currentTab} onChange={selectTab} ariaLabel="内容发布视图"/>
    {currentTab === "oauth" && <Panel className="knowledge-list-panel">
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
          <div><span>绑定渠道</span><strong>{connection.channel_id ? channels.find((row) => row.id === connection.channel_id)?.name || "渠道已删除" : "项目级账号"}</strong></div>
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
    {currentTab === "tasks" && <>
      <Panel className={`knowledge-list-panel${canExecute ? "" : " publishing-task-panel-compact"}`}><div className="panel-heading"><div><h3>发布任务</h3><p>共 {total} 条；点开一条，按提示完成发布</p></div></div>
        <div className="knowledge-list">{tasks.map((task) => <button className="knowledge-item" type="button" key={task.id} onClick={() => { setSelected(task); setCancelConfirm(false); setSelectedVersion(null); setVersionLoading(true); setPublishedUrl(""); setBodyExpanded(false); setError(""); }}><span><strong>发布任务 #{formatSerialNo(task.serial_no)}</strong><small>{task.version_title ? `《${task.version_title}》` : "未命名内容"} · {channels.find((row) => row.id === task.channel_id)?.name || "平台未匹配"}{task.account_name ? ` · ${operatorAccountName(task.account_name)}` : ""}</small>{task.budget_title && <small className="publish-budget-hint">预算归属：{task.budget_title}</small>}</span><Badge tone={task.status === "published" ? "green" : task.status === "unknown" ? "amber" : task.status === "failed" ? "red" : task.status === "cancelled" ? "slate" : "blue"}>{publishTaskStatusLabel(task.status)}</Badge></button>)}{!tasks.length && <p className="knowledge-empty">还没有发布任务。到「新建发布」选择一篇已审批的稿子即可开始。</p>}</div>
        {total > WORKBENCH_PAGE_SIZE && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={page <= 1} onClick={() => { setSelected(null); setPage(page - 1); }}>上一页</Button><span>{page} / {Math.ceil(total / WORKBENCH_PAGE_SIZE)}</span><Button variant="secondary" disabled={page * WORKBENCH_PAGE_SIZE >= total} onClick={() => { setSelected(null); setPage(page + 1); }}>下一页</Button></div>}
      </Panel>
      {selected && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setSelected(null); }}>
        <div className="modal publish-task-modal" role="dialog" aria-modal="true" aria-labelledby="publish-task-title">
        <div className="modal-header"><div><p className="eyebrow">发布任务详情</p><h2 id="publish-task-title">发布任务 #{selectedOrdinal || "—"}</h2><p className="modal-description">{selectedChannel?.name || "平台未匹配"} · {publishTaskStatusLabel(selected.status)}</p></div><Button variant="secondary" onClick={() => setSelected(null)}>关闭</Button></div>
        <div className="publish-task-meta">
          <strong>{selected.version_title ? `《${selected.version_title}》` : "未命名内容"}</strong>
          <span>第 {selected.version_no} 版{selected.account_name ? ` · 发布账号：${operatorAccountName(selected.account_name)}` : ""}</span>
        </div>
        {selected.receipt_id && <div className="publish-receipt-result">
          <div className="publish-receipt-result-head"><strong>发布结果</strong><Badge tone={selected.budget_title ? "green" : "slate"}>{selected.budget_title ? "已挂预算" : "未挂预算"}</Badge></div>
          {selected.published_url && <div className="publish-receipt-line">发布链接：<a href={selected.published_url} target="_blank" rel="noreferrer">{selected.published_url}</a></div>}
          <div className="publish-receipt-line">回填时间：{formatOAuthTime(selected.received_at ?? null)}</div>
          {selected.budget_title && <div className="publish-receipt-line">预算归属：{selected.budget_title}</div>}
        </div>}
        {selected.status === "published" && <p className="publish-result-note publish-result-success">这条发布已经完成，不需要再操作。</p>}
        {selected.status === "cancelled" && <p className="publish-result-note">这条发布已取消。</p>}
        {selected.status === "failed" && <p className="publish-result-note publish-result-danger">这次没有发出去。可以回到「新建发布」重新建一条任务。</p>}
        {selected.handoff_reason && <p className="publish-result-note">{publishHandoffLabel(selected.handoff_reason)}{selected.handoff_note ? `：${selected.handoff_note}` : ""}</p>}
        {!["published", "cancelled", "failed"].includes(selected.status) && <div className="publish-flow-card">
          <div className="publish-flow-step">
            <span className="publish-step-no">1</span>
            <div className="publish-step-copy"><strong>复制正文</strong><p>正文已按审批版本准备好，复制后粘贴到平台编辑器。</p></div>
            <Button variant="secondary" disabled={!selectedVersion?.body} onClick={() => void copyBody()}>复制正文</Button>
          </div>
          <div className="publish-flow-step">
            <span className="publish-step-no">2</span>
            <div className="publish-step-copy"><strong>到平台发布</strong><p>{selectedPublishUrl ? "打开发布后台，按平台正常流程发布。" : "这个平台还没有配置发布入口，请联系管理员补充。"}</p></div>
            <Button variant="secondary" onClick={() => openUrl(selectedPublishUrl, "发布后台地址")}>打开发布后台</Button>
          </div>
        </div>}
        {canExecute && ["pending", "needs_review", "publishing", "unknown"].includes(selected.status) && <div className="publish-finish-card">
          <div className="publish-finish-head"><strong>{selected.status === "unknown" ? "确认发布结果" : "发布完成后"}</strong><span>{selected.status === "publishing" ? "已记录发出，补上文章链接就完成。" : "把平台上的文章链接粘贴到这里。"}</span></div>
          <label className="field"><span className="field-label">文章链接</span><input className="text-input" type="url" placeholder="https://…" value={publishedUrl} onChange={(e) => setPublishedUrl(e.target.value)}/><small>院校类渠道、招生和招聘页面，要先有同地址的已通过页面审批，否则发布结果会被拒绝。可以在「页面审批」里先登记。</small></label>
          <div className="knowledge-actions">
            <Button disabled={busy || !publishedUrl.trim()} onClick={() => void completePublish()}>{selected.status === "unknown" ? "确认已发布" : "完成发布"}</Button>
            {["pending", "needs_review"].includes(selected.status) && <Button variant="secondary" disabled={busy} onClick={() => void markUncertain()}>不确定，稍后核实</Button>}
            {["pending", "needs_review"].includes(selected.status) && <Button variant="secondary" disabled={busy} onClick={() => void markNotPublished()}>没有发出去</Button>}
            {selected.status === "unknown" && <Button variant="secondary" disabled={busy} onClick={() => void confirmNotPublished()}>确认没有发出</Button>}
            {selected.status === "pending" && ["api", "authorized"].includes(selected.publish_mode ?? "") && <>
              <Button variant="secondary" disabled={busy} onClick={() => void handoffSelectedTask("qr_required")}>二维码阻断，转人工</Button>
              <Button variant="secondary" disabled={busy} onClick={() => void handoffSelectedTask("captcha_required")}>验证码阻断，转人工</Button>
            </>}
          </div>
        </div>}
        {canCancel && ["pending", "needs_review"].includes(selected.status) && <div className="publish-finish-card">
          <div className="publish-finish-head"><strong>{cancelConfirm ? "确认取消这条任务？" : "不准备发布了？"}</strong><span>{cancelConfirm ? "取消后任务不会继续，任务和操作记录仍保留。" : "取消只停止这条任务，不删除任务或已经保存的发布结果。"}</span></div>
          <div className="knowledge-actions">
            {cancelConfirm ? <>
              <Button variant="danger" disabled={busy} onClick={() => void cancelSelectedTask()}>{busy ? "取消中…" : "确认取消任务"}</Button>
              <Button variant="secondary" disabled={busy} onClick={() => setCancelConfirm(false)}>返回</Button>
            </> : <Button variant="secondary" disabled={busy} onClick={() => setCancelConfirm(true)}>取消任务</Button>}
          </div>
        </div>}
        {error && <p className="form-error" role="alert">{error}</p>}
        {versionLoading && <p className="knowledge-empty">正在读取正文…</p>}
        {!selectedVersion && !versionLoading && <p className="knowledge-footnote">暂时读不到正文。可以先到发布后台打开已审批的稿子继续操作。</p>}
        {selectedVersion && <div className="publish-body-card">
          <div className="publish-body-head"><div><strong>正文预览</strong><span>{selectedVersion.title}</span></div><button type="button" className="publish-body-toggle" onClick={() => setBodyExpanded((value) => !value)}>{bodyExpanded ? "收起" : "展开全文"}</button></div>
          <div className={`publish-body-preview${bodyExpanded ? " is-expanded" : ""}`}>{plainPublishText(selectedVersion.body)}</div>
        </div>}
        </div>
      </div>}
    </>}
    {currentTab === "receipts" && <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>发布结果</h3><p>共 {receiptTotal} 条；每一条对应一次真实发布，记录文章链接、核实时间和预算归属</p></div></div>
      {receiptError && <p className="form-error" role="alert">{receiptError}</p>}
      {receiptLoading ? <p className="knowledge-empty">正在读取发布结果…</p> : <>
      <div className="knowledge-list">{receipts.map((receipt) => <div className="knowledge-item" key={receipt.id}>
        <span>
          <strong>发布记录 #{formatSerialNo(receipt.serial_no)} · {receipt.channel_name || "渠道未匹配"}</strong>
          <small className="publish-receipt-url"><a href={receipt.published_url} target="_blank" rel="noreferrer">{receipt.published_url}</a></small>
          <small>接收时间：{formatOAuthTime(receipt.received_at)}{receipt.verified_at ? ` · 核实时间：${formatOAuthTime(receipt.verified_at)}` : ""}</small>
          {receipt.budget_title && <small className="publish-budget-hint">预算归属：{receipt.budget_title}</small>}
          {receipt.page_approval_id && <small className="publish-budget-hint">已关联页面审批：{receipt.page_approval_id.slice(0, 8)}</small>}
        </span>
        <span className="knowledge-actions"><Badge tone={receipt.budget_title ? "green" : "slate"}>{receipt.budget_title ? "已挂预算" : "未挂预算"}</Badge></span>
      </div>)}{!receipts.length && <div className="knowledge-empty guide-empty"><p>还没有发布结果。先去「发布任务」完成一条发布，回填文章链接后，这里就会出现记录。</p><Button variant="secondary" onClick={() => selectTab("tasks")}>去发布任务</Button></div>}</div>
      {receiptTotal > WORKBENCH_PAGE_SIZE && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={receiptPage <= 1} onClick={() => setReceiptPage(receiptPage - 1)}>上一页</Button><span>{receiptPage} / {Math.ceil(receiptTotal / WORKBENCH_PAGE_SIZE)}</span><Button variant="secondary" disabled={receiptPage * WORKBENCH_PAGE_SIZE >= receiptTotal} onClick={() => setReceiptPage(receiptPage + 1)}>下一页</Button></div>}
      </>}
    </Panel>}
    {currentTab === "approvals" && <PageApprovalsPanel mode={mode} projectId={projectId} canRead={canRead} canExecute={canExecute} canApprove={canApprove} channels={channels} onNotice={onNotice}/>}
    {currentTab === "accounts" && canViewAccounts && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>发布账号</h3><p>{canExecute ? "按平台登记一个用于发布的账号，发任务时直接选它；有任务的账号只能停用" : "可查看并删除没有发布任务的账号；有任务的账号只能停用，修改需运营编辑权限"}</p></div></div>
      {!!accounts.length && <div className="knowledge-list">{accounts.map((account) => <div className="knowledge-item" key={account.id}><span><strong>{account.account_name}</strong><small>{channels.find((row) => row.id === account.channel_id)?.name || "平台已删除"}{account.notes ? ` · ${account.notes}` : ""}</small>{account.oauth_connection_id && <small className="publish-budget-hint">授权：{account.oauth_provider_code || "OAuth"} · {account.oauth_external_account_name || "已绑定"}</small>}</span><div className="knowledge-actions"><Badge tone={account.is_active ? "green" : "slate"}>{account.is_active ? "启用" : "停用"}</Badge>{Number(account.task_count ?? 0) > 0 && <Badge tone="slate">任务 {account.task_count}</Badge>}{canExecute && <Button type="button" variant="secondary" disabled={busy} onClick={() => startEditAccount(account)}>修改</Button>}{canDeleteAccounts && Number(account.task_count ?? 0) === 0 && <Button type="button" variant="danger" disabled={busy} onClick={() => askDeleteAccount(account)}>删除</Button>}</div></div>)}</div>}
      {!accounts.length && <p className="knowledge-empty">{canExecute ? "还没有发布账号。先在下方选择一个平台，再填账号名称。" : "还没有发布账号。"}</p>}
      {!!editingAccountId && canExecute && <form onSubmit={saveAccount} className="account-rebind-form">
        <div className="panel-heading"><div><h4>修改账号</h4><p>只改账号信息，不会影响已经创建的发布任务</p></div></div>
        <label className="field"><span className="field-label">账号名称</span><input className="text-input" required value={editAccountName} onChange={(e) => setEditAccountName(e.target.value)}/></label>
        <label className="field"><span className="field-label">备注（可选）</span><input className="text-input" value={editAccountNotes} onChange={(e) => setEditAccountNotes(e.target.value)} placeholder="例如：新手机号 / 新运营人"/></label>
        <label className="field"><span className="field-label">平台授权（可选）</span><select className="text-input" value={editAccountOauthId} onChange={(e) => setEditAccountOauthId(e.target.value)}><option value="">不绑定平台授权</option>{connectionsForChannel(accounts.find((item) => item.id === editingAccountId)?.channel_id || "").map((item) => <option key={item.id} value={item.id}>{item.provider_name} · {item.external_account_name || item.external_account_id}</option>)}</select><span className="field-hint">绑定后令牌仍只存服务端；撤销授权会让该账号的自动发布转人工。</span></label>
        <div className="field"><span className="field-label">账号状态</span><label className="checkbox-row"><input type="checkbox" checked={editAccountActive} onChange={(e) => setEditAccountActive(e.target.checked)}/> 启用该账号</label></div>
        <div className="knowledge-actions"><Button type="submit" disabled={busy}>保存</Button><Button type="button" variant="secondary" disabled={busy} onClick={cancelEditAccount}>取消</Button></div>
      </form>}
      {!editingAccountId && canExecute && <form onSubmit={addAccount}>
        <label className="field"><span className="field-label">发布平台</span><select className="text-input" required value={accountChannelId} onChange={(e) => { setAccountChannelId(e.target.value); setAccountOauthId(""); }}><option value="">选择平台</option>{channels.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="field"><span className="field-label">账号名称</span><input className="text-input" required value={accountName} onChange={(e) => setAccountName(e.target.value)} placeholder="例如：广州基地公众号"/></label>
        <label className="field"><span className="field-label">平台授权（可选）</span><select className="text-input" value={accountOauthId} onChange={(e) => setAccountOauthId(e.target.value)} disabled={!accountChannelId}><option value="">不绑定平台授权</option>{connectionsForChannel(accountChannelId).map((item) => <option key={item.id} value={item.id}>{item.provider_name} · {item.external_account_name || item.external_account_id}</option>)}</select><span className="field-hint">先选发布平台，再绑定同平台或项目级授权；令牌不会进入浏览器。</span></label>
        <Button type="submit" disabled={busy}>添加账号</Button>
      </form>}
    </Panel>}
    {currentTab === "create" && canExecute && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>新建发布</h3><p>选一篇已审批的稿子和发布账号，加入发布清单</p></div></div><form onSubmit={addTask}>
      <label className="field"><span className="field-label">要发布的稿子</span><select className="text-input" required value={versionId} onChange={(e) => setVersionId(e.target.value)}><option value="">选择已审批内容</option>{versions.map((item) => <option key={item.version_id} value={item.version_id}>{item.title} · 第 {item.version_no} 版</option>)}</select></label>
      <label className="field"><span className="field-label">用哪个账号发布</span><select className="text-input" required value={accountId} onChange={(e) => setAccountId(e.target.value)}><option value="">选择发布账号</option>{accounts.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{operatorAccountName(item.account_name)} · {channels.find((row) => row.id === item.channel_id)?.name || "平台"}</option>)}</select></label>
      <div className="knowledge-actions"><Button type="submit" disabled={busy}>加入发布清单</Button></div>
    </form></Panel>}
    {deleteAccountTarget && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !deleteAccountBusy) closeDeleteAccount(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="publish-account-delete-title">
        <div className="modal-header"><div><p className="eyebrow">DELETE</p><h2 id="publish-account-delete-title">删除发布账号</h2></div><button className="icon-button" aria-label="关闭" disabled={deleteAccountBusy} onClick={closeDeleteAccount}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">确定删除发布账号「<strong>{deleteAccountTarget.account_name}</strong>」吗？此操作不可恢复。</p>
        <p className="field-hint">只允许删除没有任何发布任务引用的账号。只要该账号参与过发布任务，系统会阻止删除；请改用「停用」，保留历史任务和发布结果。</p>
        {deleteAccountError && <p className="form-error" role="alert">{deleteAccountError}</p>}
        <div className="modal-actions">
          <Button variant="secondary" disabled={deleteAccountBusy} onClick={closeDeleteAccount}>取消</Button>
          <Button variant="danger" disabled={deleteAccountBusy} onClick={() => void confirmDeleteAccount()}>{deleteAccountBusy ? "删除中…" : "确认删除"}</Button>
        </div>
      </div>
    </div>}
  </div>;
}
