"use client";

import { useEffect, useState } from "react";

import { Badge, Button, Panel } from "../ui";
import { StatePlaceholder } from "../states";
import { workbenchClient } from "@/lib/workbench/client";
import type { PublishBoardBatchRecord, PublishBoardBatchesRecord, PublishBoardItemRecord, PublishBoardRecord } from "@/lib/workbench/types";

/**
 * B8 发布回链看板。
 *
 * 一条链三段：回执 URL → 搜索引擎是否收录 → 是否被 AI 引用（只认人工复核通过）。
 * 检测失败的记录停在「未查成」，不并入「未收录」；比率为 null 时显示「无数据」。
 */

function rate(value: number | null): string {
  if (value === null) return "无数据";
  return `${(value * 100).toFixed(1)}%`;
}

const STAGE_LABEL: Record<PublishBoardBatchRecord["stage"], string> = {
  not_dispatched: "未确认投喂",
  no_receipt: "已生成任务 · 无回执",
  no_visibility_check: "有回执 · 未检测收录",
  not_cited: "已检测 · 未被引用",
  cited: "走完全链",
};
const STAGE_TONE: Record<PublishBoardBatchRecord["stage"], "green" | "amber" | "red" | "slate"> = {
  not_dispatched: "slate",
  no_receipt: "amber",
  no_visibility_check: "amber",
  not_cited: "red",
  cited: "green",
};

function ReachableBadge({ row }: { row: PublishBoardItemRecord }) {
  if (row.reachability_error) return <Badge tone="amber">未查成（{row.reachability_error}）</Badge>;
  if (row.reachable === null || row.reachable === undefined) return <Badge tone="slate">未回抓</Badge>;
  if (row.reachable) return <Badge tone="green">可访问{row.reachability_status ? ` · ${row.reachability_status}` : ""}</Badge>;
  return <Badge tone="red">不可访问{row.reachability_status ? ` · ${row.reachability_status}` : ""}</Badge>;
}

function VisibilityBadge({ row }: { row: PublishBoardItemRecord }) {
  if (row.visibility_error_code) return <Badge tone="amber">未查成（{row.visibility_error_code}）</Badge>;
  if (row.visibility_matched === null) return <Badge tone="slate">未检测</Badge>;
  if (row.visibility_matched) return <Badge tone="green">已收录{row.visibility_position ? ` · 第 ${row.visibility_position} 位` : ""}</Badge>;
  return <Badge tone="red">未收录</Badge>;
}

