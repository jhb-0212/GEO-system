"use client";

import { Icon } from "../ui";
import { formatIsoDate, formatPersonName } from "@/lib/workbench/format";
import type { ContentVersionRecord, ReviewItem, Tone, WorkbenchSnapshot } from "@/lib/workbench/types";

/** 演示模式的内容审核数据：把审核项适配成与真实接口一致的版本记录，复用同一个面板。 */
export function toDemoVersion(item: ReviewItem): ContentVersionRecord {
  return {
    version_id: item.id,
    item_id: item.id,
    title: item.title,
    version_no: 1,
    status: item.status === "已通过" ? "approved" : item.status === "已驳回" ? "rejected" : "pending_review",
    kind: item.type,
    channel_id: null,
    author_name: item.author,
    submitted_at: item.submittedAt,
  };
}

/** 账号显示只保留业务名称，隐藏 seed、API 适配器等实现备注。 */
export function displayUserName(name?: string) {
  return formatPersonName(name) || "当前账号";
}

export function statusTone(status: string): Tone {
  if (["运行中", "已完成", "已通过", "已转化"].includes(status)) return "green";
  if (["进行中", "跟进中"].includes(status)) return "blue";
  if (["需复核", "待审核", "待跟进", "筹备中", "待核实"].includes(status)) return "amber";
  if (["已驳回", "失败", "已流失"].includes(status)) return "red";
  return "slate";
}

export function projectName(snapshot: WorkbenchSnapshot, id: string) {
  return snapshot.projects.find((project) => project.id === id)?.name ?? "未知项目";
}

/**
 * 引擎占比圆环按真实 share 分段。
 * 之前圆环是写死的 CSS 渐变，图例百分比变了圆环纹丝不动，属于「图和数据对不上」。
 * share 合计不一定等于 100（后端按任务数算占比后取整），这里按合计归一化。
 */
export function engineGradient(engines: WorkbenchSnapshot["engines"]): string | undefined {
  const total = engines.reduce((sum, engine) => sum + Math.max(0, engine.share), 0);
  if (!total) return undefined;
  let cursor = 0;
  const stops = engines.map((engine) => {
    const start = cursor;
    cursor += (Math.max(0, engine.share) / total) * 100;
    return `${engine.color} ${start.toFixed(2)}% ${cursor.toFixed(2)}%`;
  });
  return `conic-gradient(${stops.join(", ")})`;
}

export function TrendChart({ values, dates, days }: { values: (number | null)[]; dates: string[]; days: number }) {
  if (!values.some((value) => value !== null)) return <div className="chart-empty">暂无有效样本</div>;
  const peak = Math.max(...values.filter((value): value is number => value !== null), 0);
  const yMax = Math.max(10, Math.ceil(peak / 10) * 10);
  const yLabels = [yMax, yMax * 0.75, yMax * 0.5, yMax * 0.25, 0].map((value) => `${Number(value.toFixed(1))}%`);
  const segments: { x: number; y: number }[][] = [];
  let active: { x: number; y: number }[] = [];
  values.forEach((value, index) => {
    if (value === null) { if (active.length) segments.push(active); active = []; return; }
    active.push({ x: 28 + index * (517 / Math.max(1, values.length - 1)), y: 160 - (value / yMax) * 128 });
  });
  if (active.length) segments.push(active);
  const visiblePoints = values.filter((value) => value !== null).length;
  const dots = segments.flatMap((segment) => segment.length === 1 || visiblePoints <= 3 ? segment : []);
  const start = dates[0] ? formatIsoDate(dates[0]) : `${days} 天前`;
  const middle = dates[Math.floor((dates.length - 1) / 2)] ? formatIsoDate(dates[Math.floor((dates.length - 1) / 2)]) : `${Math.round(days / 2)} 天前`;
  const end = dates[dates.length - 1] ? formatIsoDate(dates[dates.length - 1]) : "今天";
  const middleIndex = Math.floor((values.length - 1) / 2);
  const tickItems = dates.length && dates.length <= 7
    ? dates.map((date, index) => ({ label: formatIsoDate(date), index }))
    : dates.length
      ? [
          { label: formatIsoDate(dates[0]), index: 0 },
          { label: formatIsoDate(dates[Math.min(dates.length - 1, middleIndex)]), index: middleIndex },
          { label: formatIsoDate(dates[dates.length - 1]), index: Math.max(0, values.length - 1) },
        ]
      : [{ label: start, index: 0 }, { label: middle, index: middleIndex }, { label: end, index: Math.max(0, values.length - 1) }];
  const staggered = false;
  const dense = tickItems.length > 7;
  return <div className={`trend-chart${staggered ? " trend-chart-staggered" : ""}`}><div className="chart-y">{yLabels.map((label) => <span key={label}>{label}</span>)}</div><svg viewBox="0 0 585 180" role="img" aria-label={`近 ${days} 天品牌提及率变化`}><path d="M28 32H558M28 64H558M28 96H558M28 128H558M28 160H558" stroke="#e9edf3" strokeDasharray="4 5"/>{segments.map((points, index) => points.length > 1 ? <polyline key={index} points={points.map((point) => `${point.x},${point.y}`).join(" ")} fill="none" stroke="#3e70ef" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/> : null)}{dots.map((point, index) => <circle key={`dot-${index}`} cx={point.x} cy={point.y} r={4.5} fill="#3e70ef" stroke="#fff" strokeWidth={2}/>)}</svg><div className={`chart-x${dense ? " chart-x-dense" : ""}${staggered ? " chart-x-staggered" : ""}`}>{tickItems.map((item, index) => <span key={`${item.label}-${index}`} style={{ left: `${((28 + item.index * (517 / Math.max(1, values.length - 1))) / 585) * 100}%`, top: staggered && index % 2 === 1 ? "14px" : undefined }}>{item.label}</span>)}</div></div>;
}

export function EmptyTable({ message }: { message: string }) {
  return <div className="empty-table"><span className="empty-icon"><Icon name="folder" size={24} /></span><strong>暂无数据</strong><p>{message}</p></div>;
}
