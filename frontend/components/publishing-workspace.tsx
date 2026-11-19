"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, DetailModal, Panel } from "./ui";
import { WorkTabs } from "./work-tabs";
import { workbenchClient } from "@/lib/workbench/client";
import type { ChannelRecord, ContentVersionDetail, ContentVersionRecord, PublishAccountRecord, PublishTaskRecord } from "@/lib/workbench/types";

type PublishTab = "tasks" | "accounts" | "create";

function readTab(value: string | null): PublishTab {
  return value === "accounts" || value === "create" ? value : "tasks";
}

export function PublishingWorkspace({ mode, projectId, canRead, canExecute, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canExecute: boolean; onNotice: (message: string) => void;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = readTab(searchParams.get("publish_tab"));
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
    ...(canExecute ? [{ id: "accounts" as PublishTab, label: "登记账号", count: accounts.length }, { id: "create" as PublishTab, label: "新建任务" }] : []),
  ];
  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    {!canExecute && <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号可以查看发布任务，但没有执行权限。登记发布账号、创建任务需要运营编辑（publish.execute）；项目管理员负责内容审批。</p></Panel>}
    <WorkTabs items={tabs} active={canExecute ? activeTab : "tasks"} onChange={selectTab} ariaLabel="内容发布视图"/>
    {(activeTab === "tasks" || !canExecute) && <>
      <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>发布任务</h3><p>共 {total} 条；回执不明时先核实，再决定是否重试</p></div></div>
        <div className="knowledge-list">{tasks.map((task) => <button className="knowledge-item" type="button" key={task.id} onClick={() => { setSelected(task); setSelectedVersion(null); setVersionLoading(true); setPublishedUrl(""); }}><span><strong>{task.id.slice(0, 8)}</strong><small>内容版本 {task.version_id.slice(0, 8)} · 渠道 {channels.find((row) => row.id === task.channel_id)?.name || task.channel_id.slice(0, 8)} · trace {task.trace_id ? `${task.trace_id.slice(0, 12)}…` : "未继承"}</small></span><Badge tone={task.status === "published" ? "green" : task.status === "unknown" ? "amber" : task.status === "failed" ? "red" : "blue"}>{task.status}</Badge></button>)}{!tasks.length && <p className="knowledge-empty">暂无发布任务</p>}</div>
        {total > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><span>{page} / {Math.ceil(total / 20)}</span><Button variant="secondary" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>下一页</Button></div>}
      </Panel>
      {selected && <DetailModal eyebrow="PUBLISH TASK" title={`任务 ${selected.id.slice(0, 8)}`} subtitle={`状态 ${selected.status} · 手动发布台账，不调用平台 API`} onClose={() => setSelected(null)}>
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
      </DetailModal>}
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
