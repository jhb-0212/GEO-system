"use client";

import { useEffect, useState } from "react";

import { workbenchClient } from "@/lib/workbench/client";
import type { AlertEventRecord, Lead, MonthlyReport, SentimentItemRecord, SentimentSummaryRecord, StatsOverview } from "@/lib/workbench/types";
import { Badge, Button, Icon, Panel } from "../ui";

function percent(value: number | null | undefined) {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
}

function dateText(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value.slice(0, 10) : date.toLocaleDateString("zh-CN");
}

function EmptyHow({ steps }: { steps: { title: string; detail: string }[] }) {
  return <div className="client-empty-how">
    {steps.map((step, index) => <div className="client-empty-step" key={step.title}>
      <span>{index + 1}</span>
      <strong>{step.title}</strong>
      <p>{step.detail}</p>
    </div>)}
  </div>;
}

export function ClientSentiment({ projectId, navigate }: { projectId: string; navigate: (section: "statistics" | "report") => void }) {
  const [summary, setSummary] = useState<SentimentSummaryRecord | null>(null);
  const [items, setItems] = useState<SentimentItemRecord[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!projectId || projectId === "all") return;
    let alive = true;
    Promise.all([
      workbenchClient.sentimentSummary(projectId),
      workbenchClient.sentimentItems(projectId, { page_size: "20" }).catch(() => ({ data: [] as SentimentItemRecord[], meta: { page: 1, page_size: 20, total: 0 } })),
    ]).then(([value, list]) => {
      if (!alive) return;
      setSummary(value);
      setItems(list.data.filter((item) => item.polarity));
      setError("");
    }).catch((cause) => { if (alive) setError(cause instanceof Error ? cause.message : "口碑数据加载失败"); });
    return () => { alive = false; };
  }, [projectId]);

  const labeled = summary ? summary.counts.positive + summary.counts.neutral + summary.counts.negative : 0;
  const enough = labeled >= 5;

  return <div className="client-page">
    <Panel className="client-detail-panel">
      <div className="client-section-head"><div><h2>AI 回答里，品牌被怎样评价</h2><p>只统计已经人工复核过的提及内容，未复核的不下结论</p></div>{summary && <Badge tone={enough ? "green" : "amber"}>{enough ? `已复核 ${labeled} 条` : "样本积累中"}</Badge>}</div>
      {error && <p className="knowledge-footnote">{error}</p>}
      {summary && !enough ? <div className="client-empty-block client-empty-wide">
        <strong>口碑样本还在积累</strong>
        <span>已经抓取 {summary.total_reviewed_citations} 条提及内容，其中 {labeled} 条完成复核；样本达到 5 条后再展示正负面比例，避免用一两条样本下结论。</span>
        <div className="client-empty-metrics">
          <div><strong>{summary.total_reviewed_citations}</strong><span>已抓取提及</span></div>
          <div><strong>{labeled}</strong><span>已复核</span></div>
          <div><strong>5</strong><span>展示所需样本</span></div>
        </div>
        <EmptyHow steps={[
          { title: "回答入库", detail: "每条 AI 回答里提到品牌的段落自动收进来" },
          { title: "人工复核", detail: "判断这段是在夸、在贬，还是只是提到" },
          { title: "满 5 条出结论", detail: "样本够了才展示正负面比例，避免误判" },
        ]}/>
        <div className="client-empty-actions">
          <Button variant="secondary" onClick={() => navigate("statistics")}>看 AI 可见度</Button>
          <Button variant="quiet" onClick={() => navigate("report")}>看品牌诊断</Button>
        </div>
      </div> : summary ? <>
        <div className="client-sentiment">
          <div className="client-sentiment-bar">
            <i style={{ width: `${(summary.counts.positive / labeled) * 100}%`, background: "var(--g-positive)" }}/>
            <i style={{ width: `${(summary.counts.neutral / labeled) * 100}%`, background: "var(--g-neutral)" }}/>
            <i style={{ width: `${(summary.counts.negative / labeled) * 100}%`, background: "var(--g-danger)" }}/>
          </div>
          <div className="client-sentiment-legend">
            <span><i className="is-positive"/>正面 {summary.counts.positive}</span>
            <span><i className="is-neutral"/>中性 {summary.counts.neutral}</span>
            <span><i className="is-negative"/>负面 {summary.counts.negative}</span>
          </div>
        </div>
        <div className="client-quote-list">
          {items.slice(0, 8).map((item) => <div key={item.citation_id} className="client-quote">
            <Badge tone={item.polarity === "positive" ? "green" : item.polarity === "negative" ? "red" : "slate"}>{item.polarity === "positive" ? "正面" : item.polarity === "negative" ? "负面" : "中性"}</Badge>
            <strong>{item.title || item.domain || "AI 引用内容"}</strong>
            {item.excerpt && <p>{item.excerpt}</p>}
            <span>{item.domain} · {dateText(item.published_at)}</span>
          </div>)}
        </div>
      </> : null}
    </Panel>
  </div>;
}

