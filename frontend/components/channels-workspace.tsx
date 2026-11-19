"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import { formatDateTime } from "@/lib/workbench/format";
import type { ChannelAnomalyList, ChannelDetailRecord, ChannelRecord } from "@/lib/workbench/types";

const categories = [
  ["own_site", "自有站点"], ["content_platform", "内容平台"], ["video", "视频平台"],
  ["community", "社区"], ["encyclopedia", "百科"], ["local_media", "地方媒体"],
  ["industry_media", "行业媒体"], ["institution", "机构"],
] as const;
const statuses = [["candidate", "候选"], ["published", "已发布"], ["observed", "已观测"], ["review_pending", "待归类"]] as const;
const approvalStatuses = [["pending_review", "待审核"], ["approved", "已准入"], ["rejected", "已驳回"]] as const;
const approvalTones: Record<string, "green" | "amber" | "red" | "slate"> = { approved: "green", pending_review: "amber", rejected: "red" };
const label = (pairs: readonly (readonly [string, string])[], value: string) => pairs.find(([code]) => code === value)?.[1] ?? value;
const approvalLabel = (value: string) => label(approvalStatuses, value);
const approvalTone = (value: string) => approvalTones[value] ?? "slate";

interface Draft { code: string; name: string; category: string; status: string; primary_domain: string; publish_url: string; login_url: string; notes: string; aliases: string; is_active: boolean }
const blank = (): Draft => ({ code: "", name: "", category: "content_platform", status: "candidate", primary_domain: "", publish_url: "", login_url: "", notes: "", aliases: "", is_active: true });

