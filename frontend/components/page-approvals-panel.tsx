"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { DataPager } from "./data-pager";
import { DataTable } from "./data-table";
import { workbenchClient, WORKBENCH_PAGE_SIZE } from "@/lib/workbench/client";
import type { ChannelRecord, PageApprovalRecord, PageApprovalStatus, PagePermission } from "@/lib/workbench/types";

const STATUS_LABELS: Record<PageApprovalStatus, string> = {
  pending: "待审批",
  approved: "已通过",
  rejected: "已驳回",
  revoked: "已撤销",
};

const STATUS_TONES: Record<PageApprovalStatus, "amber" | "green" | "red" | "slate"> = {
  pending: "amber",
  approved: "green",
  rejected: "red",
  revoked: "slate",
};

const PAGE_TYPE_LABELS: Record<string, string> = {
  homepage: "首页",
  course_or_product: "课程/产品页",
  article: "文章页",
  listicle: "榜单页",
  how_to: "教程页",
  comparison: "对比页",
  review: "测评页",
  forum_or_qa: "论坛/问答页",
  video: "视频页",
  case_study: "案例页",
  faq: "FAQ 页",
  search_surface: "搜索页",
  admissions: "招生页",
  recruitment: "招聘页",
  other: "其他页",
};

const PERMISSION_LABELS: Record<PagePermission, string> = {
  official: "官方页面（可发布）",
  authorized: "授权页面（可发布）",
  third_party: "第三方页面（仅引用）",
};

const PERMISSION_HINTS: Record<PagePermission, string> = {
  official: "品牌/院校官方页面，审批通过后可以作为官方发布页。",
  authorized: "合作方或代运营的授权页面，审批通过后可以发布。",
  third_party: "媒体、百科、转载等第三方页面，只能作为引用来源，不能作为官方发布页。",
};

const PAGE_TYPE_OPTIONS = ["admissions", "recruitment", "article", "course_or_product", "faq", "homepage", "other"];
const PERMISSION_OPTIONS: PagePermission[] = ["official", "authorized", "third_party"];

type Draft = {
  channel_id: string;
  page_url: string;
  title: string;
  page_type: string;
  permission: PagePermission;
};

function blankDraft(): Draft {
  return { channel_id: "", page_url: "", title: "", page_type: "article", permission: "official" };
}