export function ClientCompetitors({ projectId, navigate }: { projectId: string; navigate: () => void }) {
  const [overview, setOverview] = useState<StatsOverview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!projectId || projectId === "all") return;
    let alive = true;
    workbenchClient.statsOverview(projectId)
      .then((value) => { if (alive) { setOverview(value); setError(""); } })
      .catch((cause) => { if (alive) setError(cause instanceof Error ? cause.message : "竞品数据加载失败"); });
    return () => { alive = false; };
  }, [projectId]);

  const competitorMentions = overview?.competitor_entity_mentions ?? 0;
  const brandMentions = overview?.brand_entity_mentions ?? 0;
  const hasCompetitor = competitorMentions > 0;

  return <div className="client-page">
    <Panel className="client-detail-panel">
      <div className="client-section-head"><div><h2>和竞品一起出现时，谁更容易被 AI 提到</h2><p>按 AI 回答里出现的品牌和竞品实体次数计算，不合并成投票结果</p></div><Badge tone={hasCompetitor ? "blue" : "slate"}>{hasCompetitor ? "有竞品样本" : "暂无竞品样本"}</Badge></div>
      {error && <p className="knowledge-footnote">{error}</p>}
      {!hasCompetitor ? <div className="client-empty-block client-empty-wide">
        <strong>当前回答里还没有识别到竞品</strong>
        <span>这不等于品牌领先，只说明这一批回答中没有出现竞品名称。继续监测后，这里会显示品牌与竞品同场出现的份额。</span>
        <div className="client-empty-metrics">
          <div><strong>{overview?.brand_mentioned_answers ?? 0}</strong><span>提到品牌的回答</span></div>
          <div><strong>0</strong><span>竞品出现次数</span></div>
          <div><strong>{overview?.valid_answers ?? 0}</strong><span>有效回答</span></div>
        </div>
        <EmptyHow steps={[
          { title: "识别竞品实体", detail: "从回答正文里认出被提到的竞品名称" },
          { title: "配对同场回答", detail: "只比较品牌和竞品同时出现的那些回答" },
          { title: "算出同场份额", detail: "样本够了再展示谁更容易被 AI 提到" },
        ]}/>
        <Button variant="secondary" onClick={navigate}>看 AI 可见度</Button>
      </div> : <div className="client-compete">
        <div className="client-compete-row"><span>品牌</span><strong>{brandMentions} 次</strong><div><i style={{ width: `${(brandMentions / (brandMentions + competitorMentions || 1)) * 100}%` }}/></div></div>
        <div className="client-compete-row"><span>竞品</span><strong>{competitorMentions} 次</strong><div><i className="is-competitor" style={{ width: `${(competitorMentions / (brandMentions + competitorMentions || 1)) * 100}%` }}/></div></div>
        <p className="client-caliber-note">同一个回答里同时提到多方时，各方都计一次，所以份额相加可能超过 100%。</p>
      </div>}
    </Panel>
  </div>;
}

