"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { ChannelRecord, ContentReviewRecord, ContentVersionDetail, ContentVersionRecord } from "@/lib/workbench/types";

export function ContentWorkspace({ mode, projectId, canRead, canWrite, canReview, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean; canReview: boolean;
  onNotice: (message: string) => void;
}) {
  const [status, setStatus] = useState("pending_review");
  const [items, setItems] = useState<ContentVersionRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<ContentVersionDetail | null>(null);
  const [history, setHistory] = useState<ContentReviewRecord[]>([]);
  const [channels, setChannels] = useState<ChannelRecord[]>([]);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("channel");
  const [channelId, setChannelId] = useState("");
  const [parentId, setParentId] = useState("");
  const [body, setBody] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [createdItemId, setCreatedItemId] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const result = await workbenchClient.contentVersions(projectId, status, page);
    setItems(result.data); setTotal(result.meta?.total ?? result.data.length);
  }, [projectId, status, page]);
  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([workbenchClient.contentVersions(projectId, status, page), canWrite ? workbenchClient.channels(projectId, 1, 100) : Promise.resolve(null)])
      .then(([result, channelList]) => { if (!active) return; setItems(result.data); setTotal(result.meta?.total ?? result.data.length); setChannels(channelList?.data ?? []); setError(""); })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "内容列表加载失败"); });
    return () => { active = false; };
  }, [mode, canRead, canWrite, projectId, status, page]);

  async function openVersion(id: string) {
    try {
      const [detail, reviews] = await Promise.all([workbenchClient.contentVersion(projectId, id), workbenchClient.contentReviews(projectId, id)]);
      setSelected(detail); setHistory(reviews.data); setComment(""); setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "内容详情加载失败"); }
  }

  async function createContent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!title.trim() || !body.trim()) return; setBusy(true);
    try {
      let itemId = createdItemId;
      if (!itemId) {
        const created = await workbenchClient.contentAction(projectId, "content-item", {
          title: title.trim(), kind, channel_id: kind === "channel" ? channelId || null : null,
          parent_id: parentId || null,
        });
        itemId = String(created.item_id);
        setCreatedItemId(itemId);
      }
      const version = await workbenchClient.contentAction(projectId, "content-version-create", { body: body.trim(), change_note: changeNote || null }, itemId);
      setCreatedItemId(""); setTitle(""); setBody(""); setChangeNote(""); setParentId("");
      setStatus("draft"); setPage(1); await workbenchClient.contentVersion(projectId, String(version.version_id));
      onNotice("草稿已保存，可在草稿列表提交审核");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "内容保存失败；可用当前表单重试"); }
    finally { setBusy(false); }
  }

  async function submit() {
    if (!selected) return; setBusy(true);
    try {
      await workbenchClient.contentAction(projectId, "content-submit", {}, selected.version_id);
      setSelected(null); await refresh(); onNotice("内容已提交审核");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "提交审核失败"); }
    finally { setBusy(false); }
  }

  async function review(decision: "approved" | "rejected") {
    if (!selected) return; setBusy(true);
    try {
      await workbenchClient.contentAction(projectId, "content-review", { decision, comment: comment || null }, selected.version_id);
      setSelected(null); await refresh(); onNotice(decision === "approved" ? "版本已审批通过" : "版本已驳回");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "审批失败"); }
    finally { setBusy(false); }
  }

  if (mode === "mock") return null;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有内容查看权限。</p></Panel>;
  return <div className="knowledge-workspace">
    {error && <p className="form-error" role="alert">{error}</p>}
    <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>内容版本</h3><p>查看正文和审批记录后再决定</p></div><select className="text-input" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); setSelected(null); }}><option value="pending_review">待审核</option><option value="draft">草稿</option><option value="approved">已通过</option><option value="rejected">已驳回</option></select></div>
      <div className="knowledge-list">{items.map((item) => <button className="knowledge-item" type="button" key={item.version_id} onClick={() => void openVersion(item.version_id)}><span><strong>{item.title} · v{item.version_no}</strong><small>{item.author_name || "未知作者"} · {item.submitted_at || "尚未提交"}</small></span><Badge tone={item.status === "approved" ? "green" : item.status === "rejected" ? "red" : "amber"}>{item.status}</Badge></button>)}{!items.length && <p className="knowledge-empty">当前状态暂无版本</p>}</div>
      {total > 20 && <div className="knowledge-panel-foot"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><span>{page} / {Math.ceil(total / 20)}</span><Button variant="secondary" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>下一页</Button></div>}
    </Panel>
    {selected && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>{selected.title} · v{selected.version_no}</h3><p>{selected.kind} · {selected.status} · hash {selected.content_hash.slice(0, 12)}…</p></div><Button variant="secondary" onClick={() => setSelected(null)}>关闭</Button></div>
      <p className="sample-answer">{selected.body}</p>
      <p className="knowledge-footnote">审批记录：{history.length ? history.map((row) => `${row.reviewer_name || "审核员"} ${row.decision}${row.comment ? `（${row.comment}）` : ""}`).join("；") : "暂无"}</p>
      {canWrite && ["draft", "rejected"].includes(selected.status) && <Button disabled={busy} onClick={() => void submit()}>提交审核</Button>}
      {canReview && selected.status === "pending_review" && <><label className="field"><span className="field-label">审批意见</span><textarea className="text-input knowledge-textarea short" value={comment} onChange={(e) => setComment(e.target.value)}/></label><div className="knowledge-actions"><Button disabled={busy} onClick={() => void review("approved")}>通过</Button><Button variant="secondary" disabled={busy} onClick={() => void review("rejected")}>驳回</Button></div></>}
    </Panel>}
    {canWrite && <Panel className="knowledge-editor-panel"><div className="panel-heading"><div><h3>新建内容草稿</h3><p>提交后正文锁定；修改需追加版本</p></div></div><form onSubmit={createContent}>
      <label className="field"><span className="field-label">标题</span><input className="text-input" required value={title} onChange={(e) => setTitle(e.target.value)}/></label>
      <label className="field"><span className="field-label">类型</span><select className="text-input" value={kind} onChange={(e) => setKind(e.target.value)}><option value="channel">渠道稿</option><option value="master">母稿</option></select></label>
      {kind === "channel" && <label className="field"><span className="field-label">渠道</span><select className="text-input" required value={channelId} onChange={(e) => setChannelId(e.target.value)}><option value="">选择渠道</option>{channels.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>}
      {kind === "channel" && <label className="field"><span className="field-label">母稿 ID（可选）</span><input className="text-input" value={parentId} onChange={(e) => setParentId(e.target.value)}/></label>}
      <label className="field"><span className="field-label">正文</span><textarea className="text-input knowledge-textarea" required value={body} onChange={(e) => setBody(e.target.value)}/></label>
      <label className="field"><span className="field-label">变更说明</span><input className="text-input" value={changeNote} onChange={(e) => setChangeNote(e.target.value)}/></label>
      <Button type="submit" disabled={busy}>{createdItemId ? "重试保存版本" : "保存草稿"}</Button>
    </form></Panel>}
  </div>;
}
