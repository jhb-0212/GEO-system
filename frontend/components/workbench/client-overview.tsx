"use client";

import { useEffect, useState } from "react";

import { workbenchClient } from "@/lib/workbench/client";
import { formatIsoDate } from "@/lib/workbench/format";
import type { Section, SampleDetail, StatsOverview, WorkbenchSnapshot } from "@/lib/workbench/types";
import { Badge, Button, Icon, Panel } from "../ui";
import { TrendChart } from "./shared";

function percent(value: number | null | undefined) {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
}

function sampleDate(value: string | null | undefined) {
  return value ? value.slice(0, 10) : "";
}

function cleanAnswer(text: string) {
  return text
    .replace(/\r\n/g, "\n")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/^\s*[📍📝📷🖼️]+\s*/gmu, "")
    .replace(/^\s*-\s+/gm, "· ")
    .replace(/1[3-9]\d{9}/g, "［手机号已隐去］")
    .replace(/\n{3,}/g, "\n\n");
}

function answerHeadline(sample: SampleDetail) {
  const line = cleanAnswer(sample.raw_answer || sample.answer_excerpt || "")
    .split("\n")
    .map((item) => item.trim())
    .find(Boolean);
  return line ? line.slice(0, 72) : "AI 回答样本";
}

function AnswerExcerpt({ sample }: { sample: SampleDetail }) {
  const text = sample.raw_answer || sample.answer_excerpt || "";
  if (!text) return <div className="client-answer-text">这条回答没有可展示的正文。</div>;
  const blocks = cleanAnswer(text)
    .replace(/\n(?=[^\n]{1,12}\n)/g, "\n\n")
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (!blocks.length) return <div className="client-answer-text">这条回答没有可展示的正文。</div>;
  const term = sample.brand_match_term?.trim() || "";
  const brandBlock = term ? blocks.findIndex((block) => block.includes(term)) : -1;
  const first = brandBlock > 2 ? brandBlock - 1 : 0;
  const picked = blocks.slice(first, first + 3);
  return <div className="client-answer-text">
    {first > 0 ? "…" : ""}
    {picked.map((block) => {
      const index = term ? block.indexOf(term) : -1;
      return <p key={block}>
        {index >= 0 ? <>
          {block.slice(0, index)}
          <mark>{term}</mark>
          {block.slice(index + term.length)}
        </> : block}
      </p>;
    })}
  </div>;
}

function visibilityState(rate: number | null) {
  if (rate === null) return { label: "样本积累中", tone: "slate" as const, advice: "当前有效样本还不足以判断趋势，下一轮采集完成后再看变化。" };
  if (rate >= 0.3) return { label: "表现稳定", tone: "green" as const, advice: "品牌已经稳定进入一部分 AI 回答，接下来重点看推荐位和竞品差距。" };
  if (rate >= 0.1) return { label: "已有存在感", tone: "blue" as const, advice: "品牌已经能被部分 AI 回答提及，继续补齐高意图问题下的可引用内容。" };
  return { label: "需要加强", tone: "amber" as const, advice: "品牌在 AI 回答中还偏弱，优先处理用户真正会问、但 AI 没有提到你的问题。" };
}