export function ClientAlerts({ projectId, navigate }: { projectId: string; navigate: (section: "statistics" | "report") => void }) {
  const [events, setEvents] = useState<AlertEventRecord[]>([]);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!projectId || projectId === "all") return;
    let alive = true;
    workbenchClient.alertEvents(projectId)
      .then((page) => { if (alive) { setEvents(page.data); setError(""); } })
      .catch((cause) => { if (alive) setError(cause instanceof Error ? cause.message : "提醒加载失败"); })
      .finally(() => { if (alive) setLoaded(true); });
    return () => { alive = false; };
  }, [projectId]);

  return <div className="client-page">
    <Panel className="client-detail-panel">
      <div className="client-section-head"><div><h2>值得你关注的变化</h2><p>我们持续盯着提及、推荐、竞品和负面评价的异常波动</p></div><Badge tone={events.length ? "amber" : "green"}>{loaded ? `${events.length} 条变化` : "加载中"}</Badge></div>
      {error && <p className="knowledge-footnote">{error}</p>}
      {loaded && !events.length ? <div className="client-empty-block client-empty-wide">
        <strong>目前没有需要你关注的变化</strong>
        <span>当品牌提及率、推荐率明显下降，或竞品反超、负面评价上升时，这里会出现提醒。</span>
        <div className="client-monitor-tags">
          <span>品牌提及率</span><span>AI 推荐率</span><span>竞品反超</span><span>负面评价</span>
        </div>
        <EmptyHow steps={[
          { title: "每天对比基线", detail: "拿最近一轮结果和过去 7 天平均比" },
          { title: "越过阈值才提醒", detail: "小幅波动不打扰，明显下降或反超才出现" },
          { title: "点开看前后变化", detail: "每条提醒都带触发时间和相关回答" },
        ]}/>
        <div className="client-empty-actions">
          <Button variant="secondary" onClick={() => navigate("statistics")}>看当前 AI 表现</Button>
          <Button variant="quiet" onClick={() => navigate("report")}>看诊断结论</Button>
        </div>
      </div> : <div className="client-alert-list">
        {events.map((event) => <div key={event.id} className="client-alert">
          <Badge tone={event.severity === "critical" ? "red" : "amber"}>{event.severity === "critical" ? "重要" : "关注"}</Badge>
          <div><strong>{event.title}</strong><p>{event.message}</p><span>{dateText(event.triggered_at)}</span></div>
        </div>)}
      </div>}
    </Panel>
  </div>;
}

