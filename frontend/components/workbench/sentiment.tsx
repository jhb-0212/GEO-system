"use client";

import { useEffect, useState } from "react";

import { Badge, Button, SelectInput } from "../ui";
import { StatePlaceholder } from "../states";
import { workbenchClient } from "@/lib/workbench/client";
import type { SentimentItemRecord, SentimentSummaryRecord } from "@/lib/workbench/types";

/**
 * B5 情绪原文统计。
 *
 * 只做两件事：三档计数（正/中/负 + 未标注）、按可信度排序的原文列表。
 * 情绪结论只来自人工标注；可信度只是来源类别的排序权重，不是内容质量评级。
 */

const POLARITY_OPTIONS = [
  { value: "", label: "全部原文" },
  { value: "positive", label: "正向共识" },
  { value: "neutral", label: "中性共识" },
  { value: "negative", label: "负向共识" },
  { value: "pending_second", label: "待第二人" },
  { value: "disputed", label: "有分歧" },
  { value: "unlabeled", label: "未标注" },
];

const SORT_OPTIONS = [
  { value: "credibility", label: "按来源可信度" },
  { value: "recent", label: "按发布时间" },
];

const POLARITY_LABEL: Record<string, string> = { positive: "正向", neutral: "中性", negative: "负向" };
const POLARITY_TONE: Record<string, "green" | "slate" | "red"> = { positive: "green", neutral: "slate", negative: "red" };

function stateBadge(row: SentimentItemRecord) {
  if (row.state === "pending_second") return <Badge tone="amber">待第二人</Badge>;
  if (row.state === "disputed") return <Badge tone="red">有分歧</Badge>;
  if (row.state === "unlabeled") return <Badge tone="slate">未标注</Badge>;
  return <Badge tone={POLARITY_TONE[row.state]}>{POLARITY_LABEL[row.state]}共识</Badge>;
}

function pct(value: number | null): string {
  if (value === null) return "无引用";
  return `${(value * 100).toFixed(1)}%`;
}

