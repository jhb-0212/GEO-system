"use client";

import { useEffect, useState } from "react";
import { Button, Panel } from "../ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { EncyclopediaEntryRecord, EncyclopediaReference } from "@/lib/workbench/types";

const PLATFORMS: { value: string; label: string }[] = [
  { value: "baidu_baike", label: "百度百科" },
  { value: "sogou_baike", label: "搜狗百科" },
  { value: "douyin_baike", label: "抖音百科" },
  { value: "wikipedia", label: "维基百科" },
  { value: "other", label: "其他平台" },
];

const STATUS_TONE: Record<string, string> = {
  draft: "badge-slate", pending_review: "badge-amber", published: "badge-green", rejected: "badge-red",
};

/** 参考资料一行一条：`标题 | https://url | 备注`。 */
function parseReferences(text: string): EncyclopediaReference[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [title, url, note] = line.split("|").map((part) => part.trim());
      return { title: title ?? "", url: url ?? "", note: note || null };
    })
    .filter((ref) => ref.title && ref.url);
}

function formatReferences(refs: EncyclopediaReference[]): string {
  return (refs ?? []).map((ref) => `${ref.title} | ${ref.url} | ${ref.note ?? ""}`.trim()).join("\n");
}

/** K4 百科词条：站内起草 → 提交审核 → 通过/驳回 → 登记第三方外链。 */
export function EncyclopediaWorkspace({ mode, projectId, canRead, canWrite, canReview, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean; canReview: boolean;
  onNotice?: (message: string, tone?: "blue" | "green" | "amber" | "red") => void;
}) {
  const [entries, setEntries] = useState<EncyclopediaEntryRecord[]>([]);
  const [loadedKey, setLoadedKey] = useState("");
  const [opened, setOpened] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [title, setTitle] = useState("");
  const [platform, setPlatform] = useState("baidu_baike");
  const [summary, setSummary] = useState("");
  const [body, setBody] = useState("");
  const [refs, setRefs] = useState("");

  const [editTitle, setEditTitle] = useState("");
  const [editSummary, setEditSummary] = useState("");
  const [editBody, setEditBody] = useState("");
  const [editRefs, setEditRefs] = useState("");
  const [publishUrl, setPublishUrl] = useState("");
  const [reviewNote, setReviewNote] = useState("");

  const listKey = `${mode}:${projectId}:encyclopedia`;
  const loading = mode === "live" && canRead && projectId !== "all" && loadedKey !== listKey;

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.encyclopediaEntries(projectId)
      .then((rows) => { if (active) { setEntries(rows); setLoadedKey(listKey); } })
      .catch((cause) => {
        if (!active) return;
        setError(cause instanceof Error ? cause.message : "词条加载失败");
        setLoadedKey(listKey);
      });
    return () => { active = false; };
  }, [mode, canRead, projectId, listKey]);

  const create = async () => {
    if (busy) return;
    if (!title.trim() || !body.trim()) { setError("词条名与正文不能为空"); return; }
    setBusy(true); setError("");
    try {
      const record = await workbenchClient.createEncyclopediaEntry(projectId, {
        title: title.trim(), platform, body: body.trim(), summary: summary.trim() || undefined,
        references: parseReferences(refs),
      });
      setEntries((current) => [record, ...current]);
      setTitle(""); setSummary(""); setBody(""); setRefs("");
      onNotice?.(`已建词条：${record.title}（草稿）`, "green");
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "新建词条失败";
      setError(message); onNotice?.(message, "red");
    } finally { setBusy(false); }
  };

  const openEntry = (entry: EncyclopediaEntryRecord) => {
    if (opened === entry.entry_id) { setOpened(""); return; }
    setOpened(entry.entry_id);
    setEditTitle(entry.title); setEditSummary(entry.summary ?? "");
    setEditBody(entry.body); setEditRefs(formatReferences(entry.references));
    setPublishUrl(""); setReviewNote("");
  };

  const patch = async (entryId: string, payload: Parameters<typeof workbenchClient.updateEncyclopediaEntry>[2], message: string) => {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const record = await workbenchClient.updateEncyclopediaEntry(projectId, entryId, payload);
      setEntries((current) => current.map((row) => row.entry_id === entryId ? record : row));
      onNotice?.(message, "green");
    } catch (cause) {
      const message2 = cause instanceof Error ? cause.message : "保存失败";
      setError(message2); onNotice?.(message2, "red");
    } finally { setBusy(false); }
  };

  const run = async (fn: () => Promise<EncyclopediaEntryRecord>, message: string) => {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const record = await fn();
      setEntries((current) => current.map((row) => row.entry_id === record.entry_id ? record : row));
      onNotice?.(message, "green");
    } catch (cause) {
      const text = cause instanceof Error ? cause.message : "操作失败";
      setError(text); onNotice?.(text, "red");
    } finally { setBusy(false); }
  };

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">百科词条仅真实接口模式可用。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有内容查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  return <Panel className="knowledge-list-panel generation-panel">
    <div className="panel-heading">
      <div><h3>百科词条</h3><p>站内起草 → 提交审核 → 通过后到平台提交并回登外链；系统不代第三方平台发布。</p></div>
    </div>

    {canWrite && <div className="generation-form">
      <label>词条名<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={255} placeholder="广东省AI数字人才就业实训基地" /></label>
      <label>平台<select value={platform} onChange={(event) => setPlatform(event.target.value)}>
        {PLATFORMS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select></label>
      <label>摘要<input value={summary} onChange={(event) => setSummary(event.target.value)} maxLength={1000} placeholder="一句话定位（可留空）" /></label>
      <label className="generation-wide">正文<textarea value={body} onChange={(event) => setBody(event.target.value)} rows={4} placeholder="按「定义 / 事实 / 联系方式」分段的百科体正文" /></label>
      <label className="generation-wide">参考资料<textarea value={refs} onChange={(event) => setRefs(event.target.value)} rows={3} placeholder="一行一条：官网简介 | https://gdccai.com/about | 一手来源" /></label>
      <Button onClick={() => void create()} disabled={busy}>{busy ? "处理中…" : "新建草稿"}</Button>
    </div>}

    {error && <p className="form-error" role="alert">{error}</p>}
    {loading && <p className="knowledge-empty">正在加载词条…</p>}
    {!loading && entries.length === 0 && <p className="knowledge-empty">还没有词条。先建一份草稿，补齐参考资料再提交审核。</p>}

    <div className="generation-items">
      {entries.map((entry) => {
        const open = opened === entry.entry_id;
        const editable = canWrite && (entry.status === "draft" || entry.status === "rejected");
        return <div className="generation-item" key={entry.entry_id}>
          <div className="generation-item-head">
            <div className="generation-item-title">
              <strong>{entry.title}</strong>
              <small>
                {entry.platform_label} · <span className={STATUS_TONE[entry.status] ?? "badge-slate"}>{entry.status_label}</span>
                · 参考资料 {entry.references.length} 条
                {entry.version > 1 ? ` · v${entry.version}` : ""}
                {entry.published_url ? " · 已回登外链" : ""}
              </small>
            </div>
            <div className="toolbar-extra">
              <Button variant="secondary" onClick={() => openEntry(entry)}>{open ? "收起" : "展开/编辑"}</Button>
              {canWrite && (entry.status === "draft" || entry.status === "rejected") && <Button onClick={() => void run(() => workbenchClient.submitEncyclopediaEntry(projectId, entry.entry_id), "已提交审核")} disabled={busy}>提交审核</Button>}
            </div>
          </div>

          {open && <div className="generation-detail">
            <div className="generation-brief">
              <h5>审核记录</h5>
              <p>状态：{entry.status_label}</p>
              <p>审核人意见：{entry.review_note ?? "—"}</p>
              <p>审核时间：{entry.reviewed_at ?? "—"}</p>
              {
                /* 外链只展示，不在这里反复填 */
              }
              <p>外链：{entry.published_url ? <a href={entry.published_url} target="_blank" rel="noreferrer">{entry.published_url}</a> : "—"}</p>
              {canReview && entry.status === "pending_review" && <div className="generation-review">
                <label>审核意见<input value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="驳回必须写原因" /></label>
                <div className="toolbar-extra">
                  <Button onClick={() => void run(() => workbenchClient.reviewEncyclopediaEntry(projectId, entry.entry_id, true, reviewNote), "已审核通过")} disabled={busy}>通过</Button>
                  <Button variant="secondary" onClick={() => void run(() => workbenchClient.reviewEncyclopediaEntry(projectId, entry.entry_id, false, reviewNote), "已驳回")} disabled={busy}>驳回</Button>
                </div>
              </div>}
              {canWrite && entry.status === "published" && !entry.published_url && <div className="generation-review">
                <label>平台外链<input value={publishUrl} onChange={(event) => setPublishUrl(event.target.value)} placeholder="https://baike.baidu.com/item/..." /></label>
                <Button onClick={() => void run(() => workbenchClient.publishEncyclopediaEntry(projectId, entry.entry_id, publishUrl.trim()), "已登记外链")} disabled={busy || !publishUrl.trim()}>回登外链</Button>
              </div>}
            </div>

            <div>
              {editable ? <div className="generation-edit">
                <label>词条名<input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} maxLength={255} /></label>
                <label>摘要<input value={editSummary} onChange={(event) => setEditSummary(event.target.value)} maxLength={1000} /></label>
                <label>正文<textarea value={editBody} onChange={(event) => setEditBody(event.target.value)} rows={8} /></label>
                <label>参考资料<textarea value={editRefs} onChange={(event) => setEditRefs(event.target.value)} rows={3} /></label>
                <Button onClick={() => void patch(entry.entry_id, {
                  title: editTitle.trim(), summary: editSummary.trim(), body: editBody.trim(),
                  references: parseReferences(editRefs),
                }, "已保存草稿")} disabled={busy}>保存</Button>
              </div> : <pre className="generation-draft">{entry.summary ? `${entry.summary}\n\n` : ""}{entry.body}</pre>}
            </div>
          </div>}
        </div>;
      })}
    </div>

    <p className="tracks-footnote">审核通过只代表站内可发；第三方百科的提交与结果仍由人在平台完成，回来登记外链即可。</p>
  </Panel>;
}
