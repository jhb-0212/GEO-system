"use client";

import { useEffect, useState } from "react";

import styles from "@/app/observatory/observatory.module.css";
import type { ObservatoryData, ObservatoryRange } from "@/app/observatory/observatory-data";
import { MiniRing, TrendChart } from "@/app/observatory/observatory-client";
import { Icon } from "../ui";
import type { Section } from "@/lib/workbench/types";
import type { OverviewTodo } from "./section-registry";

/**
 * 旧工作台里的「监测总览」。
 *
 * 导航、顶栏、页头全部沿用旧工作台的 app-shell，只把概览内容换成观察台的结论式信息结构。
 * 这样从总览去任何 section 都不会换壳、换 URL 根路径，也不会出现两套侧栏。
 */
export function OverviewObservatory({ projectId, navigate, todos, todoCount, todoLoading, onOpenTodos }: {
  projectId: string;
  navigate: (section: Section) => void;
  todos: OverviewTodo[];
  todoCount: number;
  todoLoading: boolean;
  onOpenTodos: () => void;
}) {
  const [data, setData] = useState<ObservatoryData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const query = projectId && projectId !== "all" ? `?project_id=${encodeURIComponent(projectId)}` : "";
    fetch(`/internal/observatory${query}`, { cache: "no-store" })
      .then(async (response) => {
        const payload = await response.json().catch(() => null);
        if (!response.ok) throw new Error(payload?.error?.message ?? "概览读取失败");
        if (active) setData(payload?.data ?? null);
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : "概览读取失败");
      });
    return () => { active = false; };
  }, [projectId]);

  if (error) {
    return <div className={styles.embedded}>
      <div className={`${styles.insight} ${styles.emptyInsight}`}>
        <div className={styles.insightHead}><span className={styles.insightKicker}><i />监测总览</span></div>
        <p className={styles.statement}>概览暂时读不出来。</p>
        <p className={styles.caliber}>{error}。下面的导航和任务数据不受影响，可以先从「监测任务」或「诊断报告」开始。</p>
      </div>
    </div>;
  }

  if (!data) {
    return <div className={styles.embedded}>
      <div className={`${styles.insight} ${styles.emptyInsight}`}>
        <div className={styles.insightHead}><span className={styles.insightKicker}><i />正在读取本轮结论</span></div>
        <p className={styles.statement}>把回答、链接和缺口先收拢到一页。</p>
        <p className={styles.caliber}>读取当前项目的有效回答与引用数据，马上回来。</p>
      </div>
    </div>;
  }

  const rangeMeta: ObservatoryRange | undefined = data.ranges.find((item) => item.days === 30) ?? data.ranges[0];
  const mentioned = data.mentionedAnswers;
  const cited = data.citedAnswers;
  const broken = data.mentions.filter((row) => row.status === "链接失效").length;
  const onlyMentioned = Math.max(0, mentioned - cited - broken);
  const absent = Math.max(0, data.totalAnswers - mentioned);
  const engineTotal = data.engines.reduce((total, engine) => total + engine.count, 0);
  const engineMax = Math.max(1, ...data.engines.map((engine) => engine.count));
  const sourceMax = Math.max(1, ...data.sources.map((source) => source.share));
  const sourceTopShare = data.sources.reduce((total, source) => total + source.share, 0);
  const otherSites = Math.max(0, data.sourcesCount - data.sources.length);
  const otherShare = Math.max(0, 100 - sourceTopShare);

  return <div className={`${styles.shell} ${styles.embedded}`}>
    <div className={styles.dashboard}>
      <section className={styles.insight}>
        <div className={styles.insightHead}>
          <span className={styles.insightKicker}><i />本轮结论 / 近 30 天</span>
          <span className={styles.badge}>{data.projectName} · {data.totalAnswers} 条可用回答</span>
        </div>
        <p className={styles.statement}>AI 在 <span>{data.totalAnswers}</span> 条回答里，<br />提到你 <em>{mentioned}</em> 次。</p>
        <div className={styles.insightFoot}>
          <div className={styles.metrics}>
            <div><MiniRing value={data.mentionRate} /><span><b>{data.mentionRate}%</b><strong>提到你的回答</strong><small>{data.totalAnswers} 条里 {mentioned} 条</small></span></div>
            <div><MiniRing value={data.citeRate} /><span><b>{data.citeRate}%</b><strong>回答带链接</strong><small>{data.totalAnswers} 条里 {cited} 条</small></span></div>
            <div><MiniRing value={data.competitorTogether} zero={data.competitorTogether === 0} /><span><b>{data.competitorTogether}</b><strong>竞品也在</strong><small>{data.totalAnswers} 条里 {data.competitorTogether} 条</small></span></div>
          </div>
          <p className={styles.caliber}>占比按 <b>{data.totalAnswers} 条可用回答</b>算；没查成功的 {data.excludedFailed} 条先不计入{data.brandAnswers > 0 ? `。另外 ${data.brandAnswers} 条直接搜品牌的问题另算` : ""}。</p>
        </div>
      </section>

      <aside className={styles.actions}>
        <div className={styles.panelHead}><div><h2>待办 {todoCount}</h2><p>跨审核、发布、采集与知识</p></div><span className={styles.countBadge}>{todoLoading ? "…" : `${todoCount} 件`}</span></div>
        {todos.length > 0
          ? <div className={styles.actionList}>{todos.map((item, index) => <button type="button" key={item.key} onClick={() => navigate(item.section)}>
            <span>{String(index + 1).padStart(2, "0")}</span><span><strong>{item.title}</strong><small>{item.group} · {item.meta}</small></span><Icon name="arrowUp" size={15} />
          </button>)}</div>
          : <div className={styles.actionEmpty}><p>当前没有需要人工处理的待办。</p><small>监测、审核和发布任务都已清空。</small></div>}
        <div className={styles.actionFoot}><span>上一轮检查 {data.updatedAt.split(" ").slice(-1)[0]}</span><button type="button" onClick={onOpenTodos}>打开待办中心 <Icon name="arrowRight" size={14} /></button></div>
      </aside>

      <section className={styles.trend}>
        <div className={styles.panelHead}><div><h2>最近有多少条回答提到你</h2><p>{rangeMeta?.label}</p></div><div className={styles.legend}><span><i />提到你</span><span><i className={styles.alt} />带链接</span></div></div>
        {rangeMeta && <TrendChart range={rangeMeta} />}
        <div className={styles.trendFoot}><span>最多的是 <b>{rangeMeta?.peakLabel ?? "—"}</b>，来自「{rangeMeta?.peakSource ?? "还没有提到你的回答"}」</span><span className={styles.delta}>按时间段汇总，不估算</span></div>
      </section>

      <section className={styles.sources}>
        <div className={styles.panelHead}><div><h2>AI 从哪些网站找到你</h2><p>{data.sourceLabel}</p></div><button type="button" className={styles.iconBtn} aria-label="查看渠道台账" onClick={() => navigate("channels")}><Icon name="more" size={18} /></button></div>
        <div className={styles.sourceList}>{data.sources.map((source, index) => <div key={source.name} className={styles.sourceRow}>
          <span>{String(index + 1).padStart(2, "0")}</span><strong>{source.name}</strong><i><b style={{ width: `${Math.max(6, (source.share / sourceMax) * 100)}%` }} /></i><em>{source.share}%</em>
        </div>)}</div>
        {otherSites > 0 && otherShare > 0 && <p className={styles.sourceNote}>其余 {otherSites} 个网站比较分散，合计 {otherShare}%。</p>}
        <div className={styles.engineChart}>
          <div className={styles.engineHead}><span>四个 AI 平台各答了多少</span><span>共 {engineTotal} 条</span></div>
          <div className={styles.engineBars}>{data.engines.map((engine) => <div key={engine.name}><i style={{ height: `${Math.max(6, (engine.count / engineMax) * 40)}px` }} /><span>{engine.name} <b>{engine.count}</b></span></div>)}</div>
        </div>
      </section>
    </div>
    <div className={styles.notice}><Icon name="info" size={18} /><span><b>{data.noticeTitle}</b>{data.noticeNote}</span><button type="button" onClick={() => navigate("samples")}>看回答明细 <Icon name="arrowRight" size={14} /></button></div>
    <div className={styles.embeddedFoot}>
      <span>没提到 {absent} 条 · 只提到 {onlyMentioned} 条 · 带链接 {cited} 条</span>
      <button type="button" onClick={() => navigate("report")}>打开诊断报告 <Icon name="arrowRight" size={14} /></button>
    </div>
  </div>;
}
