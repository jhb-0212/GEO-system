"use client";

import { useEffect, useState } from "react";

import { Badge, Panel, SelectInput } from "../ui";
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

const QUESTION_TYPE_OPTIONS = [
  { value: "", label: "全部题目" },
  { value: "general", label: "通用题（自然发现）" },
  { value: "brand", label: "品牌题（功能验证）" },
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
}: {
  mode: "mock" | "live";
  projectId: string;
  canRead: boolean;
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

  return (
    <div className="report-layout">
      <div className="report-filters">
        <SelectInput label="答案口径" value={answerKind} onChange={(event) => setAnswerKind(event.target.value)}>
          {ANSWER_KIND_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </SelectInput>
        <SelectInput label="题目分区" value={questionType} onChange={(event) => setQuestionType(event.target.value)}>
          {QUESTION_TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </SelectInput>
        <div className="report-scope">
          <Badge tone={hasSamples ? "green" : "amber"}>有效样本 {report.scope.valid_answers}</Badge>
          <span className="report-scope-note">
            排除：失败 {excluded.failed ?? 0} · 待复核 {excluded.manual_review ?? 0} · 无回答面 {excluded.no_answer_surface ?? 0} · 未完成 {excluded.pending_or_running ?? 0}
          </span>
        </div>
      </div>

      {!hasSamples && (
        <StatePlaceholder kind="empty" compact title="当前筛选范围内没有有效样本" description="调整答案口径或题目分区，或先完成一轮监测采集。" />
      )}

      <div className="report-grid">
        {report.dimensions.map((row) => (
          <Panel className="report-card" key={row.key}>
            <div className="report-card-head">
              <span className="report-card-label">{row.label}</span>
              <Badge tone={row.has_data ? "blue" : "slate"}>{row.has_data ? `${row.numerator} / ${row.denominator}` : "无分母"}</Badge>
            </div>
            <div className="report-card-value">{percent(row.value)}</div>
            <p className="report-card-def">{row.definition}</p>
            {dimensionExtra(row) && <p className="report-card-extra">{dimensionExtra(row)}</p>}
            <p className="report-card-basis">口径：{row.basis}</p>
          </Panel>
        ))}
      </div>

      <Panel className="report-caveats" title="口径提示">
        <ul>
          {report.caveats.map((note) => <li key={note}>{note}</li>)}
        </ul>
      </Panel>
    </div>
  );
}
