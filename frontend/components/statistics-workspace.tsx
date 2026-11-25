"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, Icon, Panel } from "./ui";
import { WorkTabs } from "./work-tabs";
import { BrandSearchPanel, CompetitorSourcesPanel, SellingPointsPanel } from "./workbench/gap-metrics";
import { ColumnCompare, DonutChart, HorizontalBars, RateBars, StackedBar, VizEmpty } from "./stats-visuals";
import type { BarItem, ColumnItem, DonutSegment, StackSegment } from "./stats-visuals";
import { workbenchClient } from "@/lib/workbench/client";
import type { AcceptanceContract, AdaptationReport, ContentConsistencyReport, ContentFormatReport, ContentFreshness, DistributionCandidates, EngineHealth, GeoOverview, MonitoringRound, PageVisibilityReport, SourceCoverage, SourceTiers, SourceMatrix, StatsAnswerKindOverview, StatsEngine, StatsEntry, StatsOverview, StatsPublishVisibility, StatsQuestion, StatsSource } from "@/lib/workbench/types";

type StatsTab = "overview" | "engines" | "entries" | "questions" | "health" | "sources" | "visibility" | "consistency" | "formats" | "adaptation" | "selling_points" | "brand_search" | "competitor_sources";

type StatsTabGroupId = "overview" | "entry" | "source" | "content";

interface StatsTabGroup {
  id: StatsTabGroupId;
  label: string;
  tabs: readonly StatsTab[];
}

/** 13 个统计页按问题归组，避免一长排同权页签。 */
const STATS_TAB_GROUPS: readonly StatsTabGroup[] = [
  { id: "overview", label: "总览", tabs: ["overview"] },
  { id: "entry", label: "入口与引擎", tabs: ["engines", "entries", "health"] },
  { id: "source", label: "信源与搜索", tabs: ["sources", "visibility", "brand_search", "competitor_sources"] },
  { id: "content", label: "内容与一致性", tabs: ["questions", "formats", "adaptation", "selling_points", "consistency"] },
];

function readTab(value: string | null): StatsTab {
  return value === "engines" || value === "entries" || value === "questions" || value === "health" || value === "sources" || value === "visibility" || value === "consistency" || value === "formats" || value === "adaptation" || value === "selling_points" || value === "brand_search" || value === "competitor_sources" ? value : "overview";
}

const rate = (value: number | null) => value === null ? "--" : `${(value * 100).toFixed(1)}%`;
const citationRate = (observable: number | null | undefined, value: number | null) =>
  observable === 0 ? "不可观测" : rate(value);
const signedCount = (value: number) => value === 0 ? "持平" : `${value > 0 ? "+" : ""}${value}`;
const signedRate = (value: number | null) => value === null ? "--" : `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)} 个百分点`;
const rateDiff = (current: number | null, base: number | null) => current === null || base === null ? null : current - base;
// 信源分布按引用条数取前 N 个域名；徽标数字是"显示数"，不是域名总数，文案里要说清
const SOURCES_LIMIT = 50;
const VISIBILITY_LIMIT = 50;
// 单次检测最多跑 20 条回执：每条一次外部调用，后端上限 50
const CHECK_LIMIT = 20;
const money = (value: number | null) => value === null ? "--" : `¥${value.toFixed(4)}`;
const ms = (value: number | null) => value === null ? "--" : `${Math.round(value)} ms`;
const failureCodeLabels: Record<string, string> = {
  login_blocked: "登录阻断", timeout: "超时", access_blocked: "访问受限",
  captcha: "验证码", rate_limited: "限流", other: "其他", unknown: "未标原因",
};
const healthLabel: Record<EngineHealth["availability"], string> = {
  healthy: "正常", degraded: "部分失败", failing: "持续失败", untested: "未采样",
  no_credentials: "缺凭据", no_endpoint: "缺入口地址", disabled: "已停用",
};

