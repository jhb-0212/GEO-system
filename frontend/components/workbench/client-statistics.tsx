"use client";

import { useEffect, useState } from "react";

import { workbenchClient } from "@/lib/workbench/client";
import type { Section, SentimentSummaryRecord, StatsAnswerKindOverview, StatsOverview, WorkbenchSnapshot } from "@/lib/workbench/types";
import { Badge, Button, Icon, Panel } from "../ui";

function percent(value: number | null | undefined) {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
}

export function ClientStatistics({
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
  const [overview, setOverview] = useState<StatsOverview | null>(null);
  const [answerKinds, setAnswerKinds] = useState<StatsAnswerKindOverview[]>([]);
  const [sentiment, setSentiment] = useState<SentimentSummaryRecord | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!focusProjectId) return;
    let alive = true;
    setError("");
    Promise.all([
      workbenchClient.statsOverview(focusProjectId),
      workbenchClient.statsOverviewByAnswerKind(focusProjectId),
      workbenchClient.sentimentSummary(focusProjectId).catch(() => null),
    ]).then(([value, kinds, tone]) => {
      if (!alive) return;
      setOverview(value);
      setAnswerKinds(kinds);
      setSentiment(tone);
    }).catch((cause) => {
      if (alive) setError(cause instanceof Error ? cause.message : "统计数据加载失败");
    });
    return () => { alive = false; };
  }, [focusProjectId]);

  const mentionRate = overview?.brand_mention_rate ?? snapshot.brandMentionRate ?? null;
  const sentimentLabeled = sentiment ? sentiment.counts.positive + sentiment.counts.neutral + sentiment.counts.negative : 0;
  const enoughSentiment = sentimentLabeled >= 5;
  const positiveRate = enoughSentiment ? sentiment!.counts.positive / sentimentLabeled : null;
  const metrics = [
    { label: "品牌提及率", value: percent(mentionRate), note: overview ? `${overview.brand_mentioned_answers} / ${overview.valid_answers} 条有效回答` : "统计中" },
    { label: "内容被引用率", value: percent(overview?.citation_rate), note: overview ? `${overview.citation_answers} 条回答引用了品牌内容` : "统计中" },
    { label: "品牌推荐率", value: percent(overview?.brand_recommendation_rate), note: overview?.brand_recommendation_rate === null || overview?.brand_recommendation_rate === undefined ? "样本不足，暂不计算" : `AI 主动推荐 ${overview?.brand_recommended_answers ?? 0} 条` },
    { label: "竞品同场占比", value: percent(overview?.answer_share), note: overview?.answer_share === null || overview?.answer_share === undefined ? "样本不足，暂不计算" : "和竞品同题出现时的占比" },
  ];
  const answerCards = [
    { title: "生成式回答", description: "用户直接问 AI，AI 自己组织一段回答", kind: "answer" },
    { title: "搜索结果", description: "AI 搜索先列出网页结果，再给简要回答", kind: "search_result" },
  ].map((item) => ({ ...item, data: answerKinds.find((record) => record.answer_kind === item.kind) ?? null }));

  return <div className="client-page">
    <Panel className="client-insight-strip">
      <span className="client-insight-icon"><Icon name="spark" size={22}/></span>
      <div>
        <strong>{mentionRate === null ? "品牌表现还在建立基线" : mentionRate >= 0.3 ? "品牌已经稳定进入 AI 回答" : mentionRate >= 0.1 ? "品牌已经出现在一部分 AI 回答里" : "品牌在 AI 回答里仍然偏弱"}</strong>
        <p>{mentionRate === null ? "当前有效样本不足，先完成下一轮采集。" : `当前每 100 条有效回答，约有 ${Math.round(mentionRate * 100)} 条提到品牌；其中被引用的内容还少，优先补高意图问题的可引用内容。`}</p>
      </div>
      <Button variant="secondary" onClick={() => navigate("report")}>看品牌诊断</Button>
    </Panel>

    {error && <p className="knowledge-footnote" role="alert">统计数据暂时没有取到：{error}</p>}

    <Panel className="client-stat-panel">
      <div className="client-stat-strip">
        {metrics.map((metric) => <div key={metric.label} className="client-stat-item">
          <span>{metric.label}</span>
          <strong>{metric.value}</strong>
          <small>{metric.note}</small>
        </div>)}
      </div>
    </Panel>

    <div className="client-two-col">
      <Panel className="client-detail-panel">
        <div className="client-section-head"><div><h2>不同类型的 AI 回答，表现不一样</h2><p>分开看，避免把两种回答混成一个比例</p></div></div>
        <div className="client-answer-kinds">
          {answerCards.map((item) => <div key={item.kind} className="client-answer-kind">
            <div><strong>{item.title}</strong><span>{item.description}</span></div>
            <div className="client-answer-rate"><strong>{item.data ? percent(item.data.brand_mention_rate) : "—"}</strong><span>品牌提及率</span></div>
            <div className="client-answer-rate"><strong>{item.data ? percent(item.data.citation_rate) : "—"}</strong><span>内容被引用率</span></div>
          </div>)}
        </div>
      </Panel>

      <Panel className="client-detail-panel">
        <div className="client-section-head"><div><h2>AI 怎么评价你</h2><p>{sentiment ? `已复核 ${sentimentLabeled} 条提及品牌的内容` : "等待口碑样本"}</p></div><Badge tone={positiveRate !== null && positiveRate >= 0.5 ? "green" : "slate"}>{positiveRate === null ? "样本不足" : `正向 ${percent(positiveRate)}`}</Badge></div>
        {sentiment && enoughSentiment ? <div className="client-sentiment">
          <div className="client-sentiment-bar" aria-label="AI 口碑分布">
            <i style={{ width: `${(sentiment.counts.positive / sentimentLabeled) * 100}%`, background: "var(--g-positive)" }}/>
            <i style={{ width: `${(sentiment.counts.neutral / sentimentLabeled) * 100}%`, background: "var(--g-neutral)" }}/>
            <i style={{ width: `${(sentiment.counts.negative / sentimentLabeled) * 100}%`, background: "var(--g-danger)" }}/>
          </div>
          <div className="client-sentiment-legend">
            <span><i className="is-positive"/>正面 {sentiment.counts.positive}</span>
            <span><i className="is-neutral"/>中性 {sentiment.counts.neutral}</span>
            <span><i className="is-negative"/>负面 {sentiment.counts.negative}</span>
          </div>
          <button type="button" className="text-link" onClick={() => navigate("sentiment")}>看具体评价原文 <Icon name="arrowRight" size={15}/></button>
        </div> : <div className="client-empty-block"><strong>{sentimentLabeled > 0 ? `已复核 ${sentimentLabeled} 条，样本还不够` : "还没有足够的口碑样本"}</strong><span>满 5 条后再判断正负面比例，先看具体原文。</span>{sentimentLabeled > 0 && <button type="button" className="text-link" onClick={() => navigate("sentiment")}>看具体评价原文 <Icon name="arrowRight" size={14}/></button>}</div>}
      </Panel>
    </div>

    <p className="client-caliber-note">口径说明：提及率、引用率和推荐率都以有效回答为分母；推荐状态未知的样本不进入推荐率分母；不同回答类型单独计算，不合并。</p>
  </div>;
}