export function SentimentWorkspace({
  mode,
  projectId,
  canRead,
  canWrite,
  onNotice,
}: {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
  canWrite: boolean;
  onNotice: (message: string) => void;
}) {
  const [summary, setSummary] = useState<SentimentSummaryRecord | null>(null);
  const [items, setItems] = useState<SentimentItemRecord[] | null>(null);
  const [meta, setMeta] = useState<{ page: number; page_size: number; total: number } | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [polarity, setPolarity] = useState("");
  const [sort, setSort] = useState("credibility");
  const [page, setPage] = useState(1);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [correctingId, setCorrectingId] = useState<string | null>(null);

  const projectReady = Boolean(projectId) && projectId !== "all";
  const active = mode === "live" && canRead && projectReady;
  const key = `${projectId}:${polarity}:${sort}:${page}`;
  const loading = active && loadedFor !== key;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    Promise.all([
      workbenchClient.sentimentSummary(projectId),
      workbenchClient.sentimentItems(projectId, { polarity: polarity || undefined, sort, page: String(page), page_size: "20" }),
    ])
      .then(([summaryRecord, list]) => {
        if (cancelled) return;
        setSummary(summaryRecord);
        setItems(list.data);
        setMeta(list.meta);
        setError("");
      })
      .catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "情绪统计加载失败"); })
      .finally(() => { if (!cancelled) setLoadedFor(key); });
    return () => { cancelled = true; };
  }, [projectId, active, polarity, sort, page, key]);

  async function label(row: SentimentItemRecord, next: "positive" | "neutral" | "negative") {
    if (!canWrite) return;
    setSavingId(row.citation_id);
    try {
      await workbenchClient.labelSentiment(projectId, row.citation_id, { polarity: next });
      const fresh = await workbenchClient.sentimentSummary(projectId);
      const freshItems = await workbenchClient.sentimentItems(projectId, {
        polarity: polarity || undefined,
        sort,
        page: String(page),
        page_size: "20",
      });
      setSummary(fresh);
      setItems(freshItems.data);
      setMeta(freshItems.meta);
      onNotice(`已提交${POLARITY_LABEL[next]}标注，等待第二人独立盲评`);
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "标注失败");
    } finally {
      setSavingId(null);
    }
  }

  async function corrective(row: SentimentItemRecord) {
    if (!canWrite) return;
    setCorrectingId(row.citation_id);
    try {
      const result = await workbenchClient.createCorrectiveBatch(projectId, row.citation_id, {});
      const reused = (result as { reused?: boolean })?.reused;
      onNotice(reused ? "这条原文已有纠正批次，直接复用" : "已建纠正批次：到内容生成批次里审稿");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "纠正批次创建失败");
    } finally {
      setCorrectingId(null);
    }
  }

  if (mode !== "live") {
    return <StatePlaceholder kind="not-collected" title="演示模式不展示情绪统计" description="情绪只统计人工复核过的引用原文，演示数据不参与。" />;
  }
  if (!canRead) {
    return <StatePlaceholder kind="permission" title="无权查看情绪统计" description="当前账号缺少内容读取能力，请联系项目管理员。" />;
  }
  if (!projectReady) {
    return <StatePlaceholder kind="empty" title="请先选择项目" description="情绪统计按项目计算；在右上角选择具体项目后查看。" />;
  }
  if (loading) return <StatePlaceholder kind="loading" title="正在统计情绪原文" />;
  if (error) return <StatePlaceholder kind="error" title="情绪统计加载失败" description={error} />;
  if (!summary) return null;

  const totalPages = meta ? Math.max(1, Math.ceil(meta.total / meta.page_size)) : 1;

  return (
    <div className="report-layout">
      <div className="sentiment-cards">
        {(["positive", "neutral", "negative"] as const).map((tone) => (
          <div className="sentiment-card" key={tone}>
            <span className="sentiment-card-label">{POLARITY_LABEL[tone]}</span>
            <strong className={`sentiment-card-value tone-${tone}`}>{summary.counts[tone]}</strong>
            <span className="sentiment-card-note">
              {summary.consensus_total ? `${(summary.counts[tone] / summary.consensus_total * 100).toFixed(1)}% of 共识` : "尚无共识"}
            </span>
          </div>
        ))}
        <div className="sentiment-card">
          <span className="sentiment-card-label">未标注</span>
          <strong className="sentiment-card-value">{summary.unlabeled}</strong>
          <span className="sentiment-card-note">
            标注覆盖率 {pct(summary.coverage)}
          </span>
        </div>
      </div>

      <p className="report-scope-note">
        共识 {summary.consensus_total} 条 · 待第二人 {summary.pending_second} 条 · 有分歧 {summary.disputed} 条。
        单人标注不计入三档计数；只有两名不同标注人同档才进入共识分母。
      </p>

      <div className="report-filters">
        <SelectInput label="倾向筛选" value={polarity} onChange={(event) => { setPolarity(event.target.value); setPage(1); }}>
          {POLARITY_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </SelectInput>
        <SelectInput label="排序" value={sort} onChange={(event) => { setSort(event.target.value); setPage(1); }}>
          {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </SelectInput>
        <span className="report-scope-note">共 {meta?.total ?? 0} 条已复核引用 · 可信度是来源类别权重，不是内容评级</span>
      </div>

      {items && items.length === 0 && (
        <StatePlaceholder kind="empty" compact title="没有符合条件的原文" description="当前筛选下没有已复核引用；先完成引用复核再来标注。" />
      )}

      {items && items.length > 0 && (
        <div className="sentiment-list">
          {items.map((row) => (
            <article className="sentiment-item" key={row.citation_id}>
              <div className="sentiment-item-head">
                <a href={row.url} target="_blank" rel="noreferrer" className="sentiment-item-title">{row.title || row.url}</a>
                {stateBadge(row)}
              </div>
              {row.excerpt && <p className="sentiment-item-excerpt">{row.excerpt.slice(0, 220)}{row.excerpt.length > 220 ? "…" : ""}</p>}
              <div className="sentiment-item-meta">
                <Badge tone="slate">{row.credibility_tier}</Badge>
                <span>{row.domain ?? "未知来源"}</span>
                {row.published_at && <span>发布 {row.published_at.slice(0, 10)}</span>}
                {row.note && <span>备注：{row.note}</span>}
              </div>
              {canWrite && (
                <div className="sentiment-item-ops">
                  <Button variant="quiet" disabled={savingId === row.citation_id} onClick={() => void label(row, "positive")}>标为正向</Button>
                  <Button variant="quiet" disabled={savingId === row.citation_id} onClick={() => void label(row, "neutral")}>标为中性</Button>
                  <Button variant="quiet" disabled={savingId === row.citation_id} onClick={() => void label(row, "negative")}>标为负向</Button>
                  {row.state === "negative" && (
                    <Button variant="primary" disabled={correctingId === row.citation_id} onClick={() => void corrective(row)}>生成纠正稿</Button>
                  )}
                </div>
              )}
            </article>
          ))}
        </div>
      )}

      {meta && meta.total > meta.page_size && (
        <div className="sentiment-pager">
          <Button variant="quiet" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>上一页</Button>
          <span>第 {page} / {totalPages} 页</span>
          <Button variant="quiet" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>下一页</Button>
        </div>
      )}
    </div>
  );
}