export function ClientMonthly({ projectId, canDownload }: { projectId: string; canDownload: boolean }) {
  const [report, setReport] = useState<MonthlyReport | null>(null);
  const [error, setError] = useState("");
  const month = new Date().toLocaleDateString("sv-SE").slice(0, 7);

  useEffect(() => {
    if (!projectId || projectId === "all") return;
    let alive = true;
    workbenchClient.statsMonthly(projectId, month)
      .then((value) => { if (alive) { setReport(value); setError(""); } })
      .catch((cause) => { if (alive) setError(cause instanceof Error ? cause.message : "月报加载失败"); });
    return () => { alive = false; };
  }, [projectId, month]);

  const general = report?.answer_breakdown?.general ?? null;
  const brand = report?.answer_breakdown?.brand ?? null;
  const answer = report?.answers ?? null;
  const leads = report?.leads ?? null;

  return <div className="client-page">
    <Panel className="client-insight-strip">
      <span className="client-insight-icon"><Icon name="calendar" size={22}/></span>
      <div><strong>{month.replace("-", " 年 ")} 月品牌表现</strong><p>按月汇总 AI 回答、品牌提及和咨询转化，可直接用于对内复盘或对外汇报。</p></div>
      {canDownload && <Button variant="secondary" icon="download" onClick={() => workbenchClient.downloadMonthlyReport(projectId, month)}>下载月报</Button>}
    </Panel>
    {error && <p className="knowledge-footnote">{error}</p>}
    {report && <div className="client-two-col">
      <Panel className="client-detail-panel">
        <div className="client-section-head"><div><h2>用户不知道你时，AI 会不会主动提到</h2><p>自然提问 · {general?.valid_answers ?? report.answers.valid_answers} 条有效回答</p></div></div>
        <div className="client-month-big">{percent(general?.brand_mention_rate ?? report.answers.brand_mention_rate)}</div>
        <p className="client-caliber-note">在用户没有直接点名品牌的问题里，AI 主动提到品牌的占比。</p>
        <div className="client-month-line"><span>内容被引用率</span><strong>{percent(general?.citation_rate ?? report.answers.citation_rate)}</strong></div>
      </Panel>
      <Panel className="client-detail-panel">
        <div className="client-section-head"><div><h2>用户直接问你时，AI 说得准不准</h2><p>品牌验证 · {brand?.valid_answers ?? 0} 条有效回答</p></div></div>
        <div className="client-month-big">{percent(brand?.brand_mention_rate ?? null)}</div>
        <p className="client-caliber-note">用户直接点名品牌时，AI 回答里出现品牌的占比；识别准确率为 {percent(brand?.brand_identified_rate ?? null)}。</p>
      </Panel>
    </div>}
    {report && <Panel className="client-detail-panel">
      <div className="client-section-head"><div><h2>从 AI 回答到真实咨询</h2><p>本月咨询线索与转化</p></div></div>
      <div className="client-month-grid">
        <div><span>咨询总量</span><strong>{leads?.total ?? 0}</strong></div>
        <div><span>有效线索</span><strong>{leads?.valid ?? 0}</strong></div>
        <div><span>已联系</span><strong>{leads?.contacted ?? 0}</strong></div>
        <div><span>已转化</span><strong>{leads?.enrolled ?? 0}</strong></div>
      </div>
      <p className="client-caliber-note">有效回答 {answer?.valid_answers ?? 0} 条 · 本月新增发布 {report.published_receipts} 条</p>
    </Panel>}
  </div>;
}

export function ClientLeads({ leads, navigate }: { leads: Lead[]; navigate: (section: "statistics" | "report") => void }) {
  const visible = leads.filter((lead) => lead.isValid !== false);
  return <div className="client-page">
    <Panel className="client-detail-panel">
      <div className="client-section-head"><div><h2>从 AI 回答来的咨询</h2><p>客户看到 AI 推荐后留下的联系方式与意向</p></div><Badge tone={visible.length ? "blue" : "slate"}>{visible.length} 条有效线索</Badge></div>
      {!visible.length ? <div className="client-empty-block client-empty-wide">
        <strong>还没有收到咨询</strong>
        <span>当客户通过官网或 AI 推荐入口留下联系方式后，会出现在这里。</span>
        <EmptyHow steps={[
          { title: "AI 回答带来访问", detail: "客户从 AI 推荐里找到官网或咨询入口" },
          { title: "留下联系方式", detail: "表单提交后自动进入线索池" },
          { title: "在这里跟进", detail: "联系人、意向和来源会一起记录下来" },
        ]}/>
        <div className="client-empty-actions">
          <Button variant="secondary" onClick={() => navigate("statistics")}>看 AI 推荐表现</Button>
          <Button variant="quiet" onClick={() => navigate("report")}>看品牌诊断</Button>
        </div>
      </div> : <div className="client-lead-list">
        {visible.map((lead) => <div key={lead.id} className="client-lead">
          <div><strong>{lead.contactName || "未填写联系人"}</strong><span>{lead.interest || "未填写意向"}</span></div>
          <Badge tone={lead.status === "已转化" ? "green" : lead.status === "已流失" ? "slate" : "blue"}>{lead.status}</Badge>
          <div className="client-lead-meta"><span>{lead.source}</span><span>{dateText(lead.createdAt)}</span></div>
        </div>)}
      </div>}
    </Panel>
  </div>;
}
