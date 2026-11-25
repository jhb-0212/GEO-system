"use client";

import { useEffect, useState } from "react";

import { Badge, Button, Icon, SelectInput } from "../ui";
import { StatePlaceholder } from "../states";
import { workbenchClient } from "@/lib/workbench/client";
import type { DiagnosisDimensionRecord, DiagnosisReportRecord } from "@/lib/workbench/types";

/**
 * B6 诊断报告 / B4 五维分项数字。
 *
 * 只展示后端算好的分子、分母与样本数，不给综合评分、不做评级。
 * 分母为 0 的分项显示「无有效样本」，不用 0 假装有数据。
 */

const ANSWER_KIND_OPTIONS = [
  { value: "", label: "全部样本（融合口径）" },
  { value: "answer", label: "仅生成回答" },
  { value: "search_result", label: "仅检索结果" },
];

const CLIENT_ANSWER_KIND_OPTIONS = [
  { value: "", label: "全部回答" },
  { value: "answer", label: "生成式回答" },
  { value: "search_result", label: "搜索结果" },
];

const QUESTION_TYPE_OPTIONS = [
  { value: "", label: "全部题目" },
  { value: "general", label: "通用题（自然发现）" },
  { value: "brand", label: "品牌题（功能验证）" },
];

const CLIENT_QUESTION_TYPE_OPTIONS = [
  { value: "", label: "全部问题" },
  { value: "general", label: "自然提及的问题" },
  { value: "brand", label: "品牌验证问题" },
];

const CLIENT_DIMENSIONS: Record<string, { label: string; description: string }> = {
  mention_rate: { label: "AI 回答里提到品牌", description: "用户提问后，AI 在回答中点名提到你的频率" },
  first_rank_rate: { label: "第一个推荐品牌", description: "AI 在推荐列表里把你放在第一位的频率" },
  recommendation_rate: { label: "AI 主动推荐品牌", description: "AI 明确建议用户选择你的频率" },
  top3_rate: { label: "进入推荐前 3", description: "AI 把你放进推荐列表前三的频率" },
  source_coverage: { label: "引用内容来自你的渠道", description: "AI 引用的内容里，有多少来自品牌自己的网站或账号" },
  competitor_rank: { label: "和竞品同场时的位次", description: "和竞品出现在同一个回答里时，你排在竞品前面的频率" },
  context_quality: { label: "引用页面真的提到品牌", description: "AI 引用的页面里，有多少标题或摘要真的写了你的品牌" },
};

const CLIENT_DIMENSION_GROUPS = [
  { title: "AI 会不会提到你", description: "先确认品牌有没有进入 AI 的回答", keys: ["mention_rate"] },
  { title: "AI 会不会推荐你", description: "再看品牌在推荐、首位和前三里的位置", keys: ["first_rank_rate", "recommendation_rate", "top3_rate"] },
  { title: "引用的内容可不可信", description: "最后看 AI 引用的来源、位次和页面内容", keys: ["source_coverage", "competitor_rank", "context_quality"] },
];

function percent(value: number | null): string {
  if (value === null) return "无有效样本";
  return `${(value * 100).toFixed(1)}%`;
}

function dimensionExtra(row: DiagnosisDimensionRecord): string {
  const parts: string[] = [];
  if (row.key === "source_coverage") {
    parts.push(`品牌自有域名 ${row.extra.brand_domains ?? 0} 个 / 去重域名 ${row.extra.total_domains ?? 0} 个`);
  }
  if (row.key === "competitor_rank") {
    const brandAvg = row.extra.brand_avg;
    const competitorAvg = row.extra.competitor_avg;
    if (brandAvg !== null && brandAvg !== undefined) parts.push(`品牌平均位次 ${brandAvg}`);
    if (competitorAvg !== null && competitorAvg !== undefined) parts.push(`最优竞品平均位次 ${competitorAvg}`);
  }
  if (row.key === "context_quality") {
    const terms = Array.isArray(row.extra.terms) ? (row.extra.terms as string[]) : [];
    if (terms.length) parts.push(`匹配词：${terms.join(" / ")}`);
    const pageTypes = Array.isArray(row.extra.page_types) ? (row.extra.page_types as Array<{ page_type: string; count: number }>) : [];
    if (pageTypes.length) parts.push(`页面类型：${pageTypes.map((item) => `${item.page_type} ${item.count}`).join("、")}`);
  }
  return parts.join("；");
}

