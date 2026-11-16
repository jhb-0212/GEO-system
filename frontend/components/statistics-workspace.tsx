"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, Panel } from "./ui";
import { WorkTabs } from "./work-tabs";
import { workbenchClient } from "@/lib/workbench/client";
import type { EngineHealth, GeoOverview, StatsEngine, StatsOverview, StatsQuestion } from "@/lib/workbench/types";

type StatsTab = "overview" | "engines" | "questions" | "health";

function readTab(value: string | null): StatsTab {
  return value === "engines" || value === "questions" || value === "health" ? value : "overview";
}

const rate = (value: number | null) => value === null ? "--" : `${(value * 100).toFixed(1)}%`;
const money = (value: number | null) => value === null ? "--" : `¥${value.toFixed(4)}`;
const ms = (value: number | null) => value === null ? "--" : `${Math.round(value)} ms`;
const healthLabel: Record<EngineHealth["availability"], string> = {
  healthy: "正常", degraded: "部分失败", failing: "持续失败", untested: "未采样",
  no_credentials: "缺凭据", no_endpoint: "缺入口地址", disabled: "已停用",
};

export function StatisticsWorkspace({ mode, projectId, canRead, canExport, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canExport: boolean; onNotice: (message: string) => void;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = readTab(searchParams.get("stats_tab"));
  const [overview, setOverview] = useState<StatsOverview | null>(null);
  const [engines, setEngines] = useState<StatsEngine[]>([]);
  const [questions, setQuestions] = useState<StatsQuestion[]>([]);
  const [engineHealth, setEngineHealth] = useState<EngineHealth[]>([]);
  const [geo, setGeo] = useState<GeoOverview | null>(null);
  const [loadedProject, setLoadedProject] = useState("");
  const loading = mode === "live" && canRead && loadedProject !== projectId;
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([workbenchClient.statsOverview(projectId), workbenchClient.statsByEngine(projectId), workbenchClient.statsByQuestion(projectId), workbenchClient.statsEngineHealth(projectId), workbenchClient.statsGeo(projectId)])
      .then(([summary, byEngine, byQuestion, health, geoOverview]) => { if (active) { setOverview(summary); setEngines(byEngine); setQuestions(byQuestion); setEngineHealth(health); setGeo(geoOverview); setError(""); setLoadedProject(projectId); } })
      .catch((cause) => { if (active) { setOverview(null); setError(cause instanceof Error ? cause.message : "统计加载失败"); setLoadedProject(projectId); } });
    return () => { active = false; };
  }, [mode, projectId, canRead]);

  async function download() {
    setExporting(true);
    try { await workbenchClient.downloadStats(projectId); onNotice("统计 CSV 已下载"); }
    catch (cause) { onNotice(cause instanceof Error ? cause.message : "导出失败"); }
    finally { setExporting(false); }
  }

  function selectTab(tab: StatsTab) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("section", "statistics");
    if (projectId && projectId !== "all") params.set("project_id", projectId);
    if (tab === "overview") params.delete("stats_tab");
    else params.set("stats_tab", tab);
    router.push(`/workbench?${params.toString()}`, { scroll: false });
  }

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">统计看板请切换到真实接口模式查看。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有统计查看权限。</p></Panel>;
  const tabs: { id: StatsTab; label: string; count?: number }[] = [
    { id: "overview", label: "总览" },
    { id: "engines", label: "分引擎", count: engines.length },
    { id: "health", label: "引擎健康", count: engineHealth.length },
    { id: "questions", label: "分问题", count: questions.length },
  ];
  const totalTokens = engineHealth.reduce((sum, item) => sum + item.total_tokens, 0);
  const costItems = engineHealth.filter((item) => item.estimated_cost_cny !== null);
  const totalCost = costItems.length ? costItems.reduce((sum, item) => sum + (item.estimated_cost_cny ?? 0), 0) : null;
  const latencyItems = engineHealth.filter((item) => item.avg_latency_ms !== null);
  const avgLatency = latencyItems.length ? latencyItems.reduce((sum, item) => sum + (item.avg_latency_ms ?? 0), 0) / latencyItems.length : null;
  const attentionCount = engineHealth.filter((item) => ["failing", "degraded", "no_credentials", "no_endpoint"].includes(item.availability)).length;
  const toneFor = (availability: EngineHealth["availability"]) => availability === "healthy" ? "green" : availability === "untested" ? "slate" : availability === "degraded" ? "amber" : "red";
  return <div className="statistics-workspace">
    <WorkTabs items={tabs} active={activeTab} onChange={selectTab} ariaLabel="统计看板视图" extra={canExport ? <Button variant="secondary" icon="download" disabled={exporting} onClick={() => void download()}>{exporting ? "导出中…" : "导出 CSV"}</Button> : undefined}/>
    {activeTab === "overview" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>监测统计</h3><p>只计算有效回答；失败、待复核和未完成单列</p></div></div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && <p className="knowledge-empty">正在加载统计…</p>}
      {overview && !loading && <><div className="stats-cards">
        <div><span>有效回答</span><strong>{overview.valid_answers}</strong></div>
        <div><span>品牌提及率</span><strong>{rate(overview.brand_mention_rate)}</strong></div>
        <div><span>引用率</span><strong>{rate(overview.citation_rate)}</strong></div>
        <div><span>渠道数</span><strong>{overview.channel_count}</strong></div>
        <div><span>页面数</span><strong>{overview.page_count}</strong></div>
      </div>{geo && <><div className="stats-cards">
        <div><span>竞品份额 SOV</span><strong>{rate(geo.sov)}</strong></div>
        <div><span>品牌正向率</span><strong>{rate(geo.sentiment.positive_rate)}</strong></div>
        <div><span>平均提及位次</span><strong>{geo.brand_position.average_rank ?? "--"}</strong></div>
        <div><span>首位提及率</span><strong>{rate(geo.brand_position.top1_rate)}</strong></div>
      </div><p className="stats-excluded">情感（仅品牌句）：正 {geo.sentiment.positive} · 中 {geo.sentiment.neutral} · 负 {geo.sentiment.negative} · 未提及 {geo.sentiment.not_mentioned}；位次样本 {geo.brand_position.sample_count}</p></>}<p className="stats-excluded">未计入有效回答：失败 {overview.excluded.failed} · 待复核 {overview.excluded.manual_review} · 未完成 {overview.excluded.pending_or_running}</p></>}
      {!overview && !loading && !error && <p className="knowledge-empty">暂无统计数据</p>}
    </Panel>}
    {activeTab === "engines" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>分引擎</h3><p>同一指标口径</p></div><Badge tone="blue">{engines.length} 个</Badge></div><div className="table-scroll"><table><thead><tr><th>引擎</th><th>有效回答</th><th>品牌提及率</th><th>引用率</th></tr></thead><tbody>{engines.map((item) => <tr key={item.engine_id}><td>{item.engine_name}</td><td>{item.valid_answers}</td><td>{rate(item.brand_mention_rate)}</td><td>{rate(item.citation_rate)}</td></tr>)}</tbody></table>{loading && <p className="knowledge-empty">正在加载统计…</p>}{!engines.length && !loading && <p className="knowledge-empty">暂无有效样本</p>}</div></Panel>}
    {activeTab === "health" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>引擎健康与成本</h3><p>入口级样本、失败率、延迟、token 与估算费用；缺凭据/未采样单独标记</p></div><Badge tone={attentionCount ? "amber" : "green"}>{attentionCount ? `${attentionCount} 个需处理` : "全部正常"}</Badge></div>
      <div className="stats-cards">
        <div><span>入口数</span><strong>{engineHealth.length}</strong></div>
        <div><span>总样本</span><strong>{engineHealth.reduce((sum, item) => sum + item.sample_count, 0)}</strong></div>
        <div><span>平均延迟</span><strong>{ms(avgLatency)}</strong></div>
        <div><span>总 token</span><strong>{totalTokens.toLocaleString()}</strong></div>
        <div><span>估算费用</span><strong>{money(totalCost)}</strong></div>
      </div>
      <div className="table-scroll"><table><thead><tr><th>引擎 / 入口</th><th>可用性</th><th>任务</th><th>样本</th><th>失败率</th><th>平均延迟</th><th>token</th><th>费用</th><th>最近采样</th></tr></thead><tbody>
        {engineHealth.map((item) => <tr key={item.entry_id}>
          <td><strong>{item.engine_name}</strong><br/><span className="muted">{item.entry_name} · {item.model_name ?? item.protocol}</span></td>
          <td><Badge tone={toneFor(item.availability)}>{healthLabel[item.availability]}</Badge>{!item.price_configured && item.estimated_cost_cny === null && <p className="muted">未配置单价</p>}</td>
          <td>{item.task_count}</td><td>{item.sample_count}</td><td>{rate(item.failure_rate)}</td><td>{ms(item.avg_latency_ms)}</td><td>{item.total_tokens.toLocaleString()}</td><td>{money(item.estimated_cost_cny)}</td><td>{item.last_sampled_at ? new Date(item.last_sampled_at).toLocaleString("zh-CN") : "未采样"}</td>
        </tr>)}
      </tbody></table>{loading && <p className="knowledge-empty">正在加载统计…</p>}{!engineHealth.length && !loading && <p className="knowledge-empty">暂无引擎入口</p>}</div>
    </Panel>}
    {activeTab === "questions" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>分问题</h3><p>按监测题目查看结果</p></div><Badge tone="blue">{questions.length} 题</Badge></div><div className="table-scroll"><table><thead><tr><th>题目</th><th>有效回答</th><th>品牌提及率</th><th>引用率</th></tr></thead><tbody>{questions.map((item) => <tr key={item.question_id}><td>{item.question_code} · {item.question_title}</td><td>{item.valid_answers}</td><td>{rate(item.brand_mention_rate)}</td><td>{rate(item.citation_rate)}</td></tr>)}</tbody></table>{loading && <p className="knowledge-empty">正在加载统计…</p>}{!questions.length && !loading && <p className="knowledge-empty">暂无有效样本</p>}</div></Panel>}
  </div>;
}