export function ChannelsWorkspace({ mode, projectId, canRead, canWrite, canApprove, canExport, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean; canApprove: boolean; canExport: boolean; onNotice: (message: string) => void;
}) {
  const [items, setItems] = useState<ChannelRecord[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [citedChannels, setCitedChannels] = useState<number | null>(null);
  const [anomalies, setAnomalies] = useState<ChannelAnomalyList | null>(null);
  const [loadedKey, setLoadedKey] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ChannelDetailRecord | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [existingAliases, setExistingAliases] = useState<ChannelRecord["aliases"]>([]);
  const [reviewing, setReviewing] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectNote, setRejectNote] = useState("");

  const key = `${projectId}:${page}`;
  const loading = loadedKey !== key || detailLoading;
  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.channels(projectId, page).then((result) => {
      if (active) { setItems(result.data); setTotal(result.meta?.total ?? result.data.length); setError(""); setLoadedKey(key); }
    }).catch((cause) => { if (active) { setItems([]); setError(cause instanceof Error ? cause.message : "渠道加载失败"); setLoadedKey(key); } });
    return () => { active = false; };
  }, [mode, canRead, projectId, page, key]);
  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.statsOverview(projectId).then((result) => {
      if (active) setCitedChannels(result.channel_count);
    }).catch(() => {
      if (active) setCitedChannels(null);
    });
    return () => { active = false; };
  }, [mode, canRead, projectId]);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.channelAnomalies(projectId).then((result) => {
      if (active) setAnomalies(result);
    }).catch(() => {
      if (active) setAnomalies(null);
    });
    return () => { active = false; };
  }, [mode, canRead, projectId]);

  async function openDetail(id: string) {
    setDetailLoading(true);
    try {
      const item = await workbenchClient.channel(projectId, id);
      setDetail(item);
      setDraft(null);
      setEditingId(null);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "读取渠道详情失败"); }
    finally { setDetailLoading(false); }
  }

  function startEdit(item: ChannelDetailRecord) {
    if (!canWrite) return;
      if (item.is_active === undefined || item.aliases === undefined || item.notes === undefined) {
        onNotice("当前后端尚未返回备注、启停和别名，不能安全编辑；请更新后端到前端联调分支");
        return;
      }
      setEditingId(item.id);
      setExistingAliases(item.aliases);
      setDraft({ code: item.code, name: item.name, category: item.category, status: item.status,
        primary_domain: item.primary_domain ?? "", publish_url: item.publish_url ?? "", login_url: item.login_url ?? "", notes: item.notes ?? "", aliases: "", is_active: item.is_active });
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || !canWrite) return;
    setSaving(true);
    const aliases = [...new Set(draft.aliases.split(/[\n,，]+/).map((value) => value.trim().toLowerCase()).filter(Boolean))];
    const input: Record<string, unknown> = {
      name: draft.name.trim(), category: draft.category, status: draft.status,
      primary_domain: draft.primary_domain.trim() || null,
      publish_url: draft.publish_url.trim() || null,
      login_url: draft.login_url.trim() || null,
      notes: draft.notes.trim() || null, is_active: draft.is_active,
    };
    if (!editingId) input.code = draft.code.trim();
    if (aliases.length) input.aliases = aliases;
    try {
      await workbenchClient.saveChannel(projectId, input, editingId ?? undefined);
      const result = await workbenchClient.channels(projectId, page);
      setItems(result.data);
      setTotal(result.meta?.total ?? result.data.length);
      setDraft(null);
      setEditingId(null);
      setDetail(null);
      onNotice("渠道已保存；旧名称和旧域名由后端保留为别名");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "保存渠道失败"); }
    finally { setSaving(false); }
  }

  async function exportCsv() {
    if (!canExport || projectId === "all" || exporting) return;
    setExporting(true);
    try {
      await workbenchClient.downloadChannels(projectId);
      onNotice("渠道台账 CSV 已下载");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "渠道导出失败"); }
    finally { setExporting(false); }
  }

  async function reloadList() {
    const result = await workbenchClient.channels(projectId, page);
    setItems(result.data);
    setTotal(result.meta?.total ?? result.data.length);
  }

  async function approveChannel() {
    if (!detail || !canApprove || reviewing) return;
    setReviewing(true);
    try {
      await workbenchClient.reviewChannel(projectId, detail.id, "approved");
      onNotice("渠道已通过准入");
      await reloadList();
      await openDetail(detail.id);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "审批失败"); }
    finally { setReviewing(false); }
  }

  async function rejectChannel() {
    if (!detail || !canApprove || reviewing) return;
    const note = rejectNote.trim();
    if (!note) { onNotice("请填写驳回原因"); return; }
    setReviewing(true);
    try {
      await workbenchClient.reviewChannel(projectId, detail.id, "rejected", note);
      onNotice("渠道已驳回");
      setRejectOpen(false);
      setRejectNote("");
      await reloadList();
      await openDetail(detail.id);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "审批失败"); }
    finally { setReviewing(false); }
  }

  async function resubmitChannel() {
    if (!detail || !canWrite || reviewing) return;
    setReviewing(true);
    try {
      await workbenchClient.resubmitChannel(projectId, detail.id);
      onNotice("已重新提交，等待准入审批");
      await reloadList();
      await openDetail(detail.id);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "重新提交失败"); }
    finally { setReviewing(false); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">渠道台账仅在真实接口模式显示。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有渠道查看权限。</p></Panel>;
  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading"><div><h3>渠道台账</h3><p>目录规模 {total} 条 · 实测被引用渠道 {citedChannels ?? "—"}</p></div><div className="knowledge-actions">{canExport && <Button variant="secondary" icon="download" disabled={exporting} onClick={() => void exportCsv()}>{exporting ? "导出中…" : "导出 CSV"}</Button>}{canWrite && <Button icon="plus" onClick={() => { setDetail(null); setEditingId(null); setExistingAliases([]); setDraft(blank()); }}>新增渠道</Button>}</div></div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {anomalies && anomalies.counts.total > 0 && <div className="load-error" role="alert" style={{ alignItems: "flex-start" }}>
        <div style={{ display: "grid", gap: "6px" }}>
          <strong>渠道/发布一致性异常 {anomalies.counts.total} 条（高 {anomalies.counts.high} · 警告 {anomalies.counts.warning}）</strong>
          <div style={{ display: "grid", gap: "5px", maxHeight: "160px", overflowY: "auto" }}>
            {anomalies.anomalies.map((row) => <span key={`${row.code}:${row.channel_id}:${row.task_id ?? ""}:${row.receipt_id ?? ""}`}>
              {row.severity === "high" ? "【高】" : "【警告】"}{row.channel_name}：{row.message} 建议：{row.recommended_action}
            </span>)}
          </div>
        </div>
      </div>}
      <div className="knowledge-list" key={page}>{items.map((item) => <button className="knowledge-item" type="button" key={item.id} onClick={() => void openDetail(item.id)}><span><strong>{item.name}</strong><small>{item.code} · {item.primary_domain || "无主域名"}</small></span><span>{label(categories, item.category)} · {label(statuses, item.status)} · <Badge tone={approvalTone(item.approval_status)}>{approvalLabel(item.approval_status)}</Badge></span><Badge tone={item.status === "review_pending" ? "amber" : "blue"}>查看</Badge></button>)}{!loading && !items.length && !error && <p className="knowledge-empty">当前项目暂无渠道</p>}{loading && <p className="knowledge-empty">正在加载渠道…</p>}</div>
      {total > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><span>{page} / {Math.ceil(total / 20)}</span><Button variant="secondary" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>下一页</Button></div>}
    </Panel>
    {detail && !draft && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setDetail(null); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="channel-detail-title" style={{ maxHeight: "88vh", overflowY: "auto" }}>
        <div className="modal-header"><div><p className="eyebrow">CHANNEL DETAIL</p><h2 id="channel-detail-title">{detail.name}</h2></div><button className="icon-button" aria-label="关闭" onClick={() => setDetail(null)}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">{detail.code} · {label(categories, detail.category)} · {label(statuses, detail.status)}</p>
        <p className="knowledge-footnote">主域名：{detail.primary_domain || "未设置"} · {detail.is_active ? "已启用" : "已停用"}</p>
        <p className="knowledge-footnote">发布后台：{detail.publish_url || "未配置"} · 登录页：{detail.login_url || "未配置"}</p>
        <p className="knowledge-footnote">备注：{detail.notes || "无"}</p>
        <p className="knowledge-footnote">别名：{detail.aliases.length ? detail.aliases.map((alias) => alias.alias_name ? `${alias.domain}（${alias.alias_name}）` : alias.domain).join("、") : "无"}</p>
        <p className="knowledge-footnote">引用 {detail.citation_count} 条 · 样本 {detail.sample_count} 个 · 被引页面 {detail.page_count} 个</p>
        <p className="knowledge-footnote">引擎：{detail.engine_codes.join("、") || "无"} · 题目：{detail.question_codes.join("、") || "无"}</p>
        <p className="knowledge-footnote">首次采样：{detail.first_sampled_at || "无"} · 最近采样：{detail.last_sampled_at || "无"}</p>
        <div>
          <strong>准入：<Badge tone={approvalTone(detail.approval_status)}>{approvalLabel(detail.approval_status)}</Badge></strong>
          {detail.decision_comment && <p className="knowledge-footnote">审批意见：{detail.decision_comment}</p>}
          {!!detail.approvals.length && <div><strong>审批记录</strong>{detail.approvals.map((row) => (
            <p className="knowledge-footnote" key={row.id}>
              {row.submitted_by_name || "未知提交人"} 提交于 {formatDateTime(row.submitted_at)}
              {row.decision ? ` · ${row.reviewed_by_name || "未知审批人"} ${row.decision === "approved" ? "通过" : "驳回"}于 ${formatDateTime(row.reviewed_at)}` : " · 待审批"}
              {row.comment ? ` · 意见：${row.comment}` : ""}
            </p>
          ))}</div>}
        </div>
        {!!detail.page_urls.length && <div><strong>相关页面</strong>{detail.page_urls.map((url) => <p className="knowledge-footnote" key={url}>{url}</p>)}</div>}
        {!!detail.citations.length && <div><strong>最近引用</strong>{detail.citations.map((row) => <p className="knowledge-footnote" key={row.citation_id}>{row.engine_name} · {row.question_code} · {row.review_status} · {row.raw_url}</p>)}</div>}
        <div className="modal-actions">
          {canWrite && <Button onClick={() => startEdit(detail)}>编辑</Button>}
          {canApprove && detail.approval_status === "pending_review" && <>
            <Button disabled={reviewing} onClick={() => void approveChannel()}>{reviewing ? "处理中…" : "通过准入"}</Button>
            <Button variant="danger" disabled={reviewing} onClick={() => { setRejectOpen(true); setRejectNote(""); }}>驳回</Button>
          </>}
          {canWrite && detail.approval_status === "rejected" && <Button disabled={reviewing} onClick={() => void resubmitChannel()}>{reviewing ? "提交中…" : "重新提交"}</Button>}
          <Button variant="secondary" onClick={() => setDetail(null)}>关闭</Button>
        </div>
      </div>
    </div>}
    {rejectOpen && detail && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !reviewing) { setRejectOpen(false); setRejectNote(""); } }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="channel-reject-title">
        <div className="modal-header"><div><p className="eyebrow">REJECT</p><h2 id="channel-reject-title">驳回渠道准入</h2></div><button className="icon-button" aria-label="关闭" disabled={reviewing} onClick={() => { setRejectOpen(false); setRejectNote(""); }}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">驳回 <strong>{detail.name}</strong>，请填写驳回原因，会随审批意见一并展示。</p>
        <form onSubmit={(event) => { event.preventDefault(); void rejectChannel(); }}>
          <label className="field"><span className="field-label">驳回原因 *</span><textarea className="text-input knowledge-textarea short" value={rejectNote} required maxLength={2000} disabled={reviewing} onChange={(event) => setRejectNote(event.target.value)}/></label>
          <div className="modal-actions"><Button variant="secondary" disabled={reviewing} onClick={() => { setRejectOpen(false); setRejectNote(""); }}>取消</Button><Button type="submit" variant="danger" disabled={reviewing}>{reviewing ? "处理中…" : "确认驳回"}</Button></div>
        </form>
      </div>
    </div>}
    {draft && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) setDraft(null); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="channel-draft-title" style={{ maxHeight: "88vh", overflowY: "auto" }}>
        <div className="modal-header"><div><p className="eyebrow">CHANNEL</p><h2 id="channel-draft-title">{editingId ? "编辑渠道" : "新增渠道"}</h2></div><button className="icon-button" aria-label="关闭" disabled={saving} onClick={() => setDraft(null)}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">别名只能追加；旧名称和旧主域名由后端保存。</p>
        <form onSubmit={save}>
          <label className="field"><span className="field-label">代码</span><input className="text-input" value={draft.code} disabled={!!editingId || saving} required pattern="[a-z0-9][a-z0-9-]*" onChange={(event) => setDraft({ ...draft, code: event.target.value })}/></label>
          <label className="field"><span className="field-label">名称</span><input className="text-input" value={draft.name} disabled={saving} required maxLength={128} onChange={(event) => setDraft({ ...draft, name: event.target.value })}/></label>
          <label className="field"><span className="field-label">分类</span><select className="text-input" value={draft.category} disabled={saving} onChange={(event) => setDraft({ ...draft, category: event.target.value })}>{categories.map(([code, text]) => <option value={code} key={code}>{text}</option>)}</select></label>
          <label className="field"><span className="field-label">状态</span><select className="text-input" value={draft.status} disabled={saving} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>{statuses.map(([code, text]) => <option value={code} key={code}>{text}</option>)}</select></label>
          <label className="field"><span className="field-label">主域名</span><input className="text-input" value={draft.primary_domain} disabled={saving} placeholder="example.com" onChange={(event) => setDraft({ ...draft, primary_domain: event.target.value })}/></label>
          <label className="field"><span className="field-label">发布后台地址</span><input className="text-input" value={draft.publish_url} disabled={saving} placeholder="https://平台后台/发布页" onChange={(event) => setDraft({ ...draft, publish_url: event.target.value })}/></label>
          <label className="field"><span className="field-label">登录地址</span><input className="text-input" value={draft.login_url} disabled={saving} placeholder="https://平台登录页" onChange={(event) => setDraft({ ...draft, login_url: event.target.value })}/></label>
          <label className="field"><span className="field-label">备注</span><textarea className="text-input knowledge-textarea short" value={draft.notes} disabled={saving} maxLength={5000} onChange={(event) => setDraft({ ...draft, notes: event.target.value })}/></label>
          {!!existingAliases?.length && <p className="knowledge-footnote">已有别名：{existingAliases.map((item) => item.domain).join("、")}</p>}
          <label className="field"><span className="field-label">新增别名域名（逗号或换行分隔）</span><textarea className="text-input knowledge-textarea short" value={draft.aliases} disabled={saving} onChange={(event) => setDraft({ ...draft, aliases: event.target.value })}/></label>
          <label className="rounds-checkbox"><input type="checkbox" checked={draft.is_active} disabled={saving} onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })}/> 启用渠道</label>
          <div className="modal-actions"><Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存渠道"}</Button><Button variant="secondary" disabled={saving} onClick={() => setDraft(null)}>取消</Button></div>
        </form>
      </div>
    </div>}
  </div>;
}