export function DiagnosisReportWorkspace({
  mode,
  projectId,
  canRead,
  canExport,
  clientMode = false,
}: {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
  canExport: boolean;
  clientMode?: boolean;
}) {
  const [report, setReport] = useState<DiagnosisReportRecord | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [answerKind, setAnswerKind] = useState("");
  const [questionType, setQuestionType] = useState("");

  const projectReady = Boolean(projectId) && projectId !== "all";
  const active = mode === "live" && canRead && projectReady;
  const filterKey = `${projectId}:${answerKind}:${questionType}`;
  const loading = active && loadedFor !== filterKey;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    workbenchClient.diagnosisReport(projectId, { answer_kind: answerKind || undefined, question_type: questionType || undefined })
      .then((record) => { if (!cancelled) { setReport(record); setError(""); } })
      .catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "诊断报告加载失败"); })
      .finally(() => { if (!cancelled) setLoadedFor(filterKey); });
    return () => { cancelled = true; };
  }, [projectId, active, answerKind, questionType, filterKey]);

  if (mode !== "live") {
    return <StatePlaceholder kind="not-collected" title="演示模式不生成诊断报告" description="报告按真实样本现算，演示数据不参与任何比率。" />;
  }
  if (!canRead) {
    return <StatePlaceholder kind="permission" title="无权查看诊断报告" description="当前账号缺少 stats.read 能力，请联系项目管理员。" />;
  }
  if (!projectReady) {
    return <StatePlaceholder kind="empty" title="请先选择项目" description="诊断报告按项目计算；在右上角选择具体项目后查看。" />;
  }
  if (loading) {
    return <StatePlaceholder kind="loading" title="正在生成诊断报告" />;
  }
  if (error) {
    return <StatePlaceholder kind="error" title="诊断报告加载失败" description={error} />;
  }
  if (!report) return null;

  const excluded = report.scope.excluded ?? {};
  const hasSamples = report.scope.valid_answers > 0;
  const readyDimensions = report.dimensions.filter((row) => row.has_data).length;
  const summaryRows = ["mention_rate", "source_coverage", "context_quality"]
    .map((key) => report.dimensions.find((row) => row.key === key))
    .filter((row): row is DiagnosisDimensionRecord => Boolean(row));
  const summaryNotes: Record<string, string> = {
    mention_rate: "先确认品牌有没有进入 AI 的回答",
    source_coverage: "再看引用有没有落在品牌自有渠道",
    context_quality: "最后确认被引页面是否真的提到品牌",
  };

  if (clientMode) {
    return <div className="client-page client-diagnosis-page">
      <div className="client-diagnosis-toolbar">
        <div className="client-toolbar-copy">
          <strong>已分析 {report.scope.valid_answers} 条回答</strong>
          <span>{hasSamples ? `7 项里有 ${readyDimensions} 项可以判断，其余先积累样本。` : "当前还没有有效样本，先完成一轮采集。"}</span>
        </div>
        <div className="client-toolbar-actions">
          <select className="client-toolbar-select" aria-label="回答类型" value={answerKind} onChange={(event) => setAnswerKind(event.target.value)}>
            {CLIENT_ANSWER_KIND_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          <select className="client-toolbar-select" aria-label="问题类型" value={questionType} onChange={(event) => setQuestionType(event.target.value)}>
            {CLIENT_QUESTION_TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          {canExport && <button type="button" className="text-link" onClick={() => {
            const query = new URLSearchParams({ project_id: projectId });
            if (answerKind) query.set("answer_kind", answerKind);
            if (questionType) query.set("question_type", questionType);
            window.open(`/internal/workbench/diagnosis/export?${query}`, "_blank");
          }}>导出明细 <Icon name="download" size={14}/></button>}
        </div>
      </div>

      {!hasSamples && <StatePlaceholder kind="empty" compact title="当前还没有有效样本" description="调整回答类型或问题类型，或先完成一轮回答采集。" />}

      <div className="client-diagnosis-groups">
        {CLIENT_DIMENSION_GROUPS.map((group) => <section className="client-diagnosis-group" key={group.title}>
          <header><h2>{group.title}</h2><p>{group.description}</p></header>
          <div className="client-diagnosis-rows">
            {group.keys.map((key) => {
              const row = report.dimensions.find((item) => item.key === key);
              const copy = CLIENT_DIMENSIONS[key];
              if (!row || !copy) return null;
              const width = row.has_data && row.value !== null ? Math.max(2, Math.min(100, row.value * 100)) : 0;
              return <div className="client-diagnosis-row" key={row.key}>
                <div className="client-diagnosis-row-copy"><strong>{copy.label}</strong><p>{copy.description}</p></div>
                <div className="client-diagnosis-row-value">
                  <strong>{row.has_data && row.value !== null ? `${(row.value * 100).toFixed(1)}%` : "样本不足"}</strong>
                  <div className="client-diagnosis-bar"><i style={{ width: `${width}%` }}/></div>
                  <span>{row.has_data && row.value !== null ? `基于 ${row.denominator} 条样本` : "暂不判断"}</span>
                </div>
              </div>;
            })}
          </div>
        </section>)}
      </div>

      <p className="client-caliber-note">七项各自独立，不做综合评分或排名；样本不足时不强行给结论。回答类型和问题类型可以分开看。</p>
    </div>;
  }

  return (
    <div className="report-layout">
      <div className="report-filters">
        <SelectInput label={clientMode ? "回答类型" : "答案口径"} value={answerKind} onChange={(event) => setAnswerKind(event.target.value)}>
          {(clientMode ? CLIENT_ANSWER_KIND_OPTIONS : ANSWER_KIND_OPTIONS).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </SelectInput>
        <SelectInput label={clientMode ? "问题类型" : "题目分区"} value={questionType} onChange={(event) => setQuestionType(event.target.value)}>
          {(clientMode ? CLIENT_QUESTION_TYPE_OPTIONS : QUESTION_TYPE_OPTIONS).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </SelectInput>
        <div className="report-scope">
          <Badge tone={hasSamples ? "green" : "amber"}>已分析 {report.scope.valid_answers} 条回答</Badge>
          {!clientMode && <span className="report-scope-note">
            排除：失败 {excluded.failed ?? 0} · 待复核 {excluded.manual_review ?? 0} · 无回答面 {excluded.no_answer_surface ?? 0} · 未完成 {excluded.pending_or_running ?? 0}
          </span>}
        </div>
        {canExport && (
          <Button
            variant="secondary"
            icon="download"
            onClick={() => {
              const query = new URLSearchParams({ project_id: projectId });
              if (answerKind) query.set("answer_kind", answerKind);
              if (questionType) query.set("question_type", questionType);
              window.open(`/internal/workbench/diagnosis/export?${query}`, "_blank");
            }}
          >{clientMode ? "下载明细" : "导出 CSV"}</Button>
        )}
      </div>

      {!hasSamples && (
        <StatePlaceholder kind="empty" compact title="当前筛选范围内没有有效样本" description="调整回答类型或问题类型，或先完成一轮监测采集。" />
      )}

      <div className="report-summary">
        <div className="report-summary-lead">
          <span>本次报告摘要</span>
          <strong>{hasSamples ? `${readyDimensions} / 7 项可判断` : "暂无有效回答"}</strong>
          <p>{hasSamples ? `有效回答 ${report.scope.valid_answers} 条；失败、待复核与未完成样本不进入分母。` : "先补齐样本，报告不会用 0.0% 代替“无数据”。"}</p>
        </div>
        {summaryRows.map((row, index) => <div className="report-summary-item" key={row.key}>
          <span><b>0{index + 1}</b>{summaryNotes[row.key] ?? row.label}</span>
          <strong className={row.has_data ? "" : "is-empty"}>{row.has_data ? percent(row.value) : "无有效样本"}</strong>
          <p>{row.has_data ? `${row.label} · ${row.numerator} / ${row.denominator}` : `${row.label} · 当前筛选内没有可判断样本`}</p>
        </div>)}
      </div>

      <div className="report-detail-layout">
        <section className="report-dimensions">
          <header className="report-dimensions-head">
            <div><h3>七项分项</h3><p>每项独立分子 / 分母，不合成总分；没有样本的分项不参与排序。</p></div>
            <Badge tone={readyDimensions === report.dimensions.length ? "green" : "slate"}>{readyDimensions} / {report.dimensions.length} 项可判断</Badge>
          </header>
          {report.dimensions.map((row) => <div className="report-dimension-row" key={row.key}>
            <div className="report-dimension-copy">
              <div className="report-dimension-title"><h4>{row.label}</h4><Badge tone={row.has_data ? "blue" : "slate"}>{row.has_data ? `${row.numerator} / ${row.denominator}` : "无分母"}</Badge></div>
              <p className="report-dimension-def">{row.definition}</p>
              {(dimensionExtra(row) || row.basis) && <details className="report-card-basis">
                <summary>口径说明</summary>
                {dimensionExtra(row) && <p>{dimensionExtra(row)}</p>}
                {row.basis && <p>{row.basis}</p>}
              </details>}
            </div>
            <div className={`report-dimension-value${row.has_data ? "" : " is-empty"}`}>
              <strong>{row.has_data && row.value !== null ? percent(row.value) : "暂无样本"}</strong>
              <small>{row.has_data ? "按当前筛选实时计算" : "不参与判断"}</small>
            </div>
          </div>)}
        </section>

        <aside className="report-caliber-side">
          <div className="report-caliber-head"><span>怎么读这份报告</span><Badge tone="slate">口径</Badge></div>
          <ul className="report-card-notes">
            {report.caveats.map((note) => <li key={note}>{note}</li>)}
          </ul>
          <p className="report-caliber-foot">三项摘要只给方向；结论前先看每项的分子、分母和样本量，不做综合评分或排名。</p>
        </aside>
      </div>

      {clientMode
        ? <p className="client-caliber-note">以上七项各自独立，不做综合评分或排名；样本少于 10 条时只展示数字，不作为结论依据。</p>
        : null}
    </div>
  );
}
