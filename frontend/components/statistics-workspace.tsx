"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, Panel } from "./ui";
import { WorkTabs } from "./work-tabs";
import { workbenchClient } from "@/lib/workbench/client";
import type { EngineHealth, GeoOverview, StatsEngine, StatsOverview, StatsPublishVisibility, StatsQuestion, StatsSource } from "@/lib/workbench/types";

type StatsTab = "overview" | "engines" | "questions" | "health" | "sources" | "visibility";

function readTab(value: string | null): StatsTab {
  return value === "engines" || value === "questions" || value === "health" || value === "sources" || value === "visibility" ? value : "overview";
}

const rate = (value: number | null) => value === null ? "--" : `${(value * 100).toFixed(1)}%`;
// 信源分布按引用条数取前 N 个域名；徽标数字是"显示数"，不是域名总数，文案里要说清
const SOURCES_LIMIT = 50;
const VISIBILITY_LIMIT = 50;
// 单次检测最多跑 20 条回执：每条一次外部调用，后端上限 50
const CHECK_LIMIT = 20;
const money = (value: number | null) => value === null ? "--" : `¥${value.toFixed(4)}`;
const ms = (value: number | null) => value === null ? "--" : `${Math.round(value)} ms`;
const healthLabel: Record<EngineHealth["availability"], string> = {
  healthy: "正常", degraded: "部分失败", failing: "持续失败", untested: "未采样",
  no_credentials: "缺凭据", no_endpoint: "缺入口地址", disabled: "已停用",
};

