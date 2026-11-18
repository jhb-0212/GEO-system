"use client";

import { useEffect, useState } from "react";
import { Badge, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { MonthlyReport } from "@/lib/workbench/types";

const rate = (value: number | null) => value === null ? "--" : `${(value * 100).toFixed(1)}%`;

function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export function MonthlyReportWorkspace({ mode, projectId, canRead }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean;
}) {
  const [month, setMonth] = useState(currentMonth);
  const [report, setReport] = useState<MonthlyReport | null>(null);
  const [loadedKey, setLoadedKey] = useState("");
  const [error, setError] = useState("");
  const requestKey = `${projectId}:${month}`;
  const loading = mode === "live" && canRead && !!projectId && projectId !== "all" && !!month && loadedKey !== requestKey;

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all" || !month) return;
    let active = true;
    workbenchClient.statsMonthly(projectId, month)
      .then((data) => { if (active) { setReport(data); setError(""); setLoadedKey(requestKey); } })
      .catch((cause) => { if (active) { setReport(null); setError(cause instanceof Error ? cause.message : "月报加载失败"); setLoadedKey(requestKey); } });
    return () => { active = false; };
  }, [mode, projectId, canRead, month, requestKey]);

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">月报请切换到真实接口模式查看。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有统计查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择一个项目。</p></Panel>;

  return <div className="statistics-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading">
        <div><h3>月度报告</h3><p>按项目时区聚合本月任务、回答与发布结案；线索漏斗仅在具备线索权限时展示</p></div>
        <div className="toolbar-extra">
          <label className="date-field" htmlFor="monthly-month"><span>报告月份</span><input id="monthly-month" type="month" value={month} onChange={(event) => setMonth(event.target.value)} /></label>
          <Badge tone="blue">{report?.month ?? month}</Badge>
        </div>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && <p className="knowledge-empty">正在加载月报…</p>}
      {!loading && !report && !error && <p className="knowledge-empty">暂无月报数据</p>}
      {report && !loading && <>
        <div className="stats-cards">
          <div><span>本月任务</span><strong>{report.tasks.total}</strong></div>
          <div><span>任务完成率</span><strong>{rate(report.tasks.completion_rate)}</strong></div>
          <div><span>有效回答</span><strong>{report.answers.valid_answers}</strong></div>
          <div><span>品牌提及率</span><strong>{rate(report.answers.brand_mention_rate)}</strong></div>
          <div><span>引用率</span><strong>{rate(report.answers.citation_rate)}</strong></div>
          <div><span>发布结案</span><strong>{report.published_receipts}</strong></div>
        </div>
        <p className="stats-excluded">任务：完成 {report.tasks.done} · 失败 {report.tasks.failed} · 运行中 {report.tasks.running} · 待执行 {report.tasks.pending}</p>
        <p className="stats-excluded">回答：总样本 {report.answers.total_samples} · 失败率 {rate(report.answers.failure_rate)} · 24 小时新鲜度 {rate(report.answers.fresh_24h_rate)} · 题库覆盖 {rate(report.answers.prompt_coverage)}</p>
        {report.leads ? <div className="stats-cards">
          <div><span>咨询总量</span><strong>{report.leads.total}</strong></div>
          <div><span>有效线索</span><strong>{report.leads.valid}</strong></div>
          <div><span>已联系</span><strong>{report.leads.contacted}</strong></div>
          <div><span>已报名</span><strong>{report.leads.enrolled}</strong></div>
          <div><span>线索转化率</span><strong>{rate(report.leads.conversion_rate)}</strong></div>
        </div> : <p className="stats-excluded">当前账号没有线索查看权限，月报仅展示任务与回答数据。</p>}
      </>}
    </Panel>
  </div>;
}
