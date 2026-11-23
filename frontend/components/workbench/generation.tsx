"use client";

import { useEffect, useState } from "react";
import { Button, Panel } from "../ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { GenerationBatchRecord, GenerationBatchSummary } from "@/lib/workbench/types";

const STATUS_TEXT: Record<string, string> = {
  queued: "待跑", running: "跑批中", completed: "已完成", failed: "失败",
  pending: "待出稿", drafted: "已出稿",
};

function stamp(iso: string) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

/** G1/G2 生成批次：从缺口建批 → 跑批出模板稿 → 人工审。 */
export function GenerationWorkspace({ mode, projectId, canRead, canWrite, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canWrite: boolean;
  onNotice?: (message: string, tone?: "blue" | "green" | "amber" | "red") => void;
}) {
  const [name, setName] = useState("缺口补稿");
  const [source, setSource] = useState<"opportunity" | "question">("opportunity");
  const [limit, setLimit] = useState(10);
  const [batches, setBatches] = useState<GenerationBatchSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<GenerationBatchRecord | null>(null);
  const [loadedKey, setLoadedKey] = useState("");
  const [detailKey, setDetailKey] = useState("");
  const [opened, setOpened] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const listKey = `${mode}:${projectId}:list`;
  const loadingList = mode === "live" && canRead && projectId !== "all" && loadedKey !== listKey;
  const loadingDetail = !!selected && detailKey !== `${listKey}:${selected}`;

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.generationBatches(projectId)
      .then((rows) => {
        if (!active) return;
        setBatches(rows);
        setSelected((current) => current || rows[0]?.batch_id || "");
        setLoadedKey(listKey);
      })
      .catch((cause) => {
        if (!active) return;
        setError(cause instanceof Error ? cause.message : "批次列表加载失败");
        setLoadedKey(listKey);
      });
    return () => { active = false; };
  }, [mode, canRead, projectId, listKey]);

  useEffect(() => {
    if (!selected || mode !== "live" || !canRead) return;
    let active = true;
    workbenchClient.generationBatch(projectId, selected)
      .then((record) => { if (active) { setDetail(record); setDetailKey(`${listKey}:${selected}`); } })
      .catch((cause) => {
        if (!active) return;
        setDetail(null);
        setError(cause instanceof Error ? cause.message : "批次详情加载失败");
        setDetailKey(`${listKey}:${selected}`);
      });
    return () => { active = false; };
  }, [selected, mode, canRead, projectId, listKey]);

  const create = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const record = await workbenchClient.createGenerationBatch(projectId, { name: name.trim() || "缺口补稿", source, limit });
      setDetail(record);
      setSelected(record.batch_id);
      setBatches((current) => [{
        batch_id: record.batch_id, name: record.name, source: record.source, status: record.status,
        engine_code: record.engine_code, created_at: record.created_at, totals: record.totals,
      }, ...current]);
      setLoadedKey("");
      setDetailKey("");
      onNotice?.(`已建批次：${record.totals.total} 条待出稿`, "green");
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "建批失败";
      setError(message);
      onNotice?.(message, "red");
    } finally {
      setBusy(false);
    }
  };

  const run = async () => {
    if (!selected || busy) return;
    setBusy(true);
    setError("");
    try {
      const record = await workbenchClient.runGenerationBatch(projectId, selected);
      setDetail(record);
      setBatches((current) => current.map((batch) => batch.batch_id === record.batch_id
        ? { ...batch, status: record.status, totals: { total: record.totals.total, drafted: record.totals.drafted, failed: record.totals.failed } }
        : batch));
      onNotice?.(`已出稿 ${record.totals.drafted} 条，待人工审`, "green");
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "跑批失败";
      setError(message);
      onNotice?.(message, "red");
    } finally {
      setBusy(false);
    }
  };

  const review = async (itemId: string, reviewed: boolean) => {
    if (!selected || busy) return;
    try {
      await workbenchClient.reviewGenerationItem(projectId, selected, itemId, reviewed);
      setDetail((current) => current ? {
        ...current,
        items: current.items.map((item) => item.item_id === itemId ? { ...item, reviewed } : item),
      } : current);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "审稿标记失败");
    }
  };

  const exportCsv = async () => {
    if (!selected) return;
    try {
      await workbenchClient.exportGenerationBatch(projectId, selected);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "导出失败");
    }
  };

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">生成批次仅真实接口模式可用。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有内容查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  return <Panel className="knowledge-list-panel generation-panel">
    <div className="panel-heading">
      <div><h3>生成批次</h3><p>从引用缺口或未提及问题出题；模板合成草稿，进审稿队列，不自动发布。</p></div>
    </div>

    {canWrite && <div className="generation-form">
      <label>批次名<input value={name} onChange={(event) => setName(event.target.value)} maxLength={120} /></label>
      <label>来源
        <select value={source} onChange={(event) => setSource(event.target.value as "opportunity" | "question")}>
          <option value="opportunity">机会缺口（竞品被引用而我缺席）</option>
          <option value="question">未提及问题（测过但没提到品牌）</option>
        </select>
      </label>
      <label>条数<input type="number" min={1} max={50} value={limit} onChange={(event) => setLimit(Number(event.target.value) || 1)} /></label>
      <Button onClick={create} disabled={busy}>{busy ? "处理中…" : "建批"}</Button>
    </div>}

    {error && <p className="form-error" role="alert">{error}</p>}
    {loadingList && <p className="knowledge-empty">正在加载批次…</p>}

    {batches.length > 0 && <div className="generation-history">
      {batches.map((batch) => (
        <button key={batch.batch_id} type="button"
          className={`generation-chip ${selected === batch.batch_id ? "generation-chip-active" : ""}`}
          onClick={() => setSelected(batch.batch_id)}>
          <span>{batch.name}</span>
          <small>{stamp(batch.created_at)} · {batch.totals.drafted}/{batch.totals.total} · {STATUS_TEXT[batch.status] ?? batch.status}</small>
        </button>
      ))}
    </div>}

    {!loadingList && batches.length === 0 && <p className="knowledge-empty">还没有批次。先攒机会缺口或跑一轮监测，再来建批。</p>}

    {selected && loadingDetail && <p className="knowledge-empty">正在加载批次详情…</p>}

    {selected && detail && !loadingDetail && <>
      <div className="generation-head">
        <div>
          <strong>{detail.name}</strong>
          <small>{detail.source === "opportunity" ? "机会缺口" : "未提及问题"} · 共 {detail.totals.total} 条 · 出稿 {detail.totals.drafted} · 失败 {detail.totals.failed}</small>
        </div>
        <div className="toolbar-extra">
          {canWrite && <Button onClick={run} disabled={busy || detail.totals.pending === 0}>{detail.totals.pending === 0 ? "已全部出稿" : "跑批出稿"}</Button>}
          {canRead && <Button variant="secondary" onClick={exportCsv}>导出 CSV</Button>}
        </div>
      </div>

      <div className="generation-items">
        {detail.items.map((item) => {
          const open = opened.includes(item.item_id);
          return <div className={`generation-item generation-item-${item.status}`} key={item.item_id}>
            <div className="generation-item-head">
              <div className="generation-item-title">
                <strong>{item.title}</strong>
                <small>
                  {STATUS_TEXT[item.status] ?? item.status} · {item.generation_mode === "template" ? "模板合成" : "模型出稿"}
                  {item.brief?.gap_type ? ` · 缺口：${item.brief.gap_type}` : ""}
                  {item.reviewed ? " · 已审" : ""}
                </small>
              </div>
              <div className="toolbar-extra">
                <Button variant="secondary" onClick={() => setOpened((current) => open ? current.filter((id) => id !== item.item_id) : [...current, item.item_id])}>
                  {open ? "收起" : item.draft_body ? "看草稿/简报" : "看简报"}
                </Button>
                {canWrite && item.draft_body && <Button variant={item.reviewed ? "secondary" : "primary"} onClick={() => void review(item.item_id, !item.reviewed)} disabled={busy}>
                  {item.reviewed ? "取消已审" : "标记已审"}
                </Button>}
              </div>
            </div>
            {item.failure_reason && <p className="form-error">{item.failure_reason}</p>}
            {open && <div className="generation-detail">
              <div className="generation-brief">
                <h5>简报</h5>
                <p>问题：{item.brief?.question ?? "—"}</p>
                {item.brief?.samples !== null && item.brief?.samples !== undefined && <p>监测样本 {item.brief.samples} 条，品牌提及 {item.brief.mentions} 次</p>}
                <p>事实 {item.brief?.facts?.length ?? 0} 条 · FAQ {item.brief?.faqs?.length ?? 0} 条 · 来源线索 {item.brief?.sources?.length ?? 0} 个</p>
                <p className="generation-guidance">{item.brief?.guidance}</p>
              </div>
              {item.draft_body && <pre className="generation-draft">{item.draft_body}</pre>}
            </div>}
          </div>;
        })}
      </div>

      <p className="tracks-footnote">{detail.disclaimer ?? "批次只产出草稿并进审稿队列，不会自动发布；模型出稿默认关闭。"}</p>
    </>}
  </Panel>;
}