export function StatisticsWorkspace({ mode, projectId, canRead, canExport, canCheckVisibility, onNotice }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canExport: boolean; canCheckVisibility: boolean; onNotice: (message: string) => void;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = readTab(searchParams.get("stats_tab"));
  const [overview, setOverview] = useState<StatsOverview | null>(null);
  const [engines, setEngines] = useState<StatsEngine[]>([]);
  const [questions, setQuestions] = useState<StatsQuestion[]>([]);
  const [engineHealth, setEngineHealth] = useState<EngineHealth[]>([]);
  const [geo, setGeo] = useState<GeoOverview | null>(null);
  const [sources, setSources] = useState<StatsSource[]>([]);
  const [sourcesError, setSourcesError] = useState("");
  const [visibility, setVisibility] = useState<StatsPublishVisibility[]>([]);
  const [visibilityError, setVisibilityError] = useState("");
  const [loadedProject, setLoadedProject] = useState("");
  const loading = mode === "live" && canRead && loadedProject !== projectId;
  const [exporting, setExporting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    Promise.all([workbenchClient.statsOverview(projectId), workbenchClient.statsByEngine(projectId), workbenchClient.statsByQuestion(projectId), workbenchClient.statsEngineHealth(projectId), workbenchClient.statsGeo(projectId)])
      .then(([summary, byEngine, byQuestion, health, geoOverview]) => { if (active) { setOverview(summary); setEngines(byEngine); setQuestions(byQuestion); setEngineHealth(health); setGeo(geoOverview); setError(""); setLoadedProject(projectId); } })
      .catch((cause) => { if (active) { setOverview(null); setError(cause instanceof Error ? cause.message : "统计加载失败"); setLoadedProject(projectId); } });
    // 信源分布单独请求、单独降级：新接口在旧后端/网关未放行时，不应把整页统计拖挂
    workbenchClient.statsSources(projectId, SOURCES_LIMIT)
      .then((rows) => { if (active) { setSources(rows); setSourcesError(""); } })
      .catch((cause) => { if (active) { setSources([]); setSourcesError(cause instanceof Error ? cause.message : "信源分布加载失败"); } });
    // 发布可见性同样单独请求：它依赖外部搜索接口，失败只降级本面板
    workbenchClient.statsPublishVisibility(projectId, VISIBILITY_LIMIT)
      .then((rows) => { if (active) { setVisibility(rows); setVisibilityError(""); } })
      .catch((cause) => { if (active) { setVisibility([]); setVisibilityError(cause instanceof Error ? cause.message : "发布可见性加载失败"); } });
    return () => { active = false; };
  }, [mode, projectId, canRead]);

  async function download() {
    setExporting(true);
    try { await workbenchClient.downloadStats(projectId); onNotice("统计 CSV 已下载"); }
    catch (cause) { onNotice(cause instanceof Error ? cause.message : "导出失败"); }
    finally { setExporting(false); }
  }

  // 手动触发一次检测：会真实调用外部搜索接口并写库，后端有 60 秒节流
  async function runVisibilityCheck() {
    setChecking(true);
    try {
      const summary = await workbenchClient.runPublishVisibilityCheck(projectId, CHECK_LIMIT);
      onNotice(`检测完成：命中 ${summary.matched}、未收录 ${summary.unmatched}、查询失败 ${summary.failed}`);
      const rows = await workbenchClient.statsPublishVisibility(projectId, VISIBILITY_LIMIT);
      setVisibility(rows); setVisibilityError("");
    } catch (cause) {
      onNotice(cause instanceof Error ? cause.message : "检测失败");
    } finally { setChecking(false); }
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
    { id: "sources", label: "信源分布", count: sources.length },
    { id: "visibility", label: "发布可见性", count: visibility.length },
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
        <div><span title="引用里去重后的 URL 数，不是 public_pages 登记页数">被引页面数</span><strong>{overview.page_count}</strong></div>
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
    {activeTab === "sources" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>信源分布</h3><p>AI 从哪些域名取证；「渠道被引」只统计命中发布回执的真实 URL。按引用条数排序，最多显示 {SOURCES_LIMIT} 个域名</p></div><Badge tone="blue">{sources.length} 个域名</Badge></div>
      <div className="table-scroll"><table><thead><tr><th>域名</th><th>引用条数</th><th>涉及样本</th><th>自有域名</th><th>渠道被引</th><th>最近采样</th></tr></thead><tbody>
        {sources.map((item) => <tr key={item.domain}>
          <td><strong>{item.domain || "未知域名"}</strong></td>
          <td>{item.citations}</td>
          <td>{item.samples}</td>
          <td>{item.brand_related ? <Badge tone="green">自有</Badge> : "—"}</td>
          <td>{item.channel_citations ? <Badge tone="blue">{item.channel_citations} 条</Badge> : <span className="muted">未命中发布回执</span>}</td>
          <td>{item.last_sampled_at ? new Date(item.last_sampled_at).toLocaleString("zh-CN") : "—"}</td>
        </tr>)}
      </tbody></table>{loading && <p className="knowledge-empty">正在加载统计…</p>}{!sources.length && !loading && <p className="knowledge-empty">{sourcesError ? `信源分布暂不可用：${sourcesError}` : "暂无可归因的引用"}</p>}</div>
    </Panel>}
    {activeTab === "visibility" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>发布可见性</h3><p>每条发布回执的页面能不能被搜索引擎检索到；命中只认回执 URL 精确相等，不参与渠道归因。显示每条回执最近一次检测，最多 {VISIBILITY_LIMIT} 条</p></div><div className="toolbar-extra"><Badge tone="blue">{visibility.length} 条回执</Badge>{canCheckVisibility && <Button variant="secondary" disabled={checking || loading || !projectId || projectId === "all"} onClick={() => void runVisibilityCheck()}>{checking ? "检测中…" : `立即检测（${CHECK_LIMIT} 条）`}</Button>}</div></div>
      <div className="table-scroll"><table><thead><tr><th>回执页面</th><th>结果</th><th>检测时间</th><th>查询词 / 站点</th></tr></thead><tbody>
        {visibility.map((item) => <tr key={item.receipt_id}>
          <td><a href={item.published_url} target="_blank" rel="noreferrer">{item.published_url}</a></td>
          <td>{item.error_code ? <><Badge tone="amber">查询失败</Badge><p className="muted">{item.error_code}</p></> : item.matched
            ? <><Badge tone="green">已收录{item.position ? ` · 结果第 ${item.position} 条` : ""}</Badge>{item.matched_url && <p className="muted">{item.matched_url}</p>}</>
            : <Badge tone="slate">未收录</Badge>}</td>
          <td>{item.checked_at ? new Date(item.checked_at).toLocaleString("zh-CN") : "—"}</td>
          <td><span className="muted">{item.query}</span>{item.site ? <p className="muted">site: {item.site} · 返回 {item.result_count} 条</p> : null}</td>
        </tr>)}
      </tbody></table>{!visibility.length && !loading && <p className="knowledge-empty">{visibilityError ? `发布可见性暂不可用：${visibilityError}` : "还没有检测记录，先在命令行跑一次检测脚本"}</p>}</div>
    </Panel>}
  </div>;
}