export function StatisticsWorkspace({ mode, projectId, canRead, canManage, canExport, canFreeze, canCheckVisibility, onNotice, onNavigate }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean; canManage: boolean; canExport: boolean; canFreeze: boolean; canCheckVisibility: boolean; onNotice: (message: string) => void; onNavigate: (section: "channels") => void;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = readTab(searchParams.get("stats_tab"));
  const [answerKind, setAnswerKind] = useState<"split" | "answer" | "search_result">("split");
  const [questionType, setQuestionType] = useState<"general" | "brand" | "all">("general");
  const [roundId, setRoundId] = useState("all");
  const [rounds, setRounds] = useState<MonitoringRound[]>([]);
  const [overview, setOverview] = useState<StatsOverview | null>(null);
  const [overviewByKind, setOverviewByKind] = useState<StatsAnswerKindOverview[]>([]);
  const [baseline, setBaseline] = useState<StatsOverview | null>(null);
  const [baselineKey, setBaselineKey] = useState("");
  const [engines, setEngines] = useState<StatsEngine[]>([]);
  const [entries, setEntries] = useState<StatsEntry[]>([]);
  const [entryError, setEntryError] = useState("");
  const [questions, setQuestions] = useState<StatsQuestion[]>([]);
  const [engineHealth, setEngineHealth] = useState<EngineHealth[]>([]);
  const [geo, setGeo] = useState<GeoOverview | null>(null);
  const [sources, setSources] = useState<StatsSource[]>([]);
  const [sourcesError, setSourcesError] = useState("");
  const [coverage, setCoverage] = useState<SourceCoverage | null>(null);
  const [coverageError, setCoverageError] = useState("");
  const [tiers, setTiers] = useState<SourceTiers | null>(null);
  const [tiersError, setTiersError] = useState("");
  const [matrix, setMatrix] = useState<SourceMatrix | null>(null);
  const [matrixError, setMatrixError] = useState("");
  const [visibility, setVisibility] = useState<StatsPublishVisibility[]>([]);
  const [visibilityError, setVisibilityError] = useState("");
  const [contract, setContract] = useState<AcceptanceContract | null>(null);
  const [contractError, setContractError] = useState("");
  const [freshness, setFreshness] = useState<ContentFreshness | null>(null);
  const [freshnessError, setFreshnessError] = useState("");
  const [consistency, setConsistency] = useState<ContentConsistencyReport | null>(null);
  const [consistencyError, setConsistencyError] = useState("");
  const [formats, setFormats] = useState<ContentFormatReport | null>(null);
  const [formatsError, setFormatsError] = useState("");
  const [adaptation, setAdaptation] = useState<AdaptationReport | null>(null);
  const [adaptationError, setAdaptationError] = useState("");
  const [adaptationAnswers, setAdaptationAnswers] = useState<Record<string, string>>({});
  const [adaptationNote, setAdaptationNote] = useState("");
  const [adaptationSaving, setAdaptationSaving] = useState(false);
  const [pageStates, setPageStates] = useState<PageVisibilityReport | null>(null);
  const [pageStatesError, setPageStatesError] = useState("");
  const [candidates, setCandidates] = useState<DistributionCandidates | null>(null);
  const [candidatesError, setCandidatesError] = useState("");
  const [loadedKey, setLoadedKey] = useState("");
  const loading = mode === "live" && canRead && loadedKey !== `${projectId}:${roundId}:${answerKind}:${questionType}`;
  const [exporting, setExporting] = useState(false);
  const [roundBusy, setRoundBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.rounds(projectId, 1, 100)
      .then(({ data }) => { if (active) setRounds(data); })
      .catch(() => { if (active) setRounds([]); });
    return () => { active = false; };
  }, [mode, projectId, canRead]);

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    const kind = answerKind === "split" ? undefined : answerKind;
    const qtype = questionType;
    const selectedRoundId = roundId === "all" ? undefined : roundId;
    const baselineId = rounds.find((item) => item.is_baseline)?.id;
    Promise.all([
      workbenchClient.statsOverview(projectId, kind, selectedRoundId, qtype),
      workbenchClient.statsOverviewByAnswerKind(projectId, selectedRoundId, qtype),
      workbenchClient.statsByEngine(projectId, kind, selectedRoundId, qtype),
      workbenchClient.statsByQuestion(projectId, kind, selectedRoundId, qtype),
      workbenchClient.statsEngineHealth(projectId, selectedRoundId),
      workbenchClient.statsGeo(projectId, kind, selectedRoundId, qtype),
    ])
      .then(([summary, byKind, byEngine, byQuestion, health, geoOverview]) => {
        if (!active) return;
        setOverview(summary); setOverviewByKind(byKind); setEngines(byEngine); setQuestions(byQuestion); setEngineHealth(health); setGeo(geoOverview);
        setError(""); setLoadedKey(`${projectId}:${roundId}:${answerKind}:${questionType}`);
      })
      .catch((cause) => {
        if (!active) return;
        setOverview(null); setOverviewByKind([]); setError(cause instanceof Error ? cause.message : "统计加载失败");
        setLoadedKey(`${projectId}:${roundId}:${answerKind}:${questionType}`);
      });
    // 选中非基线轮次时并行读取基线总览，只用于展示差值，不阻塞主统计
    if (selectedRoundId && baselineId && selectedRoundId !== baselineId) {
      const expectedBaselineKey = `${projectId}:${roundId}:${answerKind}:${questionType}:${baselineId}`;
      workbenchClient.statsOverview(projectId, kind, baselineId, qtype)
        .then((base) => { if (active) { setBaseline(base); setBaselineKey(expectedBaselineKey); } })
        .catch(() => { if (active) setBaselineKey(""); });
    }
    // 入口对照单独请求、单独降级：网页端与手机客户端必须分行，接口缺失时不清空其他统计
    workbenchClient.statsByEntry(projectId, kind, selectedRoundId, qtype)
      .then((rows) => { if (active) { setEntries(rows); setEntryError(""); } })
      .catch((cause) => { if (active) { setEntries([]); setEntryError(cause instanceof Error ? cause.message : "入口对照加载失败"); } });
    // 信源分布单独请求、单独降级：新接口在旧后端/网关未放行时，不应把整页统计拖挂
    workbenchClient.statsSources(projectId, SOURCES_LIMIT, selectedRoundId, qtype)      .then((rows) => { if (active) { setSources(rows); setSourcesError(""); } })
      .catch((cause) => { if (active) { setSources([]); setSourcesError(cause instanceof Error ? cause.message : "信源分布加载失败"); } });
    // M1 引用源覆盖：与信源分布同源但口径不同（Top N + 覆盖/缺口），单独降级
    workbenchClient.statsSourceCoverage(projectId, 90, SOURCES_LIMIT)
      .then((rows) => { if (active) { setCoverage(rows); setCoverageError(""); } })
      .catch((cause) => { if (active) { setCoverage(null); setCoverageError(cause instanceof Error ? cause.message : "引用源覆盖加载失败"); } });
    // 信源分级 + 多源交叉验证：同样单独降级，口径与覆盖卡一致（只算已复核引用）
    workbenchClient.statsSourceTiers(projectId, 90, SOURCES_LIMIT)
      .then((rows) => { if (active) { setTiers(rows); setTiersError(""); } })
      .catch((cause) => { if (active) { setTiers(null); setTiersError(cause instanceof Error ? cause.message : "信源分级加载失败"); } });
    // 信源 × 形态矩阵：单独降级，形态分布只作事实展示，不转成投放建议
    workbenchClient.statsSourceMatrix(projectId, 90, SOURCES_LIMIT)
      .then((rows) => { if (active) { setMatrix(rows); setMatrixError(""); } })
      .catch((cause) => { if (active) { setMatrix(null); setMatrixError(cause instanceof Error ? cause.message : "形态矩阵加载失败"); } });
    // 验收契约与内容新鲜度：各自独立降级，一个接口挂了不拖整页
    workbenchClient.statsAcceptanceContract(projectId, 90, 30)
      .then((rows) => { if (active) { setContract(rows); setContractError(""); } })
      .catch((cause) => { if (active) { setContract(null); setContractError(cause instanceof Error ? cause.message : "验收契约加载失败"); } });
    workbenchClient.statsContentFreshness(projectId, 18, 100)
      .then((rows) => { if (active) { setFreshness(rows); setFreshnessError(""); } })
      .catch((cause) => { if (active) { setFreshness(null); setFreshnessError(cause instanceof Error ? cause.message : "内容新鲜度加载失败"); } });
    workbenchClient.statsContentConsistency(projectId, 50)
      .then((rows) => { if (active) { setConsistency(rows); setConsistencyError(""); } })
      .catch((cause) => { if (active) { setConsistency(null); setConsistencyError(cause instanceof Error ? cause.message : "一致性检查加载失败"); } });
    workbenchClient.statsContentFormats(projectId)
      .then((rows) => { if (active) { setFormats(rows); setFormatsError(""); } })
      .catch((cause) => { if (active) { setFormats(null); setFormatsError(cause instanceof Error ? cause.message : "内容形式加载失败"); } });
    workbenchClient.statsAdaptation(projectId)
      .then((rows) => {
        if (!active) return;
        setAdaptation(rows); setAdaptationError("");
        setAdaptationAnswers(Object.fromEntries(rows.answers.map((item) => [item.key, item.answer])));
        setAdaptationNote(rows.note ?? "");
      })
      .catch((cause) => { if (active) { setAdaptation(null); setAdaptationError(cause instanceof Error ? cause.message : "行业适配加载失败"); } });
    // 页面三态与分发候选：新口径，独立降级，不拖整页
    workbenchClient.statsPageVisibility(projectId, 50)
      .then((rows) => { if (active) { setPageStates(rows); setPageStatesError(""); } })
      .catch((cause) => { if (active) { setPageStates(null); setPageStatesError(cause instanceof Error ? cause.message : "页面三态加载失败"); } });
    workbenchClient.statsDistributionCandidates(projectId, 10)
      .then((rows) => { if (active) { setCandidates(rows); setCandidatesError(""); } })
      .catch((cause) => { if (active) { setCandidates(null); setCandidatesError(cause instanceof Error ? cause.message : "分发候选加载失败"); } });
    // 发布可见性同样单独请求：它依赖外部搜索接口，失败只降级本面板
    workbenchClient.statsPublishVisibility(projectId, VISIBILITY_LIMIT)
      .then((rows) => { if (active) { setVisibility(rows); setVisibilityError(""); } })
      .catch((cause) => { if (active) { setVisibility([]); setVisibilityError(cause instanceof Error ? cause.message : "发布可见性加载失败"); } });
    return () => { active = false; };
  }, [mode, projectId, canRead, answerKind, questionType, roundId, rounds]);

  async function download() {
    setExporting(true);
    try {
      const kind = answerKind === "split" ? undefined : answerKind;
      const qtype = questionType;
      await workbenchClient.downloadStats(projectId, kind, roundId === "all" ? undefined : roundId, qtype);
      onNotice("统计 CSV 已下载");
    }
    catch (cause) { onNotice(cause instanceof Error ? cause.message : "导出失败"); }
    finally { setExporting(false); }
  }

  async function startSelectedRound() {
    if (roundId === "all") return;
    setRoundBusy(true);
    try {
      const updated = await workbenchClient.startRound(projectId, roundId);
      setRounds((current) => current.map((item) => item.id === roundId ? updated : item));
      onNotice("本轮已开始");
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "开始本轮失败"); }
    finally { setRoundBusy(false); }
  }

  async function completeSelectedRound() {
    if (roundId === "all") return;
    setRoundBusy(true);
    try {
      const result = await workbenchClient.completeRound(projectId, roundId);
      setRounds((current) => current.map((item) => item.id === roundId ? result.round : item));
      onNotice(`本轮已完成，统计快照 ${result.snapshot_hash.slice(0, 12)}… 已冻结`);
    } catch (cause) { onNotice(cause instanceof Error ? cause.message : "完成本轮失败"); }
    finally { setRoundBusy(false); }
  }

  async function saveAdaptation() {
    setAdaptationSaving(true);
    try {
      const result = await workbenchClient.saveAdaptation(projectId, adaptationAnswers, adaptationNote.trim() || null);
      setAdaptation(result); setAdaptationError("");
      onNotice(`行业适配已保存：${result.verdict_label}`);
    } catch (cause) {
      setAdaptationError(cause instanceof Error ? cause.message : "行业适配保存失败");
    } finally { setAdaptationSaving(false); }
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
    { id: "engines", label: "全入口合计", count: engines.length },
    { id: "entries", label: "入口对照", count: entries.length },
    { id: "health", label: "引擎健康", count: engineHealth.length },
    { id: "sources", label: "信源分布", count: sources.length },
    { id: "visibility", label: "发布可见性", count: visibility.length },
    { id: "formats", label: "内容形式", count: formats?.summary.master_with_format },
    { id: "adaptation", label: "行业适配" },
    { id: "selling_points", label: "卖点完整" },
    { id: "brand_search", label: "品牌搜索" },
    { id: "competitor_sources", label: "竞品信源" },
    { id: "consistency", label: "一致性", count: consistency ? consistency.summary.fact_conflicts + consistency.summary.stale_derivations + consistency.summary.channel_anomalies : undefined },
    { id: "questions", label: "分问题", count: questions.length },
  ];
  const totalTokens = engineHealth.reduce((sum, item) => sum + item.total_tokens, 0);
  const costItems = engineHealth.filter((item) => item.estimated_cost_cny !== null);
  const totalCost = costItems.length ? costItems.reduce((sum, item) => sum + (item.estimated_cost_cny ?? 0), 0) : null;
  const latencyItems = engineHealth.filter((item) => item.avg_latency_ms !== null);
  const avgLatency = latencyItems.length ? latencyItems.reduce((sum, item) => sum + (item.avg_latency_ms ?? 0), 0) / latencyItems.length : null;
  const attentionCount = engineHealth.filter((item) => ["failing", "degraded", "no_credentials", "no_endpoint"].includes(item.availability)).length;
  const toneFor = (availability: EngineHealth["availability"]) => availability === "healthy" ? "green" : availability === "untested" ? "slate" : availability === "degraded" ? "amber" : "red";
  const selectedRound = rounds.find((item) => item.id === roundId);
  const baselineRound = rounds.find((item) => item.is_baseline);
  const currentBaselineKey = `${projectId}:${roundId}:${answerKind}:${questionType}:${baselineRound?.id ?? ""}`;
  const baselineVisible = Boolean(overview && baseline && baselineKey === currentBaselineKey && roundId !== "all" && selectedRound?.id !== baselineRound?.id);
  const visibleKindRows = answerKind === "split"
    ? overviewByKind
    : overviewByKind.filter((item) => item.answer_kind === answerKind);
  const sampleTotal = overview
    ? overview.valid_answers + overview.excluded.failed + overview.excluded.manual_review + overview.excluded.no_answer_surface + overview.excluded.pending_or_running
    : 0;
  const answerKindColumns: ColumnItem[] = visibleKindRows.map((row) => ({
    label: row.answer_kind === "answer" ? "生成回答" : "检索结果",
    value: row.valid_answers,
    note: `提及 ${rate(row.brand_mention_rate)} · 引用 ${citationRate(row.citation_observable_answers, row.citation_rate)}`,
    tone: row.answer_kind === "answer" ? "blue" : "teal",
  }));
  const sentimentSegments: StackSegment[] = geo ? [
    { label: "正面", value: geo.sentiment.positive, tone: "teal" },
    { label: "中性", value: geo.sentiment.neutral, tone: "slate" },
    { label: "负面", value: geo.sentiment.negative, tone: "red" },
  ] : [];
  // M2 样本份额：品牌与竞品在同一把尺子上，分母是「提到品牌或任一竞品的去重样本」。
  const sovBars: BarItem[] = (geo?.sov_detail?.entities ?? [])
    .map((item) => ({
      label: item.kind === "brand" ? `${item.entity}（本品牌）` : item.entity,
      value: (item.share ?? 0) * 100,
      display: rate(item.share ?? null),
      hint: `${item.mentioned_samples} / ${geo?.sov_detail?.denominator_samples ?? 0} 条样本`,
      tone: item.kind === "brand" ? "blue" as const : "slate" as const,
    }))
    .sort((left, right) => right.value - left.value);
  const sourceBars: BarItem[] = sources.slice(0, 10).map((item) => ({
    label: item.domain || "未知域名",
    value: item.citations,
    display: `${item.citations} 条`,
    hint: `${item.samples} 样本 · 渠道被引 ${item.channel_citations}`,
    tone: "blue",
  }));
  const questionBars: BarItem[] = [...questions]
    .sort((left, right) => (right.brand_mention_rate ?? -1) - (left.brand_mention_rate ?? -1))
    .map((item) => ({
      label: `${item.question_code} · ${item.question_title}`,
      value: item.brand_mention_rate ?? 0,
      display: rate(item.brand_mention_rate),
      hint: `${item.brand_mentioned_answers} / ${item.valid_answers} 条有效回答 · 引用 ${citationRate(item.citation_observable_answers, item.citation_rate)}`,
      tone: (item.brand_mention_rate ?? 0) > 0 ? "blue" : "slate",
    }));
  const visibilityMatched = visibility.filter((item) => !item.error_code && item.matched).length;
  const visibilityFailed = visibility.filter((item) => Boolean(item.error_code)).length;
  const visibilityUnmatched = Math.max(0, visibility.length - visibilityMatched - visibilityFailed);
  const visibilitySegments: DonutSegment[] = [
    { label: "已收录", value: visibilityMatched, tone: "teal" },
    { label: "未收录", value: visibilityUnmatched, tone: "slate" },
    { label: "查询失败", value: visibilityFailed, tone: "red" },
  ];
  const availabilitySegments: DonutSegment[] = [
    { label: "正常", value: engineHealth.filter((item) => item.availability === "healthy").length, tone: "teal" },
    { label: "部分失败", value: engineHealth.filter((item) => item.availability === "degraded").length, tone: "amber" },
    { label: "持续失败", value: engineHealth.filter((item) => item.availability === "failing").length, tone: "red" },
    { label: "缺凭据", value: engineHealth.filter((item) => item.availability === "no_credentials").length, tone: "amber" },
    { label: "缺入口", value: engineHealth.filter((item) => item.availability === "no_endpoint").length, tone: "red" },
    { label: "未采样", value: engineHealth.filter((item) => item.availability === "untested").length, tone: "slate" },
    { label: "已停用", value: engineHealth.filter((item) => item.availability === "disabled").length, tone: "slate" },
  ];
  const failureRateBars: BarItem[] = engineHealth
    .filter((item) => item.sample_count > 0 || (item.failure_rate ?? 0) > 0)
    .map((item) => ({
      label: `${item.engine_name} · ${item.entry_name}`,
      value: item.failure_rate ?? 0,
      display: rate(item.failure_rate),
      hint: `${item.sample_count} 样本 · ${healthLabel[item.availability]}`,
      tone: (item.failure_rate ?? 0) > 0 ? "red" : "teal",
    }));
  const latencyBars: BarItem[] = engineHealth
    .filter((item) => item.avg_latency_ms !== null)
    .sort((left, right) => (right.avg_latency_ms ?? 0) - (left.avg_latency_ms ?? 0))
    .map((item) => ({
      label: `${item.engine_name} · ${item.entry_name}`,
      value: item.avg_latency_ms ?? 0,
      display: ms(item.avg_latency_ms),
      hint: `${item.sample_count} 样本 · 失败率 ${rate(item.failure_rate)}`,
      tone: "blue",
    }));
  const activeStatsGroup = STATS_TAB_GROUPS.find((group) => group.tabs.includes(activeTab)) ?? STATS_TAB_GROUPS[0];
  const activeGroupTabs = activeStatsGroup.tabs
    .map((id) => tabs.find((tab) => tab.id === id))
    .filter((tab): tab is { id: StatsTab; label: string; count?: number } => Boolean(tab));
  const statsToolbar = <div className="stats-toolbar">
    <label className="filter-select" htmlFor="stats-round-select">
      <span>监测轮次</span><Icon name="calendar" size={15}/>
      <select id="stats-round-select" aria-label="监测轮次" value={roundId} onChange={(event) => setRoundId(event.target.value)}>
        <option value="all">全部轮次</option>
        {rounds.map((item) => <option key={item.id} value={item.id}>{item.name}{item.is_baseline ? "（基线）" : ""}</option>)}
      </select><Icon name="chevronDown" size={14}/>
    </label>
    <label className="filter-select" htmlFor="stats-question-type-select">
      <span>题目分区</span>
      <select id="stats-question-type-select" aria-label="题目分区" value={questionType} onChange={(event) => setQuestionType(event.target.value as "general" | "brand" | "all")}>
        <option value="general">通用题（自然发现）</option><option value="brand">品牌题（功能验证）</option><option value="all">全部题目</option>
      </select><Icon name="chevronDown" size={14}/>
    </label>
    <label className="filter-select" htmlFor="stats-kind-select">
      <span>答案口径</span>
      <select id="stats-kind-select" aria-label="答案口径" value={answerKind} onChange={(event) => setAnswerKind(event.target.value as "split" | "answer" | "search_result")}>
        <option value="split">分栏（不合并）</option><option value="answer">仅生成回答</option><option value="search_result">仅检索结果</option>
      </select><Icon name="chevronDown" size={14}/>
    </label>
    {canExport && <Button variant="secondary" icon="download" disabled={exporting} onClick={() => void download()}>{exporting ? "导出中…" : "导出 CSV"}</Button>}
    {mode === "live" && canFreeze && roundId !== "all" && selectedRound?.status === "planning" && <Button variant="secondary" disabled={roundBusy} onClick={() => void startSelectedRound()}>{roundBusy ? "处理中…" : "开始本轮"}</Button>}
    {mode === "live" && canFreeze && roundId !== "all" && selectedRound?.status === "running" && <Button variant="secondary" disabled={roundBusy} onClick={() => void completeSelectedRound()}>{roundBusy ? "冻结中…" : "完成本轮并冻结"}</Button>}
    {mode === "live" && roundId !== "all" && selectedRound && ["completed", "closed"].includes(selectedRound.status) && <span className="knowledge-footnote">{selectedRound.status === "completed" ? "已完成 · 快照已冻结" : "已关闭"}</span>}
  </div>;
  return <div className="statistics-workspace">
    <nav className="stats-group-tabs" aria-label="统计看板分组">
      {STATS_TAB_GROUPS.map((group) => <button
        type="button"
        key={group.id}
        className={`stats-group-tab ${activeStatsGroup.id === group.id ? "active" : ""}`}
        onClick={() => { if (activeStatsGroup.id !== group.id) selectTab(group.tabs[0]); }}
      >{group.label}</button>)}
    </nav>
    {activeGroupTabs.length > 1 && <WorkTabs items={activeGroupTabs} active={activeTab} onChange={selectTab} ariaLabel={`${activeStatsGroup.label}视图`}/>}
    {statsToolbar}
    {activeTab === "overview" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>监测统计</h3><p>总览默认只算通用题；品牌题单独看。生成回答与检索结果分栏展示，各自独立分母，不合并算提及率</p></div></div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && <div className="stats-loading-note" role="status"><i/><span>{overview ? "正在刷新统计…" : "正在加载统计…"}</span></div>}
      {!overview && loading && <div className="stats-skeleton" aria-hidden="true">
        <div className="stats-skeleton-cards"><i/><i/><i/></div>
        <div className="stats-skeleton-grid"><div><b/><b/><b/><b/></div><div><b/><b/><b/><b/></div></div>
        <div className="stats-skeleton-grid"><div><b/><b/><b/></div><div><b/><b/><b/></div></div>
      </div>}
      {overview && <>
        <div className="stats-cards stats-cards-3">
          <div><span>有效回答（当前筛选）</span><strong>{overview.valid_answers}</strong></div>
          <div className="stats-card-clickable" role="button" tabIndex={0} aria-label="查看渠道明细" title="点开查看渠道明细并导出" onClick={() => onNavigate("channels")} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onNavigate("channels"); } }}><span>渠道数</span><strong>{overview.channel_count}</strong><small className="stats-card-hint">点开明细</small></div>
          <div><span title="引用里去重后的 URL 数，不是 public_pages 登记页数">被引页面数</span><strong>{overview.page_count}</strong></div>
        </div>
        <div className="stats-viz-grid">
          <section className="stats-viz-card">
            <div className="stats-viz-head"><div><h4>核心比率</h4><p>分母统一为有效回答</p></div><span className="stats-viz-chip">有效 {overview.valid_answers}</span></div>
            <RateBars ariaLabel="品牌提及、识别与引用率" items={[
              { label: "品牌提及率", value: overview.brand_mention_rate, hint: `${overview.brand_mentioned_answers} / ${overview.valid_answers} 条有效回答`, tone: "blue" },
              { label: "被引用率（提及且带链接）", value: overview.brand_cited_rate ?? null, hint: `${overview.brand_cited_answers ?? 0} / ${overview.valid_answers} 条；只算提及且带已复核 URL 的回答`, tone: "teal" },
              { label: "品牌识别率", value: overview.brand_identified_rate, hint: `${overview.brand_identified_answers} / ${overview.valid_answers} 条；不覆盖提及率`, tone: "teal" },
              { label: "被推荐率", value: overview.brand_recommendation_rate ?? null, hint: `${overview.brand_recommended_answers ?? 0} / ${overview.recommendation_known_answers ?? 0} 条推荐状态已知；未知不进分母`, tone: "teal" },
              { label: "Top3 占比", value: overview.top3_rate ?? null, hint: `${overview.top3_answers ?? 0} / ${overview.recommendation_known_answers ?? 0} 条；位次来自有序列表，正文顺序不算`, tone: "teal" },
              { label: "答案份额", value: overview.answer_share ?? null, hint: `品牌实体 ${overview.brand_entity_mentions ?? 0} 次 / 全部实体 ${(overview.brand_entity_mentions ?? 0) + (overview.competitor_entity_mentions ?? 0)} 次；按出现次数，不等同提及率`, tone: "slate" },
              { label: "引用率", value: overview.citation_rate, display: citationRate(overview.citation_observable_answers, overview.citation_rate), hint: `${overview.citation_answers} / ${overview.valid_answers} 条有效回答；可观测 ${overview.citation_observable_answers} 条，不可观测 ${overview.citation_unobservable_answers} 条`, tone: "amber" },
            ]} />
            {overview.three_state && <p className="viz-footnote">三分互斥：被引用且带链接 {overview.three_state.cited} · 仅提及无链接 {overview.three_state.mentioned_only} · 未出现品牌 {overview.three_state.absent}（合计 {overview.three_state.denominator} 条有效回答）。</p>}
          </section>
          <section className="stats-viz-card">
            <div className="stats-viz-head"><div><h4>样本构成</h4><p>有效回答与未计入项</p></div><span className="stats-viz-chip">总样本 {sampleTotal}</span></div>
            <DonutChart ariaLabel="统计样本构成" centerValue={sampleTotal} centerLabel="总样本" segments={[
              { label: "有效回答", value: overview.valid_answers, tone: "blue" },
              { label: "失败", value: overview.excluded.failed, tone: "red" },
              { label: "待复核", value: overview.excluded.manual_review, tone: "amber" },
              { label: "无答案面", value: overview.excluded.no_answer_surface, tone: "slate" },
              { label: "未完成", value: overview.excluded.pending_or_running, tone: "slate" },
            ]} />
          </section>
          <section className="stats-viz-card">
            <div className="stats-viz-head"><div><h4>生成回答 / 检索结果</h4><p>独立分母，不合并算提及率</p></div><span className="stats-viz-chip">分栏</span></div>
            {visibleKindRows.length ? <ColumnCompare ariaLabel="生成回答与检索结果有效样本对比" items={answerKindColumns} /> : <VizEmpty text="答案口径分栏暂不可用" />}
            <div className="viz-kind-notes">
              {visibleKindRows.map((row) => <p key={row.answer_kind}>
                <i style={{ background: row.answer_kind === "answer" ? "#326af4" : "#2a9d8f" }} />
                <strong>{row.answer_kind === "answer" ? "生成回答" : "检索结果"}</strong>
                <span>提及 {rate(row.brand_mention_rate)} · 引用 {citationRate(row.citation_observable_answers, row.citation_rate)} · 可观测 {row.citation_observable_answers} 条 · 被引页面 {row.page_count}</span>
              </p>)}
            </div>
          </section>
          <section className="stats-viz-card">
            <div className="stats-viz-head"><div><h4>情感复核</h4><p>仅提及样本 · 规则词典信号</p></div><span className="stats-viz-chip">{geo ? `未提及 ${geo.sentiment.not_mentioned}` : "--"}</span></div>
            {geo ? <><StackedBar ariaLabel="提及样本情感分布" segments={sentimentSegments} footnote="未提及样本单列，不计入情感占比；该信号不进 KPI，仅作人工复核。" /><div className="viz-fact-grid"><div><span>提及样本</span><strong>{geo.sentiment.positive + geo.sentiment.neutral + geo.sentiment.negative}</strong></div><div><span>正向率</span><strong>{rate(geo.sentiment.positive_rate)}</strong></div><div><span>平均情感分</span><strong>{geo.sentiment.average_score === null ? "--" : geo.sentiment.average_score.toFixed(2)}</strong></div></div></> : <VizEmpty text="暂无情感统计" />}
          </section>
        </div>
        {!visibleKindRows.length && <p className="stats-excluded">答案口径分栏暂不可用；请刷新或检查统计接口。</p>}
        {baselineVisible && baseline && answerKind !== "split" && <p className="stats-excluded">较基线「{baselineRound?.name ?? "基线"}」：有效回答 {signedCount(overview.valid_answers - baseline.valid_answers)} · 品牌提及率 {signedRate(rateDiff(overview.brand_mention_rate, baseline.brand_mention_rate))} · 引用率 {overview.citation_observable_answers && baseline.citation_observable_answers ? signedRate(rateDiff(overview.citation_rate, baseline.citation_rate)) : "两侧至少一侧不可观测"} · 渠道数 {signedCount(overview.channel_count - baseline.channel_count)} · 被引页面 {signedCount(overview.page_count - baseline.page_count)}</p>}
        {roundId !== "all" && selectedRound?.id === baselineRound?.id && <p className="stats-excluded">当前为基线轮次，不展示与自身的差值。</p>}
        {geo && <div className="stats-viz-grid">
          <section className="stats-viz-card">
            <div className="stats-viz-head"><div><h4>覆盖与新鲜度</h4><p>题目覆盖、24 小时新鲜度与采样失败</p></div><span className="stats-viz-chip">当前筛选</span></div>
            <RateBars ariaLabel="覆盖、新鲜度与失败率" items={[
              { label: "题目覆盖率", value: geo.prompt_coverage, hint: `${geo.counts.covered_questions ?? 0} / ${geo.counts.active_questions ?? 0} 题有有效样本`, tone: "blue" },
              { label: "24h 新鲜率", value: geo.fresh_24h_rate, hint: geo.freshness_hours === null ? "暂无最近采样" : `最新样本 ${geo.freshness_hours.toFixed(1)} 小时前`, tone: "teal" },
              { label: "采样失败率", value: geo.failure_rate, hint: `失败 ${geo.counts.failed_samples ?? 0} / 总样本 ${geo.counts.total_samples ?? 0}`, tone: "red" },
            ]} />
            <div className="viz-fact-grid">
              <div><span>列表位次样本</span><strong>{geo.brand_position.sample_count}</strong></div>
              <div><span>平均列表位次</span><strong>{geo.brand_position.average_rank ?? "--"}</strong></div>
              <div><span>首位提及率</span><strong>{rate(geo.brand_position.top1_rate)}</strong></div>
            </div>
          </section>
          <section className="stats-viz-card">
            <div className="stats-viz-head"><div><h4>竞争格局</h4><p>SOV 与竞品提及样本</p></div><span className="stats-viz-chip">竞品 {geo.counts.competitor_mentioned_samples ?? 0} 样本</span></div>
            <div className="viz-sov">
              <div><span>品牌 SOV</span><strong>{rate(geo.sov)}</strong></div>
              <div className="viz-sov-track"><i style={{ width: `${Math.min(100, Math.max(0, (geo.sov ?? 0) * 100))}%` }} /></div>
            </div>
            <HorizontalBars ariaLabel="品牌与竞品样本份额" items={sovBars} emptyText="暂无份额：品牌与竞品都未被提及" />
            <div className="viz-fact-grid">
              <div><span>品牌提及样本</span><strong>{geo.counts.brand_mentioned_answers ?? 0}</strong></div>
              <div><span>竞品提及样本</span><strong>{geo.counts.competitor_mentioned_samples ?? 0}</strong></div>
              <div><span>竞品数量</span><strong>{geo.by_competitor.length}</strong></div>
            </div>
            <p className="viz-footnote">份额分母是「提到品牌或任一竞品的去重样本」，一个回答同时提到多方时各方都计 1，所以份额相加可能超过 100%；这不是投票，是曝光普遍度。</p>
            <p className="viz-footnote">无竞品提及时 SOV 记 100%，只代表当前样本里没有识别到竞品，不代表市场份额。</p>
          </section>
        </div>}
        <p className="stats-excluded">未计入有效回答：失败 {overview.excluded.failed} · 待复核 {overview.excluded.manual_review} · 无答案面 {overview.excluded.no_answer_surface} · 未完成 {overview.excluded.pending_or_running}</p>
        {Object.keys(overview.failure_breakdown ?? {}).length > 0 && <p className="stats-excluded">失败类型：{Object.entries(overview.failure_breakdown ?? {}).map(([code, count]) => `${failureCodeLabels[code] ?? code} ${count}`).join(" · ")}；不计入有效回答，也不与未命中混算。</p>}
      </>}
      {!overview && !loading && !error && <p className="knowledge-empty">暂无统计数据</p>}
    </Panel>}
    {activeTab === "engines" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>全入口合计</h3><p>同一引擎的所有入口合并后的总盘；不能据此判断网页端与手机客户端差异，跨端请看「入口对照」</p></div><Badge tone="blue">{engines.length} 个</Badge></div>
      <p className="stats-excluded">本页会合并同一引擎的 API、网页端、手机客户端与应用内搜索样本，只用于看总体；任何引擎级跨端结论必须以「入口对照」为准。</p>
      <div className="stats-viz-card stats-viz-standalone">
        <div className="stats-viz-head"><div><h4>品牌提及率（全入口合计）</h4><p>横条长度按 0–100% 绝对刻度，不按引擎间最大值拉伸</p></div><span className="stats-viz-chip">{engines.reduce((sum, item) => sum + item.valid_answers, 0)} 条有效</span></div>
        <HorizontalBars ariaLabel="全入口合计品牌提及率" scaleMax={1} items={engines.map((item) => ({
          label: item.engine_name,
          value: item.brand_mention_rate ?? 0,
          display: rate(item.brand_mention_rate),
          hint: `${item.brand_mentioned_answers} / ${item.valid_answers} 条 · 引用 ${citationRate(item.citation_observable_answers, item.citation_rate)} · 不可观测 ${item.citation_unobservable_answers}`,
          tone: (item.brand_mention_rate ?? 0) > 0 ? "blue" : "slate",
        }))} emptyText="暂无全入口样本" />
      </div>
      <div className="table-scroll"><table><thead><tr><th>引擎</th><th>有效回答</th><th>品牌提及率</th><th>引用率</th><th>引用可观测</th><th>不可观测</th></tr></thead><tbody>{engines.map((item) => <tr key={item.engine_id}><td>{item.engine_name}</td><td>{item.valid_answers}</td><td>{rate(item.brand_mention_rate)}</td><td>{citationRate(item.citation_observable_answers, item.citation_rate)}</td><td>{item.citation_observable_answers}</td><td>{item.citation_unobservable_answers}</td></tr>)}</tbody></table>{loading && <p className="knowledge-empty">正在加载统计…</p>}{!engines.length && !loading && <p className="knowledge-empty">暂无有效样本</p>}</div></Panel>}
    {activeTab === "entries" && <Panel className="knowledge-list-panel">
      <div className="panel-heading">
        <div>
          <h3>入口对照</h3>
          <p>同一引擎的网页端、手机客户端、官方 API、应用内搜索分别一行；每行独立分母，不把两端回答平均成单一结论。</p>
        </div>
        <Badge tone="blue">{entries.length} 个入口组合</Badge>
      </div>
      <div className="stats-viz-card stats-viz-standalone">
        <div className="stats-viz-head">
          <div><h4>品牌提及率（按入口）</h4><p>标签为「引擎 · 入口」；横条按 0–100% 绝对刻度。手机 App 与网页端回答可能不同，不做合并。</p></div>
          <span className="stats-viz-chip">{entries.reduce((sum, item) => sum + item.valid_answers, 0)} 条有效</span>
        </div>
        <HorizontalBars ariaLabel="按入口品牌提及率" scaleMax={1} items={entries.map((item) => ({
          label: `${item.engine_name} · ${item.entry_label}${item.entry_name && item.entry_name !== item.entry_label ? ` · ${item.entry_name}` : ""}`,
          value: item.brand_mention_rate ?? 0,
          display: rate(item.brand_mention_rate),
          hint: `${item.brand_mentioned_answers} / ${item.valid_answers} 条 · 推荐 ${rate(item.brand_recommendation_rate ?? null)} · 引用 ${citationRate(item.citation_observable_answers, item.citation_rate)}`,
          tone: item.entry_type === "app_user" ? "amber" : item.entry_type === "web_user" ? "blue" : "slate",
        }))} emptyText="暂无入口维度样本" />
      </div>
      <div className="table-scroll"><table><thead><tr><th>引擎</th><th>入口</th><th>有效回答</th><th>品牌提及率</th><th>被推荐率</th><th>Top3 占比</th><th>引用率</th></tr></thead><tbody>{entries.map((item) => <tr key={item.entry_id}><td>{item.engine_name}</td><td><div><Badge tone={item.entry_type === "app_user" ? "amber" : item.entry_type === "web_user" ? "blue" : "slate"}>{item.entry_label}</Badge>{item.entry_name && item.entry_name !== item.entry_label && <small className="task-entry-meta">{item.entry_name}</small>}</div></td><td>{item.valid_answers}</td><td>{rate(item.brand_mention_rate)}</td><td>{rate(item.brand_recommendation_rate ?? null)}</td><td>{rate(item.top3_rate ?? null)}</td><td>{citationRate(item.citation_observable_answers, item.citation_rate)}</td></tr>)}</tbody></table>{loading && <p className="knowledge-empty">正在加载入口统计…</p>}{!entries.length && !loading && <p className="knowledge-empty">{entryError || "暂无入口维度样本；请先给同一引擎分别建网页端与手机客户端入口并完成采样。"}</p>}</div>
      {entryError && entries.length > 0 && <p className="stats-excluded">入口对照刷新失败：{entryError}；当前显示上一次成功结果。</p>}
      <p className="viz-footnote">引用率为「不可观测」表示该入口没有可判断的引用证据，不能读成 0%。被推荐率 `--` 表示没有已确认的推荐状态样本，也不写成 0%。</p>
    </Panel>}
    {activeTab === "health" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>引擎健康与成本</h3><p>入口级样本、失败率、延迟、token 与估算费用；缺凭据/未采样单独标记</p></div><Badge tone={attentionCount ? "amber" : "green"}>{attentionCount ? `${attentionCount} 个需处理` : "全部正常"}</Badge></div>
      <div className="stats-cards">
        <div><span>入口数</span><strong>{engineHealth.length}</strong></div>
        <div><span>总样本</span><strong>{engineHealth.reduce((sum, item) => sum + item.sample_count, 0)}</strong></div>
        <div><span>平均延迟</span><strong>{ms(avgLatency)}</strong></div>
        <div><span>总 token</span><strong>{totalTokens.toLocaleString()}</strong></div>
        <div><span>估算费用</span><strong>{money(totalCost)}</strong></div>
      </div>
      <div className="stats-viz-grid">
        <section className="stats-viz-card">
          <div className="stats-viz-head"><div><h4>入口可用性</h4><p>按入口状态聚合，不是样本失败率</p></div><span className="stats-viz-chip">{engineHealth.length} 个入口</span></div>
          <DonutChart ariaLabel="引擎入口可用性分布" centerValue={engineHealth.length} centerLabel="入口" segments={availabilitySegments} />
        </section>
        <section className="stats-viz-card">
          <div className="stats-viz-head"><div><h4>样本失败率</h4><p>0–100% 绝对刻度；仅列有样本或失败记录的入口</p></div><span className="stats-viz-chip">失败样本 {engineHealth.reduce((sum, item) => sum + item.failed_count, 0)}</span></div>
          <HorizontalBars ariaLabel="引擎入口样本失败率" scaleMax={1} items={failureRateBars} emptyText="暂无可计算的失败率" />
        </section>
      </div>
      <div className="stats-viz-card stats-viz-standalone">
        <div className="stats-viz-head"><div><h4>平均延迟</h4><p>按入口平均延迟排序，单位毫秒</p></div><span className="stats-viz-chip">均值 {ms(avgLatency)}</span></div>
        <HorizontalBars ariaLabel="引擎入口平均延迟" maxItems={8} items={latencyBars} emptyText="暂无延迟数据" />
      </div>
      <div className="table-scroll"><table><thead><tr><th>引擎 / 入口</th><th>可用性</th><th>任务</th><th>样本</th><th>失败率</th><th>平均延迟</th><th>token</th><th>费用</th><th>最近采样</th></tr></thead><tbody>
        {engineHealth.map((item) => <tr key={item.entry_id}>
          <td><strong>{item.engine_name}</strong><br/><span className="muted">{item.entry_name} · {item.model_name ?? item.protocol}</span></td>
          <td><Badge tone={toneFor(item.availability)}>{healthLabel[item.availability]}</Badge>{!item.price_configured && item.estimated_cost_cny === null && <p className="muted">未配置单价</p>}</td>
          <td>{item.task_count}</td><td>{item.sample_count}</td><td>{rate(item.failure_rate)}</td><td>{ms(item.avg_latency_ms)}</td><td>{item.total_tokens.toLocaleString()}</td><td>{money(item.estimated_cost_cny)}</td><td>{item.last_sampled_at ? new Date(item.last_sampled_at).toLocaleString("zh-CN") : "未采样"}</td>
        </tr>)}
      </tbody></table>{loading && <p className="knowledge-empty">正在加载统计…</p>}{!engineHealth.length && !loading && <p className="knowledge-empty">暂无引擎入口</p>}</div>
    </Panel>}
    {activeTab === "questions" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>分问题</h3><p>按监测题目查看结果；横条按 0–100% 绝对刻度，只比较提及率</p></div><Badge tone="blue">{questions.length} 题</Badge></div>
      <div className="stats-viz-card stats-viz-standalone">
        <div className="stats-viz-head"><div><h4>题目品牌提及率</h4><p>按提及率从高到低排序，引用率见提示与下方明细</p></div><span className="stats-viz-chip">{questions.reduce((sum, item) => sum + item.valid_answers, 0)} 条有效</span></div>
        <HorizontalBars ariaLabel="分问题品牌提及率" scaleMax={1} maxItems={20} items={questionBars} emptyText="暂无分问题样本" />
      </div>
      <div className="table-scroll"><table><thead><tr><th>题目</th><th>有效回答</th><th>品牌提及率</th><th>引用率</th><th>引用可观测</th><th>不可观测</th></tr></thead><tbody>{questions.map((item) => <tr key={item.question_id}><td>{item.question_code} · {item.question_title}</td><td>{item.valid_answers}</td><td>{rate(item.brand_mention_rate)}</td><td>{citationRate(item.citation_observable_answers, item.citation_rate)}</td><td>{item.citation_observable_answers}</td><td>{item.citation_unobservable_answers}</td></tr>)}</tbody></table>{loading && <p className="knowledge-empty">正在加载统计…</p>}{!questions.length && !loading && <p className="knowledge-empty">暂无有效样本</p>}</div></Panel>}
    {activeTab === "sources" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>信源分布</h3><p>AI 从哪些域名取证；「渠道被引」只统计命中发布结果记录的真实 URL。按引用条数排序，最多显示 {SOURCES_LIMIT} 个域名</p></div><Badge tone="blue">{sources.length} 个域名</Badge></div>
      <div className="stats-viz-card stats-viz-standalone">
        <div className="stats-viz-head"><div><h4>品类信源覆盖</h4><p>已复核引用里 Top {SOURCES_LIMIT} 个站点，我们占几个、缺哪些；分母固定 Top N，不是全网域名</p></div><Badge tone="blue">近 90 天</Badge></div>
        {coverage ? <>
          <div className="stats-cards stats-cards-3">
            <div><span title="自有域名命中，或有发布回执落在该域名">已覆盖站点</span><strong>{coverage.coverage.covered_domains} / {coverage.coverage.top_domains}</strong><small className="stats-card-hint">{rate(coverage.coverage.covered_rate)}</small></div>
            <div><span>自有域名</span><strong>{coverage.coverage.owned_domains}</strong><small className="stats-card-hint">品牌 owned_domains + 引用判定</small></div>
            <div><span>竞品有而我们没有</span><strong>{coverage.gaps.length}</strong><small className="stats-card-hint">可投缺口</small></div>
          </div>
          {coverage.gaps.length > 0 ? <div className="table-scroll"><table><thead><tr><th>缺口站点</th><th>竞品引用条数</th><th>竞品</th></tr></thead><tbody>
            {coverage.gaps.map((gap) => <tr key={gap.domain}>
              <td><strong>{gap.domain}</strong></td>
              <td>{gap.competitor_citations}</td>
              <td>{gap.competitor_names.join(" · ") || "—"}</td>
            </tr>)}
          </tbody></table></div> : <p className="knowledge-empty">暂无「竞品被引而我们没发」的站点。</p>}
          <p className="viz-footnote">{coverage.notes.join(" ")}</p>
        </> : <p className="knowledge-empty">{coverageError ? `引用源覆盖暂不可用：${coverageError}` : "暂无覆盖数据"}</p>}
      </div>
      <div className="stats-viz-card stats-viz-standalone">
        <div className="stats-viz-head"><div><h4>信源分级（T0–T3）与多源交叉验证</h4><p>分级是站点属性，由域名白名单与来源类别推导，每条结论都能追到命中规则；不做加权总分</p></div><Badge tone="blue">近 {tiers?.days ?? 90} 天</Badge></div>
        {tiers ? <>
          <div className="stats-cards stats-cards-4">
            {tiers.tiers.filter((row) => row.tier !== "T3").map((row) => (
              <div key={row.tier}>
                <span title={row.definition}>{row.tier} · {row.label}</span>
                <strong>{row.domains} 站 / {row.citations} 条</strong>
                <small className="stats-card-hint">引用份额 {rate(row.citation_share)}</small>
              </div>
            ))}
            <div>
              <span title={tiers.tiers.find((row) => row.tier === "T3")?.definition}>T3 · 长尾与未知</span>
              <strong>{tiers.tiers.find((row) => row.tier === "T3")?.domains ?? 0} 站 / {tiers.tiers.find((row) => row.tier === "T3")?.citations ?? 0} 条</strong>
              <small className="stats-card-hint">引用份额 {rate(tiers.tiers.find((row) => row.tier === "T3")?.citation_share ?? null)}</small>
            </div>
          </div>
          <div className="stats-cards stats-cards-3">
            <div><span title="一条回答里我方被几个互不相同的站引用；同站多页只算一个来源">被引回答</span><strong>{tiers.cross_validation.brand_cited_answers}</strong><small className="stats-card-hint">单一来源 {tiers.cross_validation.single_source_answers} · 多来源 {tiers.cross_validation.multi_source_answers}</small></div>
            <div><span title="至少两个不同 T0/T1 站在同一条回答里引用我方">多高权重来源</span><strong>{rate(tiers.cross_validation.multi_high_tier_rate)}</strong><small className="stats-card-hint">{tiers.cross_validation.multi_high_tier_answers} 条 / 多来源率 {rate(tiers.cross_validation.multi_source_rate)}</small></div>
            <div><span title="至少一个 T0/T1 站引用我方">有高权重支撑</span><strong>{tiers.cross_validation.tier01_supported_answers}</strong><small className="stats-card-hint">占被引回答 {rate(tiers.cross_validation.brand_cited_answers ? tiers.cross_validation.tier01_supported_answers / tiers.cross_validation.brand_cited_answers : null)}</small></div>
          </div>
          <div className="table-scroll"><table><thead><tr><th>站点</th><th>档位</th><th>命中规则</th><th>引用条数</th><th>涉及回答</th></tr></thead><tbody>
            {tiers.domains.map((row) => <tr key={row.domain}>
              <td><strong>{row.domain}</strong></td>
              <td>{row.tier} · {row.tier_label}</td>
              <td title={row.tier_reason}>{row.tier_rule}</td>
              <td>{row.citations}</td>
              <td>{row.samples}</td>
            </tr>)}
          </tbody></table></div>
          <p className="viz-footnote">{tiers.notes.join(" ")}</p>
        </> : <p className="knowledge-empty">{tiersError ? `信源分级暂不可用：${tiersError}` : "暂无分级数据"}</p>}
      </div>
      <div className="stats-viz-card stats-viz-standalone">
        <div className="stats-viz-head"><div><h4>信源 × 内容形态矩阵</h4><p>T0–T2 站点上，AI 历史引用的是哪类页面；这是事实分布，不是「该发什么」的推荐</p></div><Badge tone="blue">近 {matrix?.days ?? 90} 天</Badge></div>
        {matrix ? <>
          <div className="stats-cards stats-cards-3">
            {matrix.forms.slice(0, 3).map((row) => (
              <div key={row.form}>
                <span>{row.label}</span>
                <strong>{row.citations} 条</strong>
                <small className="stats-card-hint">占已复核引用 {rate(row.citation_share)}</small>
              </div>
            ))}
          </div>
          {(() => {
            const other = matrix.forms.find((row) => row.form === "other");
            if (!other || (other.citation_share ?? 0) < 0.3) return null;
            return <p className="viz-footnote">形态标注缺口：{rate(other.citation_share)} 的已复核引用落在「其他」，说明 page_type 提取不足，上面分布只能当参考，不能照着投放。</p>;
          })()}
          <div className="table-scroll"><table><thead><tr><th>站点</th><th>档位</th><th>引用条数</th><th>主形态</th><th>主形态占比</th><th>形态分布</th><th>状态</th></tr></thead><tbody>
            {matrix.domains.map((row) => <tr key={row.domain}>
              <td><strong>{row.domain}</strong></td>
              <td>{row.tier}</td>
              <td>{row.citations}</td>
              <td>{row.top_form_label ?? "—"}</td>
              <td>{rate(row.top_form_share)}</td>
              <td className="stats-matrix-forms">{row.forms.map((form) => `${form.label} ${form.citations}`).join(" · ")}</td>
              <td>{row.status === "owned" ? "自有" : row.status === "covered" ? "已覆盖" : row.status === "gap" ? "缺口（竞品有我们无）" : "未触碰"}</td>
            </tr>)}
          </tbody></table></div>
          <p className="viz-footnote">{matrix.notes.join(" ")}</p>
        </> : <p className="knowledge-empty">{matrixError ? `形态矩阵暂不可用：${matrixError}` : "暂无形态数据"}</p>}
      </div>
      <div className="stats-viz-card stats-viz-standalone">
        <div className="stats-viz-head"><div><h4>验收契约 · 近 {contract?.window_days ?? 90} 天</h4><p>三个率各自独立、不相加；连续采集目标 {contract?.streak.target ?? 30} 天</p></div>{contract && <Badge tone={contract.ready.contract_ok ? "green" : "amber"}>{contract.ready.contract_ok ? "已达标" : "未达标"}</Badge>}</div>
        {contract ? <>
          <div className="stats-cards stats-cards-3">
            <div><span>提及率</span><strong>{contract.rates.mention_rate === null ? "无样本" : rate(contract.rates.mention_rate)}</strong><small className="stats-card-hint">提及 {contract.numerators.mentioned} / 有效回答 {contract.valid_answers}</small></div>
            <div><span>引用率</span><strong>{contract.rates.citation_rate === null ? "无样本" : rate(contract.rates.citation_rate)}</strong><small className="stats-card-hint">品牌相关且已复核 {contract.numerators.cited} / 有效回答 {contract.valid_answers}</small></div>
            <div><span>正向率</span><strong>{contract.rates.positive_rate === null ? "未采集" : rate(contract.rates.positive_rate)}</strong><small className="stats-card-hint">{contract.numerators.labeled ? `正向 ${contract.numerators.positive} / 已标注 ${contract.numerators.labeled}` : "尚无情感标注，不填 0%"}</small></div>
          </div>
          <p className="viz-footnote">引用来源结构：共 {contract.cited_source_mix.total} 条被引，其中社交/UGC·电商·其他合计 {contract.cited_source_mix.low_trust_total} 条（{contract.cited_source_mix.low_trust_share === null ? "—" : rate(contract.cited_source_mix.low_trust_share)}），来源类别未识别 {contract.cited_source_mix.unknown_total} 条（{contract.cited_source_mix.unknown_share === null ? "—" : rate(contract.cited_source_mix.unknown_share)}）；占比只作披露，不参与率的加减。</p>
          <p className="viz-footnote">连续采集：{contract.streak.days} 天（目标 {contract.streak.target} 天，最近一次 {contract.streak.last_date ?? "—"}）{contract.ready.missing.length ? ` · 缺 ${contract.ready.missing.join("、")}` : ""}</p>
          <p className="viz-footnote">{contract.definitions.join(" ")} {contract.notes.join(" ")}</p>
        </> : <p className="knowledge-empty">{contractError ? `验收契约暂不可用：${contractError}` : "暂无数据"}</p>}
      </div>
      <div className="stats-viz-card stats-viz-standalone">
        <div className="stats-viz-head"><div><h4>内容新鲜度 · {freshness?.window_months ?? 18} 个月窗口</h4><p>只认发布回执时间；标了发布但没回执的单列，不进分母</p></div>{freshness && <Badge tone={freshness.summary.stale > 0 ? "amber" : "slate"}>过期 {freshness.summary.stale} 条</Badge>}</div>
        {freshness ? <>
          <div className="stats-cards stats-cards-3">
            <div><span>已发布</span><strong>{freshness.summary.published}</strong><small className="stats-card-hint">过期线 {new Date(freshness.cutoff).toLocaleDateString("zh-CN")}</small></div>
            <div><span>新鲜 / 过期</span><strong>{freshness.summary.fresh} / {freshness.summary.stale}</strong><small className="stats-card-hint">过期率 {freshness.summary.stale_rate === null ? "无已发布内容" : rate(freshness.summary.stale_rate)}</small></div>
            <div><span>未发布 / 待核验</span><strong>{freshness.summary.unpublished} / {freshness.summary.published_unverified}</strong><small className="stats-card-hint">母稿 {freshness.summary.masters} · 渠道稿 {freshness.summary.channel_copies}</small></div>
          </div>
          {freshness.by_channel.length > 0 && <div className="table-scroll"><table><thead><tr><th>渠道</th><th>条目</th><th>新鲜</th><th>过期</th><th>未发布</th><th>过期率</th><th>最老发布</th></tr></thead><tbody>
            {freshness.by_channel.slice(0, 8).map((row) => <tr key={row.channel_id ?? "unassigned"}>
              <td><strong>{row.channel_name}</strong></td>
              <td>{row.items}</td>
              <td>{row.fresh}</td>
              <td>{row.stale}</td>
              <td>{row.unpublished}</td>
              <td>{row.stale_rate === null ? "—" : rate(row.stale_rate)}</td>
              <td>{row.oldest_published_at ? new Date(row.oldest_published_at).toLocaleDateString("zh-CN") : "—"}</td>
            </tr>)}
          </tbody></table></div>}
          <p className="viz-footnote">{freshness.notes.join(" ")}</p>
        </> : <p className="knowledge-empty">{freshnessError ? `内容新鲜度暂不可用：${freshnessError}` : "暂无内容数据"}</p>}
      </div>
      <div className="stats-viz-card stats-viz-standalone">
        <div className="stats-viz-head"><div><h4>页面三态 · 可访问 / 可检索 / 被引用</h4><p>三态各自独立观测，不合成分数；unknown = 没查过，不等于没有</p></div>{pageStates && <span className="stats-viz-chip">{pageStates.summary.receipts} 条回执</span>}</div>
        {pageStates ? <>
          <div className="stats-viz-grid">
            <div><span>可访问</span><strong>{pageStates.summary.accessible.yes} / {pageStates.summary.receipts}</strong><small className="stats-card-hint">明确不可访问 {pageStates.summary.accessible.no} · 未查 {pageStates.summary.accessible.unknown}</small></div>
            <div><span>可检索</span><strong>{pageStates.summary.searchable.yes}</strong><small className="stats-card-hint">未命中 {pageStates.summary.searchable.no} · 未检测/查询失败 {pageStates.summary.searchable.unknown}</small></div>
            <div><span>被引用</span><strong>{pageStates.summary.cited_pages} 页</strong><small className="stats-card-hint">合计 {pageStates.summary.cited_total} 条已复核引用</small></div>
          </div>
          {pageStates.pages.length > 0 && <div className="table-scroll"><table><thead><tr><th>页面</th><th>渠道</th><th>可访问</th><th>可检索</th><th>被引用</th></tr></thead><tbody>
            {pageStates.pages.slice(0, 8).map((row) => <tr key={row.receipt_id}>
              <td><strong>{row.title || row.url}</strong><small className="muted">{row.url}</small></td>
              <td>{row.channel ?? "—"}</td>
              <td>{row.accessible === "unknown" ? <Badge tone="slate">未查</Badge> : row.accessible === "yes" ? <Badge tone="green">可访问</Badge> : <Badge tone="amber">{row.accessible_status ?? "不可访问"}</Badge>}</td>
              <td>{row.searchable === "unknown" ? <Badge tone="slate">{row.searchable_detail}</Badge> : row.searchable === "yes" ? <Badge tone="green">{row.searchable_detail}</Badge> : <Badge tone="amber">未搜到</Badge>}</td>
              <td>{row.cited > 0 ? <Badge tone="blue">{row.cited} 条</Badge> : "0"}</td>
            </tr>)}
          </tbody></table></div>}
          <p className="viz-footnote">{pageStates.notes.join(" ")}</p>
        </> : <p className="knowledge-empty">{pageStatesError ? `页面三态暂不可用：${pageStatesError}` : "暂无回执"}</p>}
      </div>
      <div className="stats-viz-card stats-viz-standalone">
        <div className="stats-viz-head"><div><h4>分发候选 · 只建议不执行</h4><p>排序器：被复核引用条数 → 成功回执数 → 渠道名，单一维度比较，没有加权总分</p></div>{candidates && <span className="stats-viz-chip">approved {candidates.summary.approved} / 共 {candidates.summary.channels}</span>}</div>
        {candidates ? <>
          <div className="table-scroll"><table><thead><tr><th>渠道</th><th>被引条数</th><th>成功回执</th><th>出过引用的引擎</th></tr></thead><tbody>
            {candidates.candidates.slice(0, 8).map((row) => <tr key={row.channel_id}>
              <td><strong>{row.channel}</strong><small className="muted">{row.code}</small></td>
              <td>{row.cited}</td>
              <td>{row.receipts}</td>
              <td>{row.engines.length ? row.engines.join("、") : <span className="muted">暂无</span>}</td>
            </tr>)}
          </tbody></table></div>
          {candidates.others.length > 0 && <p className="viz-footnote">未进候选的渠道（非 approved）：{candidates.others.slice(0, 6).map((row) => `${row.channel}（${row.approval_status ?? "—"}）`).join("、")}</p>}
          <p className="viz-footnote">{candidates.notes.join(" ")}</p>
        </> : <p className="knowledge-empty">{candidatesError ? `分发候选暂不可用：${candidatesError}` : "暂无渠道"}</p>}
      </div>
      <div className="stats-viz-card stats-viz-standalone">
        <div className="stats-viz-head"><div><h4>被引域名 Top 10</h4><p>按引用条数排序；横条长度相对当前 Top 10 最大值</p></div><span className="stats-viz-chip">{sources.length} 个域名</span></div>
        <HorizontalBars ariaLabel="信源域名引用条数" items={sourceBars} emptyText={sourcesError ? `信源分布暂不可用：${sourcesError}` : "暂无可归因的引用"} />
      </div>
      <div className="table-scroll"><table><thead><tr><th>域名</th><th>引用条数</th><th>涉及样本</th><th>自有域名</th><th>渠道被引</th><th>最近采样</th></tr></thead><tbody>
        {sources.map((item) => <tr key={item.domain}>
          <td><strong>{item.domain || "未知域名"}</strong></td>
          <td>{item.citations}</td>
          <td>{item.samples}</td>
          <td>{item.brand_related ? <Badge tone="green">自有</Badge> : "—"}</td>
          <td>{item.channel_citations ? <Badge tone="blue">{item.channel_citations} 条</Badge> : <span className="muted">未命中发布结果</span>}</td>
          <td>{item.last_sampled_at ? new Date(item.last_sampled_at).toLocaleString("zh-CN") : "—"}</td>
        </tr>)}
      </tbody></table>{loading && <p className="knowledge-empty">正在加载统计…</p>}{!sources.length && !loading && <p className="knowledge-empty">{sourcesError ? `信源分布暂不可用：${sourcesError}` : "暂无可归因的引用"}</p>}</div>
    </Panel>}
    {activeTab === "visibility" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>发布可见性</h3><p>每条发布结果里的页面能不能被搜索引擎搜到；只认链接完全一致，不参与渠道归因。显示每条发布结果最近一次检测，最多 {VISIBILITY_LIMIT} 条</p></div><div className="toolbar-extra"><Badge tone="blue">{visibility.length} 条发布结果</Badge>{canCheckVisibility && <Button variant="secondary" disabled={checking || loading || !projectId || projectId === "all"} onClick={() => void runVisibilityCheck()}>{checking ? "检测中…" : `立即检测（${CHECK_LIMIT} 条）`}</Button>}</div></div>
      <div className="stats-viz-card stats-viz-standalone">
        <div className="stats-viz-head"><div><h4>收录结果分布</h4><p>每条发布结果最近一次检测；查询失败单列，不计入未收录</p></div><span className="stats-viz-chip">{visibility.length} 条</span></div>
        <DonutChart ariaLabel="发布结果收录情况" centerValue={visibility.length} centerLabel="发布结果" segments={visibilitySegments} />
      </div>
      <div className="table-scroll"><table><thead><tr><th>发布页面</th><th>结果</th><th>检测时间</th><th>查询词 / 站点</th></tr></thead><tbody>
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
    {activeTab === "adaptation" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>行业适配四问</h3><p>判断这个行业值不值得做 GEO；结论只作布局建议，不阻断建项目，也不改评分</p></div>{adaptation && <Badge tone={adaptation.verdict === "prioritize" ? "green" : adaptation.verdict === "pilot" ? "blue" : adaptation.verdict === "defer" ? "amber" : "slate"}>{adaptation.verdict_label}</Badge>}</div>
      {adaptationError && <p className="form-error" role="alert">行业适配暂不可用：{adaptationError}</p>}
      {adaptation && <>
        <p className="viz-footnote">{adaptation.disclaimer}</p>
        <div className="stats-cards">
          <div><span>四问得分</span><strong>{adaptation.score === null ? "—" : `${adaptation.score}/${adaptation.max_score}`}</strong><small className="stats-card-hint">是=2 部分=1 否=0 不确定不计</small></div>
          <div><span>有效回答</span><strong>{adaptation.evaluated_count}/4</strong><small className="stats-card-hint">少于 3 项只显示信息不足</small></div>
          <div><span>建议</span><strong>{adaptation.verdict_label}</strong><small className="stats-card-hint">{adaptation.reason}</small></div>
        </div>
        <div className="adaptation-grid">
          {adaptation.answers.map((item) => <div className="adaptation-question" key={item.key}>
            <label className="field">
              <span className="field-label">{item.label}</span>
              <select className="text-input" value={adaptationAnswers[item.key] ?? item.answer} disabled={!canManage || adaptationSaving} onChange={(e) => setAdaptationAnswers((current) => ({ ...current, [item.key]: e.target.value }))}>
                <option value="yes">是</option><option value="partial">部分</option><option value="no">否</option><option value="unknown">不确定</option>
              </select>
              <small className="field-hint">{item.hint}</small>
            </label>
          </div>)}
        </div>
        <label className="field"><span className="field-label">备注（可选）</span><textarea className="text-input knowledge-textarea short" value={adaptationNote} disabled={!canManage || adaptationSaving} onChange={(e) => setAdaptationNote(e.target.value)} placeholder="例如行业需求、竞争情况、转化路径的判断依据"/></label>
        <div className="knowledge-actions">
          {canManage ? <Button disabled={adaptationSaving} onClick={() => void saveAdaptation()}>{adaptationSaving ? "保存中…" : "保存评估"}</Button> : <span className="knowledge-footnote">当前账号没有维护指标配置的权限，只能查看。</span>}
          {adaptation.evaluated_at && <span className="knowledge-footnote">上次评估：{new Date(adaptation.evaluated_at).toLocaleString("zh-CN")}</span>}
        </div>
      </>}
    </Panel>}
    {activeTab === "selling_points" && <SellingPointsPanel mode={mode} projectId={projectId} canManage={canManage} onNotice={onNotice}/>}
    {activeTab === "brand_search" && <BrandSearchPanel mode={mode} projectId={projectId} canManage={canManage} onNotice={onNotice}/>}
    {activeTab === "competitor_sources" && <CompetitorSourcesPanel mode={mode} projectId={projectId} onNotice={onNotice}/>}
    {activeTab === "formats" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>内容形式覆盖</h3><p>六类形式按母稿标注统计；历史内容未回填，单独列“未标注”</p></div><Badge tone={formats && formats.summary.master_without_format ? "amber" : "green"}>{formats ? `${formats.summary.master_with_format}/${formats.summary.master_items} 已标注` : "加载中"}</Badge></div>
      {formatsError && <p className="form-error" role="alert">内容形式暂不可用：{formatsError}</p>}
      {formats && <>
        <div className="stats-cards">
          <div><span>母稿</span><strong>{formats.summary.master_items}</strong><small className="stats-card-hint">已标注 {formats.summary.master_with_format}</small></div>
          <div><span>渠道稿</span><strong>{formats.summary.channel_items}</strong><small className="stats-card-hint">继承母稿形式</small></div>
          <div><span>已关联引用证据</span><strong>{formats.summary.citation_linked_items}</strong><small className="stats-card-hint">当前版本口径</small></div>
          <div><span>引用证据覆盖率</span><strong>{formats.summary.citation_coverage === null ? "—" : `${(formats.summary.citation_coverage * 100).toFixed(0)}%`}</strong><small className="stats-card-hint">有可追溯来源，非 AI 实际引用</small></div>
        </div>
        <div className="table-scroll"><table><thead><tr><th>内容形式</th><th>母稿</th><th>渠道稿</th><th>当前版本</th><th>已关联引用</th><th>覆盖率</th></tr></thead><tbody>
          {formats.formats.map((item) => <tr key={item.content_type ?? "unclassified"}>
            <td><strong>{item.label}</strong></td>
            <td>{item.master_items}</td>
            <td>{item.channel_items}</td>
            <td>{item.current_versions}</td>
            <td>{item.citation_linked_items}</td>
            <td>{item.citation_coverage === null ? "—" : `${(item.citation_coverage * 100).toFixed(0)}%`}</td>
          </tr>)}
        </tbody></table></div>
        <p className="viz-footnote">{formats.notes.join(" ")}</p>
      </>}
    </Panel>}
    {activeTab === "consistency" && <Panel className="knowledge-list-panel"><div className="panel-heading"><div><h3>跨渠道一致性</h3><p>未跟版、渠道/发布异常、内容与已批准事实的冲突；只报差异，不自动改稿</p></div>{consistency && <Badge tone={consistency.summary.fact_conflicts + consistency.summary.channel_anomalies_high ? "amber" : "green"}>{consistency.summary.fact_conflicts + consistency.summary.stale_derivations + consistency.summary.channel_anomalies} 项待看</Badge>}</div>
      {consistencyError && <p className="form-error" role="alert">一致性检查暂不可用：{consistencyError}</p>}
      {consistency && <>
        <div className="stats-cards">
          <div><span>已扫描内容</span><strong>{consistency.summary.contents_scanned}</strong><small className="stats-card-hint">只算审核中/已批准/待发布/已发布</small></div>
          <div><span>事实冲突</span><strong>{consistency.summary.fact_conflicts}</strong><small className="stats-card-hint">电话/金额/地址片段</small></div>
          <div><span>未跟版渠道稿</span><strong>{consistency.summary.stale_derivations}</strong><small className="stats-card-hint">母稿已更新但渠道稿没同步</small></div>
          <div><span>渠道/发布异常</span><strong>{consistency.summary.channel_anomalies}</strong><small className="stats-card-hint">其中高优先级 {consistency.summary.channel_anomalies_high} 项</small></div>
        </div>
        <div className="stats-viz-head"><div><h4>内容与权威事实冲突</h4><p>只自动比对电话、金额、地址片段；组织名、服务范围仍需人工复核</p></div><span className="stats-viz-chip">{consistency.fact_conflicts.length} 条</span></div>
        <div className="table-scroll"><table><thead><tr><th>内容</th><th>类型</th><th>正文里的值</th><th>已批准事实</th><th>建议</th></tr></thead><tbody>
          {consistency.fact_conflicts.map((item, index) => <tr key={`${item.version_id}-${item.code}-${index}`}>
            <td><strong>{item.title}</strong><p className="muted">{item.channel_name ?? "母稿"}</p></td>
            <td><Badge tone={item.severity === "high" ? "red" : "amber"}>{item.code === "contact_mismatch" ? "电话" : item.code === "fee_mismatch" ? "金额" : "地址待确认"}</Badge></td>
            <td>{item.found}</td>
            <td className="muted">{item.fact_value ?? "—"}</td>
            <td>{item.message}<p className="muted">{item.recommended_action}</p></td>
          </tr>)}
        </tbody></table>{!consistency.fact_conflicts.length && <p className="knowledge-empty">未发现电话、金额或地址片段冲突。</p>}</div>
        <div className="stats-viz-head"><div><h4>未跟版渠道稿</h4><p>母稿当前版本已变化，渠道稿的改编来源哈希未同步</p></div><span className="stats-viz-chip">{consistency.stale_derivations.length} 条</span></div>
        <div className="table-scroll"><table><thead><tr><th>渠道稿</th><th>母稿</th><th>渠道</th><th>状态</th></tr></thead><tbody>
          {consistency.stale_derivations.map((item) => <tr key={item.id}>
            <td><strong>{item.channel_item_title ?? item.channel_item_id}</strong></td>
            <td>{item.master_item_title ?? item.master_item_id}{item.master_version_no ? ` · v${item.master_version_no}` : ""}</td>
            <td>{item.channel_name ?? "—"}</td>
            <td><Badge tone="amber">未跟版</Badge><p className="muted">渠道稿 {item.version_status ?? "—"} · 母稿 {item.item_status ?? "—"}</p></td>
          </tr>)}
        </tbody></table>{!consistency.stale_derivations.length && <p className="knowledge-empty">没有未跟版的渠道稿。</p>}</div>
        <div className="stats-viz-head"><div><h4>渠道台账与发布回执异常</h4><p>复用现有渠道异常口径；高优先级先处理</p></div><span className="stats-viz-chip">{consistency.channel_anomalies.length} 条</span></div>
        <div className="table-scroll"><table><thead><tr><th>渠道</th><th>异常</th><th>建议</th></tr></thead><tbody>
          {consistency.channel_anomalies.map((item, index) => <tr key={`${item.code}-${item.task_id ?? item.channel_id}-${index}`}>
            <td><strong>{item.channel_name}</strong><p className="muted">{item.channel_code} · {item.channel_status}</p></td>
            <td><Badge tone={item.severity === "high" ? "red" : "amber"}>{item.severity === "high" ? "高" : "提示"}</Badge><p>{item.message}</p></td>
            <td>{item.recommended_action}</td>
          </tr>)}
        </tbody></table>{!consistency.channel_anomalies.length && <p className="knowledge-empty">渠道台账与发布回执一致。</p>}</div>
        <p className="viz-footnote">{consistency.notes.join(" ")}</p>
      </>}
    </Panel>}
  </div>;
}