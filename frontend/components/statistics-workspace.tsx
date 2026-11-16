"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { StatsEngine, StatsOverview, StatsQuestion } from "@/lib/workbench/types";

const rate = (value: number | null) => value === null ? "--" : `${(value * 100).toFixed(1)}%`;

export function StatisticsWorkspace({ mode, projectId, canRead, canExport, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canExport: boolean; onNotice: (message: string) => void;
}) {
  const [overview, setOverview] = useState<StatsOverview | null>(null);
  const [engines, setEngines] = useState<StatsEngine[]>([]);
  const [questions, setQuestions] = useState<StatsQuestion[]>([]);
  const [loadedProject, setLoadedProject] = useState("");
  const loading = mode === "live" && canRead && loadedProject !== projectId;
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([workbenchClient.statsOverview(projectId), workbenchClient.statsByEngine(projectId), workbenchClient.statsByQuestion(projectId)])
      .then(([summary, byEngine, byQuestion]) => { if (active) { setOverview(summary); setEngines(byEngine); setQuestions(byQuestion); setError(""); setLoadedProject(projectId); } })
      .catch((cause) => { if (active) { setOverview(null); setError(cause instanceof Error ? cause.message : "统计加载失败"); setLoadedProject(projectId); } });
    return () => { active = false; };
  }, [mode, projectId, canRead]);

  async function download() {
    setExporting(true);
    try { await workbenchClient.downloadStats(projectId); onNotice("统计 CSV 已下载"); }
    catch (cause) { onNotice(cause instanceof Error ? cause.message : "导出失败"); }
    finally { setExporting(false); }
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">统计看板请切换到真实接口模式查看。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有统计查看权限。</p></Panel>;
  return <div className="statistics-workspace">
    <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>监测统计</h3><p>只计算有效回答；失败、待复核和未完成单列</p></div>{canExport && <Button variant="secondary" icon="download" disabled={exporting} onClick={() => void download()}>{exporting ? "导出中…" : "导出 CSV"}</Button>}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && <p className="knowledge-empty">正在加载统计…</p>}
      {overview && !loading && <><div className="stats-cards">
        <div><span>有效回答</span><strong>{overview.valid_answers}</strong></div>
        <div><span>品牌提及率</span><strong>{rate(overview.brand_mention_rate)}</strong></div>
        <div><span>引用率</span><strong>{rate(overview.citation_rate)}</strong></div>
        <div><span>渠道数</span><strong>{overview.channel_count}</strong></div>
        <div><span>页面数</span><strong>{overview.page_count}</strong></div>
      </div><p className="stats-excluded">未计入有效回答：失败 {overview.excluded.failed} · 待复核 {overview.excluded.manual_review} · 未完成 {overview.excluded.pending_or_running}</p></>}
    </Panel>
    <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>分引擎</h3><p>同一指标口径</p></div><Badge tone="blue">{engines.length} 个</Badge></div><div className="table-scroll"><table><thead><tr><th>引擎</th><th>有效回答</th><th>品牌提及率</th><th>引用率</th></tr></thead><tbody>{engines.map((item) => <tr key={item.engine_id}><td>{item.engine_name}</td><td>{item.valid_answers}</td><td>{rate(item.brand_mention_rate)}</td><td>{rate(item.citation_rate)}</td></tr>)}</tbody></table>{!engines.length && !loading && <p className="knowledge-empty">暂无有效样本</p>}</div></Panel>
    <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>分问题</h3><p>按监测题目查看结果</p></div><Badge tone="blue">{questions.length} 题</Badge></div><div className="table-scroll"><table><thead><tr><th>题目</th><th>有效回答</th><th>品牌提及率</th><th>引用率</th></tr></thead><tbody>{questions.map((item) => <tr key={item.question_id}><td>{item.question_code} · {item.question_title}</td><td>{item.valid_answers}</td><td>{rate(item.brand_mention_rate)}</td><td>{rate(item.citation_rate)}</td></tr>)}</tbody></table>{!questions.length && !loading && <p className="knowledge-empty">暂无有效样本</p>}</div></Panel>
  </div>;
}
