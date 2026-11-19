"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Panel } from "./ui";
import { DateField } from "./date-field";
import { workbenchClient } from "@/lib/workbench/client";
import { formatDateTime } from "@/lib/workbench/format";
import { beijingCurrentMonth } from "@/lib/workbench/time";
import type { MonthlyReport, MonthlyReportSnapshot, MonthlyReportSnapshotSummary } from "@/lib/workbench/types";

const rate = (value: number | null) => value === null ? "--" : `${(value * 100).toFixed(1)}%`;

export function MonthlyReportWorkspace({ mode, projectId, canRead, canFreeze, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canFreeze: boolean;
  onNotice?: (message: string) => void;
}) {
  const [month, setMonth] = useState(beijingCurrentMonth);
  const [report, setReport] = useState<MonthlyReport | null>(null);
  const [snapshots, setSnapshots] = useState<MonthlyReportSnapshotSummary[]>([]);
  const [selectedSnapshot, setSelectedSnapshot] = useState<MonthlyReportSnapshot | null>(null);
  const [loadingSnapshotId, setLoadingSnapshotId] = useState("");
  const [loadedKey, setLoadedKey] = useState("");
  const [freezing, setFreezing] = useState(false);
  const [error, setError] = useState("");
  const requestKey = `${projectId}:${month}`;
  const loading = mode === "live" && canRead && !!projectId && projectId !== "all" && !!month && loadedKey !== requestKey;
  const currentSnapshot = snapshots.find((item) => item.month === month);
  const displayReport = selectedSnapshot?.report ?? report;

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([
      workbenchClient.statsMonthly(projectId, month),
      workbenchClient.monthlySnapshots(projectId),
    ])
      .then(([data, history]) => {
        if (!active) return;
        setReport(data);
        setSnapshots(history);
        setError("");
        setLoadedKey(requestKey);
      })
      .catch((cause) => {
        if (!active) return;
        setReport(null);
        setError(cause instanceof Error ? cause.message : "月报加载失败");
        setLoadedKey(requestKey);
      });
    return () => { active = false; };
  }, [mode, projectId, canRead, month, requestKey]);

  async function viewSnapshot(snapshot: MonthlyReportSnapshotSummary) {
    if (mode !== "live") return;
    setLoadingSnapshotId(snapshot.snapshot_id);
    try {
      const detail = await workbenchClient.monthlySnapshot(projectId, snapshot.snapshot_id);
      setSelectedSnapshot(detail);
      setMonth(detail.month);
      onNotice?.(`正在查看 ${detail.month} 冻结月报`);
    } catch (cause) {
      onNotice?.(cause instanceof Error ? cause.message : "月报快照加载失败");
    } finally { setLoadingSnapshotId(""); }
  }

  async function freeze() {
    if (mode !== "live" || !canFreeze || currentSnapshot) return;
    setFreezing(true);
    try {
      const frozen = await workbenchClient.freezeMonthlyReport(projectId, month);
      const history = await workbenchClient.monthlySnapshots(projectId);
      setSnapshots(history);
      setSelectedSnapshot(frozen);
      onNotice?.(`${month} 月报已冻结，后续复盘以快照为准`);
    } catch (cause) {
      onNotice?.(cause instanceof Error ? cause.message : "月报冻结失败");
    } finally { setFreezing(false); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">月报请切换到真实接口模式查看。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有统计查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择一个项目。</p></Panel>;

  return <div className="statistics-workspace monthly-report-workspace">
    <Panel className="knowledge-list-panel monthly-report-main">
      <div className="panel-heading">
        <div><h3>月度报告</h3><p>聚合本月任务、回答与发布结案；冻结后作为复盘和审计的不可变版本</p></div>
        <div className="toolbar-extra">
          <DateField id="monthly-month" label="报告月份" mode="month" value={month} onChange={(value) => { setMonth(value); setSelectedSnapshot(null); }} />
          <Badge tone={selectedSnapshot ? "amber" : "blue"}>{selectedSnapshot ? "冻结快照" : report?.month ?? month}</Badge>
          {canFreeze && !currentSnapshot && <Button disabled={freezing || loading || !report} onClick={() => void freeze()}>{freezing ? "冻结中…" : "冻结本月月报"}</Button>}
        </div>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {selectedSnapshot && <div className="monthly-snapshot-banner">
        <div><strong>正在查看 {selectedSnapshot.month} 冻结月报</strong><small>冻结于 {formatDateTime(selectedSnapshot.captured_at)} · {selectedSnapshot.captured_by_name || selectedSnapshot.captured_by || "系统"} · hash {selectedSnapshot.snapshot_hash.slice(0, 12)}…</small></div>
        <Button variant="secondary" onClick={() => setSelectedSnapshot(null)}>回到实时月报</Button>
      </div>}
      {!selectedSnapshot && currentSnapshot && <div className="monthly-snapshot-banner is-muted">
        <div><strong>{month} 已冻结</strong><small>当前展示的是实时数据；复盘请打开冻结快照，避免后续数据变化影响口径。</small></div>
        <Button variant="secondary" onClick={() => void viewSnapshot(currentSnapshot)}>查看冻结快照</Button>
      </div>}
      {loading && <p className="knowledge-empty">正在加载月报…</p>}
      {!loading && !displayReport && !error && <p className="knowledge-empty">暂无月报数据</p>}
      {displayReport && !loading && <>
        <div className="stats-cards monthly-kpi-grid">
          <div><span>本月任务</span><strong>{displayReport.tasks.total}</strong></div>
          <div><span>任务完成率</span><strong>{rate(displayReport.tasks.completion_rate)}</strong></div>
          <div><span>有效回答</span><strong>{displayReport.answers.valid_answers}</strong></div>
          <div><span>品牌提及率</span><strong>{rate(displayReport.answers.brand_mention_rate)}</strong></div>
          <div><span>引用率</span><strong>{rate(displayReport.answers.citation_rate)}</strong></div>
          <div><span>发布结案</span><strong>{displayReport.published_receipts}</strong></div>
        </div>
        <p className="stats-excluded">任务：完成 {displayReport.tasks.done} · 失败 {displayReport.tasks.failed} · 运行中 {displayReport.tasks.running} · 待执行 {displayReport.tasks.pending}</p>
        <p className="stats-excluded">回答：总样本 {displayReport.answers.total_samples} · 失败率 {rate(displayReport.answers.failure_rate)} · 24 小时新鲜度 {rate(displayReport.answers.fresh_24h_rate)} · 题库覆盖 {rate(displayReport.answers.prompt_coverage)}</p>
        {displayReport.leads ? <div className="stats-cards">
          <div><span>咨询总量</span><strong>{displayReport.leads.total}</strong></div>
          <div><span>有效线索</span><strong>{displayReport.leads.valid}</strong></div>
          <div><span>已联系</span><strong>{displayReport.leads.contacted}</strong></div>
          <div><span>已报名</span><strong>{displayReport.leads.enrolled}</strong></div>
          <div><span>线索转化率</span><strong>{rate(displayReport.leads.conversion_rate)}</strong></div>
        </div> : <p className="stats-excluded">当前月报没有线索段：冻结时缺少 lead.read，或该账号无权限。</p>}
        <p className="knowledge-footnote">报告区间 {formatDateTime(displayReport.period_start)} 至 {formatDateTime(displayReport.period_end)}；period_end 为下月 1 日 00:00，不包含在统计内。</p>
      </>}
    </Panel>
    <Panel className="monthly-history-panel">
      <div className="panel-heading"><div><h3>历史快照</h3><p>同一月份只冻结一次；点击查看当时固定的报告原文</p></div><Badge tone="slate">{snapshots.length}</Badge></div>
      {!snapshots.length && <p className="knowledge-empty">还没有冻结月报。完成当月数据核对后冻结一份，后续复盘以它为准。</p>}
      {!!snapshots.length && <div className="monthly-history-list">
        {snapshots.map((item) => <button type="button" key={item.snapshot_id} className={`monthly-history-item ${selectedSnapshot?.snapshot_id === item.snapshot_id ? "selected" : ""}`} onClick={() => void viewSnapshot(item)} disabled={!!loadingSnapshotId}>
          <span><strong>{item.month}</strong><small>{formatDateTime(item.captured_at)} · {item.captured_by_name || "系统"} · 发布 {item.published_receipts} 条</small></span>
          <span className="monthly-history-metrics"><small>任务 {item.tasks_total}</small><small>回答 {item.valid_answers}</small><small>提及 {rate(item.brand_mention_rate)}</small><small>引用 {rate(item.citation_rate)}</small></span>
          <Badge tone="slate">{loadingSnapshotId === item.snapshot_id ? "读取中" : item.snapshot_hash.slice(0, 8)}</Badge>
        </button>)}
      </div>}
    </Panel>
  </div>;
}