export function PublishBoardWorkspace({
  mode,
  projectId,
  canRead,
  canExport,
}: {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
  canExport: boolean;
}) {
  const [board, setBoard] = useState<PublishBoardRecord | null>(null);
  const [batches, setBatches] = useState<PublishBoardBatchesRecord | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  const projectReady = Boolean(projectId) && projectId !== "all";
  const active = mode === "live" && canRead && projectReady;
  const loading = active && loadedFor !== projectId;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    Promise.all([workbenchClient.publishBoard(projectId), workbenchClient.publishBoardBatches(projectId)])
      .then(([record, batchRecord]) => { if (!cancelled) { setBoard(record); setBatches(batchRecord); setError(""); } })
      .catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "回链看板加载失败"); })
      .finally(() => { if (!cancelled) setLoadedFor(projectId); });
    return () => { cancelled = true; };
  }, [projectId, active]);

  if (mode !== "live") {
    return <StatePlaceholder kind="not-collected" title="演示模式不展示发布回链" description="回链依赖真实回执与检索检测，演示数据不参与。" />;
  }
  if (!canRead) {
    return <StatePlaceholder kind="permission" title="无权查看发布回链" description="当前账号缺少 publish.read 能力，请联系项目管理员。" />;
  }
  if (!projectReady) {
    return <StatePlaceholder kind="empty" title="请先选择项目" description="回链看板按项目计算；在右上角选择具体项目后查看。" />;
  }
  if (loading) return <StatePlaceholder kind="loading" title="正在汇总发布回链" />;
  if (error) return <StatePlaceholder kind="error" title="回链看板加载失败" description={error} />;
  if (!board) return null;

  const summary = board.summary;

  async function runReachability() {
    setChecking(true);
    try {
      await workbenchClient.runReceiptReachabilityCheck(projectId, 20);
      const reloaded = await workbenchClient.publishBoard(projectId);
      setBoard(reloaded); setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "回抓失败");
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="report-layout">
      <div className="sentiment-cards">
        <div className="sentiment-card">
          <span className="sentiment-card-label">已发布回执</span>
          <strong className="sentiment-card-value">{summary.total_receipts}</strong>
          <span className="sentiment-card-note">每条对应一个可访问链接</span>
        </div>
        <div className="sentiment-card">
          <span className="sentiment-card-label">可访问（回抓）</span>
          <strong className="sentiment-card-value">{summary.reachable ?? 0}</strong>
          <span className="sentiment-card-note">回抓 {summary.reachability_checked ?? 0} 条 · 不可访问 {summary.unreachable ?? 0} 条 · 可访问率 {rate(summary.reachable_rate ?? null)}</span>
        </div>
        <div className="sentiment-card">
          <span className="sentiment-card-label">可被检索</span>
          <strong className="sentiment-card-value">{summary.visibility_matched}</strong>
          <span className="sentiment-card-note">检测 {summary.visibility_checked} 条 · 失败 {summary.visibility_errored} 条 · 收录率 {rate(summary.visibility_match_rate)}</span>
        </div>
        <div className="sentiment-card">
          <span className="sentiment-card-label">被 AI 引用</span>
          <strong className="sentiment-card-value">{summary.cited}</strong>
          <span className="sentiment-card-note">占全部回执 {rate(summary.cited_rate)}</span>
        </div>
      </div>

      <div className="report-filters">
        <Button variant="secondary" disabled={checking} onClick={() => void runReachability()}>{checking ? "回抓中…" : "回抓可访问（20 条）"}</Button>
        {canExport && (
          <Button
            variant="secondary"
            icon="download"
            onClick={() => window.open(`/internal/workbench/publish-board/export?project_id=${encodeURIComponent(projectId)}`, "_blank")}
          >导出 CSV</Button>
        )}
        <span className="report-scope-note">「被引用」只认人工复核通过的引用；检测失败不算未收录</span>
      </div>

      <Panel className="report-caveats" title="按投喂批次看「卡在哪一段」">
        {!batches || batches.items.length === 0 ? (
          <p className="report-scope-note">还没有投喂批次；批次是运营一次投喂动作的单位，手工建单不归属任何批次。</p>
        ) : (
          <div className="board-list">
            {batches.items.map((row) => (
              <div className="board-row" key={row.batch_id}>
                <div className="board-row-head">
                  <span className="board-row-title">{row.name}</span>
                  <div className="board-row-badges">
                    <Badge tone={STAGE_TONE[row.stage]}>{STAGE_LABEL[row.stage]}</Badge>
                    {row.cited > 0 && <Badge tone="green">已引用 {row.cited}</Badge>}
                  </div>
                </div>
                <div className="board-row-meta">
                  <span>批次状态 {row.status}</span>
                  <span>任务 {row.tasks_total} / 登记 {row.task_count}</span>
                  <span>回执率 {row.receipt_rate === null ? "无任务" : `${(row.receipt_rate * 100).toFixed(1)}%`}</span>
                  <span>已回执 {row.with_receipt} · 可访问 {row.reachable} · 已收录 {row.visibility_matched} · 已引用 {row.cited}</span>
                </div>
              </div>
            ))}
          </div>
        )}
        <p className="report-scope-note">三段证据各自计数，不相乘成「整体成功率」；已被引用只认人工复核通过的引用。</p>
      </Panel>

      {board.items.length === 0 ? (
        <StatePlaceholder kind="empty" compact title="还没有发布回执" description="在内容发布里完成一次人工发布并填写真实 URL 结案后，这里会出现回链。" />
      ) : (
        <Panel className="report-caveats" title="回链表">
          <div className="board-list">
            {board.items.map((row) => (
              <div className="board-row" key={row.receipt_id}>
                <div className="board-row-head">
                  <a href={row.published_url} target="_blank" rel="noreferrer" className="board-row-title">
                    {row.content_title || row.published_url}
                  </a>
                  <div className="board-row-badges">
                    <ReachableBadge row={row} />
                    <VisibilityBadge row={row} />
                    {row.cited ? <Badge tone="green">已被引用</Badge> : <Badge tone="slate">未被引用</Badge>}
                  </div>
                </div>
                <div className="board-row-meta">
                  <span>#{row.task_serial_no}</span>
                  <span>{row.channel_name ?? "未知渠道"}</span>
                  <span>{row.published_host ?? "无域名"}</span>
                  <span>回执 {row.received_at.slice(0, 10)}</span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <Panel className="report-caveats" title="口径提示">
        <ul>{board.caveats.map((note) => <li key={note}>{note}</li>)}</ul>
      </Panel>
    </div>
  );
}