export function ClientOverview({
  snapshot,
  projectId,
  navigate,
}: {
  snapshot: WorkbenchSnapshot;
  projectId: string;
  navigate: (section: Section) => void;
}) {
  const focusProjectId = projectId === "all" ? snapshot.activeProjectId ?? snapshot.projects[0]?.id ?? "" : projectId;
  const project = snapshot.projects.find((item) => item.id === focusProjectId) ?? snapshot.projects[0];
  const projectTitle = project?.name ?? "当前品牌";
  const [stats, setStats] = useState<StatsOverview | null>(null);
  const [statsError, setStatsError] = useState("");
  const [sample, setSample] = useState<SampleDetail | null>(null);
  const [sampleLoading, setSampleLoading] = useState(false);
  const trendDates = snapshot.trendDates ?? [];
  const trendValues = snapshot.trend.slice(-14);
  const chartDates = trendDates.slice(-14);
  const activeDays = trendValues.filter((value) => value !== null).length;

  useEffect(() => {
    if (!focusProjectId) return;
    let alive = true;
    setStatsError("");
    workbenchClient.statsOverview(focusProjectId)
      .then((value) => { if (alive) setStats(value); })
      .catch((cause) => { if (alive) setStatsError(cause instanceof Error ? cause.message : "统计数据加载失败"); });
    setSampleLoading(true);
    workbenchClient.samples(focusProjectId)
      .then((page) => {
        const items = [...page.data].sort((a, b) => (b.sampled_at ?? "").localeCompare(a.sampled_at ?? ""));
        const candidate = items.find((item) => (item.raw_answer || item.answer_excerpt) && item.brand_mentioned)
          ?? items.find((item) => item.raw_answer || item.answer_excerpt);
        if (!candidate) return null;
        return workbenchClient.sample(focusProjectId, candidate.id);
      })
      .then((value) => {
        if (alive) setSample(value ?? null);
      })
      .catch(() => { if (alive) setSample(null); })
      .finally(() => { if (alive) setSampleLoading(false); });
    return () => { alive = false; };
  }, [focusProjectId]);

  const mentionRate = stats?.brand_mention_rate ?? snapshot.brandMentionRate ?? null;
  const state = visibilityState(mentionRate);
  const hasCompetitor = (stats?.competitor_entity_mentions ?? 0) > 0;
  const nextActions = [
    {
      title: "先补 3 个高意图问题",
      detail: `当前提及率 ${percent(mentionRate)}；优先处理用户真会问、但 AI 还没提到你的问题。`,
      cta: "看品牌诊断",
      section: "report" as Section,
    },
    {
      title: "让内容更容易被 AI 引用",
      detail: `当前引用率 ${percent(stats?.citation_rate)}；把官网核心页改成问答式和结构化表述。`,
      cta: "看引用明细",
      section: "statistics" as Section,
    },
    {
      title: "补齐口碑样本再下结论",
      detail: "复核满 5 条提及内容后，再判断 AI 对品牌的正面、中性和负面评价。",
      cta: "去 AI 口碑",
      section: "sentiment" as Section,
    },
  ];

  const brandCitations = sample?.citations?.filter((item) => item.is_brand_related).length ?? 0;
  const brandPosition = sample?.brand_match_offset != undefined ? (sample.brand_match_offset < 80 ? "回答开头" : "回答中段") : "回答里";

  return <div className="client-page">
    <Panel className="client-diagnosis">
      <div className="client-diagnosis-copy">
        <p className="eyebrow">过去 14 天 · {projectTitle}</p>
        <h1>{stats ? <>AI 在 {stats.valid_answers} 条回答里，提到你 {stats.brand_mentioned_answers} 次。</> : "正在整理 AI 对你的回答。"}</h1>
        <p className="client-diagnosis-lead">{stats ? <>内容被引用 <strong>{stats.citation_answers}</strong> 次；竞品同场份额 <strong>{hasCompetitor ? percent(stats.answer_share) : "暂不可计算"}</strong>。{state.advice}</> : state.advice}</p>
        <div className="client-diagnosis-actions">
          <Button onClick={() => navigate("report")}>看完整诊断 <Icon name="arrowRight" size={15}/></Button>
        </div>
      </div>
      <div className="client-diagnosis-facts">
        <button type="button" onClick={() => navigate("statistics")}><strong>{stats?.brand_mentioned_answers ?? "—"}</strong><span>条回答提到品牌</span><small>{stats ? `占 ${stats.valid_answers} 条的 ${percent(mentionRate)}` : "正在统计"}</small></button>
        <button type="button" onClick={() => navigate("statistics")}><strong>{stats?.citation_answers ?? "—"}</strong><span>条回答引用你的内容</span><small>{stats ? `占 ${stats.valid_answers} 条的 ${percent(stats.citation_rate)}` : "正在统计"}</small></button>
        <button type="button" onClick={() => navigate("competitors")}><strong>{hasCompetitor ? percent(stats?.answer_share) : "—"}</strong><span>竞品同场份额</span><small>{hasCompetitor ? "和竞品出现在同一个回答里" : "还没有竞品样本"}</small></button>
      </div>
    </Panel>

    {statsError && <p className="knowledge-footnote" role="alert">统计数据暂时没有取到：{statsError}。页面趋势仍按已同步数据展示。</p>}

    <div className="client-evidence-grid">
      <Panel className="client-answer-panel">
        <div className="client-section-head">
          <div><h2>AI 实际是怎么回答的</h2><p>抽一条最近的回答，直接看品牌有没有出现、出现在哪</p></div>
          {sample && <Badge tone={sample.brand_mentioned ? "green" : "amber"} dot>{sample.brand_mentioned ? "提到了品牌" : "没有提到品牌"}</Badge>}
        </div>
        {sampleLoading ? <div className="client-empty-block"><strong>正在找一条真实回答…</strong></div> : sample ? <div className="client-answer-layout">
          <div className="client-answer-main">
            <div className="client-answer-meta">
              <span>{answerHeadline(sample)}</span>
              <span>AI 回答{sample.sampled_at ? ` · ${sampleDate(sample.sampled_at)}` : ""}</span>
            </div>
            <AnswerExcerpt sample={sample}/>
            <p className="client-answer-foot">{sample.brand_mentioned ? "这条回答里出现了品牌，可以作为正向样本复盘。" : "这条回答没有出现品牌，说明这个问题下的内容还需要补。"}</p>
          </div>
          <aside className="client-answer-aside">
            <p className="eyebrow">这条样本说明</p>
            <strong>{sample.brand_mentioned ? "AI 已经把这个问题和你的品牌对上了" : "这个问题下，AI 还没有找到你"}</strong>
            <ul>
              <li>品牌出现在{brandPosition}</li>
              <li>{sample.brand_match_term ? `AI 用「${sample.brand_match_term}」称呼你` : "回答里识别到了品牌"}</li>
              <li>{brandCitations > 0 ? `引用了 ${brandCitations} 个品牌相关来源` : "这条回答没有引用你的内容"}</li>
            </ul>
            <Button variant="secondary" onClick={() => navigate("statistics")}>看更多回答 <Icon name="arrowRight" size={14}/></Button>
          </aside>
        </div> : <div className="client-empty-block client-empty-wide">
          <strong>还没有可展示的回答</strong>
          <span>完成下一轮监测后，这里会展示一条真实 AI 回答，并标出品牌出现的位置。</span>
        </div>}
      </Panel>

      <Panel className="client-next-panel">
        <div className="client-section-head"><div><h2>下一步，做这三件事</h2><p>按对品牌结果的影响排序</p></div></div>
        <div className="client-next-list">
          {nextActions.map((action, index) => <div className="client-next-item" key={action.title}>
            <span className="client-next-number">{String(index + 1).padStart(2, "0")}</span>
            <div><strong>{action.title}</strong><p>{action.detail}</p><button type="button" className="text-link" onClick={() => navigate(action.section)}>{action.cta} <Icon name="arrowRight" size={14}/></button></div>
          </div>)}
        </div>
      </Panel>
    </div>

    <Panel className="client-trend-panel">
      <div className="client-section-head">
        <div><h2>近 14 天，AI 回答里提到品牌的趋势</h2><p>{chartDates[0] && chartDates.at(-1) ? `${formatIsoDate(chartDates[0])} 至 ${formatIsoDate(chartDates.at(-1))} · 有 ${activeDays} 天有效回答` : "按有效回答逐日统计"}</p></div>
        <Badge tone={state.tone}>{state.label}</Badge>
      </div>
      {trendValues.some((value) => value !== null) ? <TrendChart values={trendValues} dates={chartDates} days={trendValues.length}/> : <div className="client-empty-trend"><Icon name="pulse" size={22}/><strong>还没有足够的有效回答</strong><span>完成下一轮采集后，这里会显示品牌提及率变化。</span></div>}
      <p className="client-trend-note">解读：目前只有 {activeDays} 天有有效回答，先看方向，不把单日波动当成结论。</p>
    </Panel>

    <p className="client-caliber-note">口径说明：只统计有效回答；样本不足时推荐率和答案份额显示「—」，不做估算。趋势只画有有效回答的日期，单日样本少时波动会被放大。统计窗口按项目所在时区的自然日计算。</p>
  </div>;
}