function formatTime(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

export function PageApprovalsPanel({ mode, projectId, canRead, canExecute, canApprove, channels, onNotice }: {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
  canExecute: boolean;
  canApprove: boolean;
  channels: ChannelRecord[];
  onNotice: (message: string) => void;
}) {
  const [records, setRecords] = useState<PageApprovalRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [pageTypeFilter, setPageTypeFilter] = useState("");
  const [channelFilter, setChannelFilter] = useState("");
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [draftError, setDraftError] = useState("");
  const [saving, setSaving] = useState(false);
  const [approveTarget, setApproveTarget] = useState<PageApprovalRecord | null>(null);
  const [rejectTarget, setRejectTarget] = useState<PageApprovalRecord | null>(null);
  const [rejectNote, setRejectNote] = useState("");
  const [revokeTarget, setRevokeTarget] = useState<PageApprovalRecord | null>(null);
  const [revokeNote, setRevokeNote] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [reviewError, setReviewError] = useState("");

  const load = useCallback(async () => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    setLoading(true);
    try {
      const result = await workbenchClient.pageApprovals(projectId, {
        status: statusFilter || undefined,
        page_type: pageTypeFilter || undefined,
        channel_id: channelFilter || undefined,
        q: appliedSearch || undefined,
        page,
        pageSize: WORKBENCH_PAGE_SIZE,
      });
      setRecords(result.data);
      setTotal(result.meta?.total ?? result.data.length);
      setError("");
    } catch (cause) {
      setRecords([]);
      setTotal(0);
      setError(cause instanceof Error ? cause.message : "页面审批加载失败");
    } finally {
      setLoading(false);
    }
  }, [mode, canRead, projectId, statusFilter, pageTypeFilter, channelFilter, appliedSearch, page]);

  useEffect(() => {
    const pending = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(pending);
  }, [load, version]);

  const approvedChannels = channels.filter((channel) => channel.is_active !== false && channel.approval_status === "approved");

  function changeFilter(setter: (value: string) => void, value: string) {
    setter(value);
    setPage(1);
  }

  function openCreate() {
    setDraft(blankDraft());
    setDraftError("");
  }

  async function createApproval(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || saving) return;
    if (!draft.channel_id || !draft.page_url.trim()) {
      setDraftError("请选择发布渠道并填写页面地址");
      return;
    }
    setSaving(true);
    setDraftError("");
    try {
      await workbenchClient.createPageApproval(projectId, {
        channel_id: draft.channel_id,
        page_url: draft.page_url.trim(),
        title: draft.title.trim() || null,
        page_type: draft.page_type,
        permission: draft.permission,
      });
      setDraft(null);
      setPage(1);
      setStatusFilter("pending");
      setVersion((value) => value + 1);
      onNotice("页面审批已登记，等待审批");
    } catch (cause) {
      setDraftError(cause instanceof Error ? cause.message : "页面审批登记失败");
    } finally {
      setSaving(false);
    }
  }

  function updateRecord(updated: PageApprovalRecord) {
    setRecords((rows) => rows.map((row) => row.id === updated.id ? updated : row));
  }

  async function confirmApprove() {
    if (!approveTarget || !canApprove || reviewing) return;
    setReviewing(true);
    setReviewError("");
    try {
      const updated = await workbenchClient.reviewPageApproval(projectId, approveTarget.id, { decision: "approved" });
      updateRecord(updated);
      setApproveTarget(null);
      setVersion((value) => value + 1);
      onNotice("页面审批已通过，可以用于保存发布结果");
    } catch (cause) {
      setReviewError(cause instanceof Error ? cause.message : "页面审批失败");
    } finally {
      setReviewing(false);
    }
  }

  async function confirmReject() {
    if (!rejectTarget || !canApprove || reviewing) return;
    const note = rejectNote.trim();
    if (!note) { setReviewError("驳回必须填写意见"); return; }
    setReviewing(true);
    setReviewError("");
    try {
      const updated = await workbenchClient.reviewPageApproval(projectId, rejectTarget.id, { decision: "rejected", note });
      updateRecord(updated);
      setRejectTarget(null);
      setRejectNote("");
      setVersion((value) => value + 1);
      onNotice("页面审批已驳回");
    } catch (cause) {
      setReviewError(cause instanceof Error ? cause.message : "驳回失败");
    } finally {
      setReviewing(false);
    }
  }

  async function confirmRevoke() {
    if (!revokeTarget || !canApprove || reviewing) return;
    const note = revokeNote.trim();
    if (!note) { setReviewError("撤销必须填写原因"); return; }
    setReviewing(true);
    setReviewError("");
    try {
      const updated = await workbenchClient.revokePageApproval(projectId, revokeTarget.id, note);
      updateRecord(updated);
      setRevokeTarget(null);
      setRevokeNote("");
      setVersion((value) => value + 1);
      onNotice("页面审批已撤销，这个页面不能再用于新的发布结果");
    } catch (cause) {
      setReviewError(cause instanceof Error ? cause.message : "撤销失败");
    } finally {
      setReviewing(false);
    }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">页面审批仅在真实接口模式显示。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有发布查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  return <div className="knowledge-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading">
        <div><h3>页面发布审批</h3><p>院校类渠道、招生页和招聘页，发布后要回填链接前，先在这里登记并通过审批；其他页面可按需登记。</p></div>
        {canExecute && <Button icon="plus" onClick={openCreate}>新增页面审批</Button>}
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="page-approval-filters">
        <label className="field"><span className="field-label">审批状态</span><select className="text-input" value={statusFilter} onChange={(event) => changeFilter(setStatusFilter, event.target.value)}><option value="">全部状态</option>{Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="field"><span className="field-label">页面类型</span><select className="text-input" value={pageTypeFilter} onChange={(event) => changeFilter(setPageTypeFilter, event.target.value)}><option value="">全部页面类型</option>{Object.entries(PAGE_TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="field"><span className="field-label">发布渠道</span><select className="text-input" value={channelFilter} onChange={(event) => changeFilter(setChannelFilter, event.target.value)}><option value="">全部渠道</option>{channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.name}</option>)}</select></label>
        <form className="field" onSubmit={(event) => { event.preventDefault(); setAppliedSearch(search); setPage(1); }}><span className="field-label">搜索页面</span><div className="channel-search-row"><input className="text-input" value={search} maxLength={255} placeholder="输入页面地址或标题" onChange={(event) => setSearch(event.target.value)}/><Button type="submit" variant="secondary" disabled={loading}>查询</Button></div></form>
        <p className="knowledge-footnote">共 {total} 条 · 第三方页面只能作为引用来源，不能作为官方发布页</p>
      </div>
      <DataTable columns={[
        { key: "title", label: "页面", width: "26%", className: "col-title", render: (record) => <><strong title={record.title || record.page_url}>{record.title || record.page_url}</strong><small title={record.page_url}>{record.page_url}</small></> },
        { key: "channel", label: "渠道", width: "14%", render: (record) => record.channel_name || "渠道已删除" },
        { key: "type", label: "类型 / 用途", width: "16%", render: (record) => <>{PAGE_TYPE_LABELS[record.page_type] ?? record.page_type}<small className="data-cell-note">{PERMISSION_LABELS[record.permission] ?? record.permission}</small></> },
        { key: "applicant", label: "申请 / 审批", width: "16%", render: (record) => <>{record.requested_by_name || "未知申请人"}<small className="data-cell-note">{record.reviewed_by_name ? `${record.reviewed_by_name} 审批` : formatTime(record.created_at)}</small></> },
        { key: "status", label: "状态", width: "10%", className: "col-status", render: (record) => <Badge tone={STATUS_TONES[record.status]}>{STATUS_LABELS[record.status]}</Badge> },
        { key: "actions", label: "操作", width: "18%", className: "data-cell-actions", render: (record) => <>
          {canApprove && record.status === "pending" && <><Button onClick={() => { setReviewError(""); setApproveTarget(record); }}>通过</Button><Button variant="secondary" onClick={() => { setReviewError(""); setRejectNote(""); setRejectTarget(record); }}>驳回</Button></>}
          {canApprove && record.status === "approved" && <Button variant="secondary" onClick={() => { setReviewError(""); setRevokeNote(""); setRevokeTarget(record); }}>撤销</Button>}
        </> },
      ]} rows={records} rowKey={(record) => record.id} startIndex={(page - 1) * WORKBENCH_PAGE_SIZE} empty={loading ? <p className="knowledge-empty">正在加载页面审批…</p> : !records.length && !error ? <div className="knowledge-empty guide-empty"><p>{total || appliedSearch || pageTypeFilter || channelFilter ? "当前筛选下没有页面审批记录。可以清空筛选后再看，或点右上角「新增页面审批」。" : "还没有页面审批记录。院校、招生、招聘页面需要发布时，点右上角「新增页面审批」，填写页面地址和类型后提交。"}</p>{!total && !appliedSearch && !pageTypeFilter && !channelFilter && canExecute && <Button variant="secondary" onClick={openCreate}>新增页面审批</Button>}</div> : null}/>
      <DataPager page={page} total={total} pageSize={WORKBENCH_PAGE_SIZE} loading={loading} onPage={setPage}/>
    </Panel>

    {draft && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) setDraft(null); }}>
      <div className="modal modal-scroll" role="dialog" aria-modal="true" aria-labelledby="page-approval-new-title">
        <div className="modal-header"><div><p className="eyebrow">页面审批</p><h2 id="page-approval-new-title">新增页面审批</h2></div><button className="icon-button" aria-label="关闭" disabled={saving} onClick={() => setDraft(null)}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">填写这个页面准备发布到哪个渠道、页面地址和用途。审批通过后，这条页面才能用于保存发布结果。</p>
        {draftError && <p className="form-error" role="alert">{draftError}</p>}
        <form onSubmit={createApproval}>
          <label className="field"><span className="field-label">发布渠道 *</span><select className="text-input" required value={draft.channel_id} disabled={saving} onChange={(event) => setDraft({ ...draft, channel_id: event.target.value })}><option value="">请选择要发布的渠道</option>{approvedChannels.map((channel) => <option key={channel.id} value={channel.id}>{channel.name}</option>)}</select><small>只列出已批准并启用的渠道。当前阶段不校验页面域名归属。</small></label>
          <label className="field"><span className="field-label">页面地址 *</span><input className="text-input" required maxLength={2048} placeholder="https://example.com/admissions" value={draft.page_url} disabled={saving} onChange={(event) => setDraft({ ...draft, page_url: event.target.value })}/><small>粘贴发布后要使用的完整链接，必须以 http:// 或 https:// 开头。</small></label>
          <label className="field"><span className="field-label">页面标题</span><input className="text-input" maxLength={255} value={draft.title} disabled={saving} onChange={(event) => setDraft({ ...draft, title: event.target.value })}/><small>方便审批人识别。标题里有“招生”“招聘”时，系统会辅助判断页面类型。</small></label>
          <label className="field"><span className="field-label">页面类型 *</span><select className="text-input" value={draft.page_type} disabled={saving} onChange={(event) => setDraft({ ...draft, page_type: event.target.value })}>{PAGE_TYPE_OPTIONS.map((value) => <option key={value} value={value}>{PAGE_TYPE_LABELS[value] ?? value}</option>)}</select><small>不确定就选“文章页”；招生、招聘请选对应类型，类型要和页面内容一致。</small></label>
          <label className="field"><span className="field-label">页面归属 *</span><select className="text-input" value={draft.permission} disabled={saving} onChange={(event) => setDraft({ ...draft, permission: event.target.value as PagePermission })}>{PERMISSION_OPTIONS.map((value) => <option key={value} value={value}>{PERMISSION_LABELS[value]}</option>)}</select><small>{PERMISSION_HINTS[draft.permission]}</small></label>
          <div className="modal-actions"><Button type="submit" disabled={saving}>{saving ? "提交中…" : "提交审批"}</Button><Button variant="secondary" disabled={saving} onClick={() => setDraft(null)}>取消</Button></div>
        </form>
      </div>
    </div>}

    {approveTarget && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !reviewing) setApproveTarget(null); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="page-approval-approve-title">
        <div className="modal-header"><div><p className="eyebrow">页面审批</p><h2 id="page-approval-approve-title">通过页面审批</h2></div><button className="icon-button" aria-label="关闭" disabled={reviewing} onClick={() => setApproveTarget(null)}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">{approveTarget.title || approveTarget.page_url}</p>
        {reviewError && <p className="form-error" role="alert">{reviewError}</p>}
        <p className="knowledge-footnote">通过后，同一渠道、同一页面地址、同一页面类型的发布结果才能保存。第三方页面即使通过，也不能作为官方发布页。</p>
        <div className="modal-actions"><Button disabled={reviewing} onClick={() => void confirmApprove()}>{reviewing ? "处理中…" : "确认通过"}</Button><Button variant="secondary" disabled={reviewing} onClick={() => setApproveTarget(null)}>取消</Button></div>
      </div>
    </div>}

    {rejectTarget && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !reviewing) setRejectTarget(null); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="page-approval-reject-title">
        <div className="modal-header"><div><p className="eyebrow">页面审批</p><h2 id="page-approval-reject-title">驳回页面审批</h2></div><button className="icon-button" aria-label="关闭" disabled={reviewing} onClick={() => setRejectTarget(null)}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">{rejectTarget.title || rejectTarget.page_url}</p>
        {reviewError && <p className="form-error" role="alert">{reviewError}</p>}
        <label className="field"><span className="field-label">驳回意见 *</span><textarea className="text-input knowledge-textarea short" required maxLength={1000} value={rejectNote} disabled={reviewing} onChange={(event) => setRejectNote(event.target.value)}/></label>
        <div className="modal-actions"><Button disabled={reviewing} onClick={() => void confirmReject()}>{reviewing ? "处理中…" : "确认驳回"}</Button><Button variant="secondary" disabled={reviewing} onClick={() => setRejectTarget(null)}>取消</Button></div>
      </div>
    </div>}

    {revokeTarget && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !reviewing) setRevokeTarget(null); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="page-approval-revoke-title">
        <div className="modal-header"><div><p className="eyebrow">页面审批</p><h2 id="page-approval-revoke-title">撤销页面审批</h2></div><button className="icon-button" aria-label="关闭" disabled={reviewing} onClick={() => setRevokeTarget(null)}><Icon name="close" size={19}/></button></div>
        <p className="modal-description">{revokeTarget.title || revokeTarget.page_url}</p>
        {reviewError && <p className="form-error" role="alert">{reviewError}</p>}
        <p className="knowledge-footnote">撤销后，这个页面不能再用于新的发布结果；已经保存的历史发布记录不受影响。</p>
        <label className="field"><span className="field-label">撤销原因 *</span><textarea className="text-input knowledge-textarea short" required maxLength={1000} value={revokeNote} disabled={reviewing} onChange={(event) => setRevokeNote(event.target.value)}/></label>
        <div className="modal-actions"><Button variant="danger" disabled={reviewing} onClick={() => void confirmRevoke()}>{reviewing ? "处理中…" : "确认撤销"}</Button><Button variant="secondary" disabled={reviewing} onClick={() => setRevokeTarget(null)}>取消</Button></div>
      </div>
    </div>}
  </div>;
}
