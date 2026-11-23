"use client";

import type { ReactNode } from "react";

import { Icon, type IconName } from "./ui";
import { StatePlaceholder } from "./states";

type Tone = "info" | "positive" | "warning" | "danger" | "neutral";

/* ------------------------------------------------------------------ */
/* KPI 卡                                                             */
/* ------------------------------------------------------------------ */

export function StatTile({
  label,
  value,
  unit,
  icon,
  tone = "info",
  delta,
  deltaSuffix = "",
  lowerIsBetter = false,
  hint,
  missingText = "尚未采集",
}: {
  label: string;
  /** null = 指标还没采集。按取舍清单 C9，此时不许显示 0 */
  value: string | number | null;
  unit?: string;
  icon?: IconName;
  tone?: Tone;
  /** 环比/同比差值；null 或 undefined 则不显示 */
  delta?: number | null;
  deltaSuffix?: string;
  /** 下降是好事时置 true（如负面提及数、错误数） */
  lowerIsBetter?: boolean;
  hint?: ReactNode;
  missingText?: string;
}) {
  const missing = value === null || value === undefined || value === "";
  const deltaFlat = typeof delta === "number" && delta === 0;
  const deltaGood = typeof delta === "number" && delta !== 0 ? (lowerIsBetter ? delta < 0 : delta > 0) : false;
  const deltaClass = deltaFlat ? "is-flat" : deltaGood ? "is-up" : "is-down";
  const arrow = deltaFlat ? "→" : typeof delta === "number" && delta > 0 ? "↑" : "↓";

  return (
    <div className="g-tile">
      <div className="g-tile-head">
        <span className="g-tile-label">{label}</span>
        {icon && (
          <span className={`g-tile-icon is-${tone}`}>
            <Icon name={icon} size={15} />
          </span>
        )}
      </div>
      <div className="g-tile-value-row">
        {missing ? (
          <span className="g-tile-value is-missing">{missingText}</span>
        ) : (
          <>
            <span className="g-tile-value">{value}</span>
            {unit && <span className="g-tile-unit">{unit}</span>}
          </>
        )}
      </div>
      <div className="g-tile-foot">
        {typeof delta === "number" && (
          <span className={`g-tile-delta ${deltaClass}`}>
            {arrow} {Math.abs(delta)}
            {deltaSuffix}
          </span>
        )}
        {hint && <span className="g-tile-hint" title={typeof hint === "string" ? hint : undefined}>{hint}</span>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 趋势                                                               */
/* ------------------------------------------------------------------ */

export interface TrendPoint {
  label: string;
  /** null = 该期未采集，线在此断开，不插值、不当 0 */
  value: number | null;
}

export function TrendArea({
  points,
  label,
  ariaLabel,
  height = 96,
  unit = "",
  format,
}: {
  points: TrendPoint[];
  label?: string;
  ariaLabel: string;
  height?: number;
  unit?: string;
  format?: (value: number) => string;
}) {
  const known = points.map((p) => p.value).filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (!known.length) {
    return (
      <StatePlaceholder
        kind="not-collected"
        compact
        title="趋势尚未采集"
        description="补齐至少一期数据后才会画线，不用 0 占位。"
      />
    );
  }

  const max = Math.max(...known, 1);
  const min = Math.min(...known, 0);
  const span = max - min || 1;
  const xOf = (index: number) => (points.length === 1 ? 50 : (index / (points.length - 1)) * 100);
  const yOf = (value: number) => 92 - ((value - min) / span) * 84;

  // 按连续段切分，null 处断开：不同段各自起一条 path，避免把缺失期连成直线
  const segments: { x: number; y: number }[][] = [];
  let current: { x: number; y: number }[] = [];
  points.forEach((point, index) => {
    if (typeof point.value === "number" && Number.isFinite(point.value)) {
      current.push({ x: xOf(index), y: yOf(point.value) });
    } else if (current.length) {
      segments.push(current);
      current = [];
    }
  });
  if (current.length) segments.push(current);

  const linePath = (segment: { x: number; y: number }[]) =>
    segment.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
  const areaPath = (segment: { x: number; y: number }[]) =>
    `${linePath(segment)} L${segment[segment.length - 1].x.toFixed(2)},100 L${segment[0].x.toFixed(2)},100 Z`;

  const latest = [...points].reverse().find((point) => typeof point.value === "number");
  const latestText = latest && typeof latest.value === "number" ? (format ? format(latest.value) : latest.value) : null;

  const ticks = points.length <= 2 ? points : [points[0], points[Math.floor((points.length - 1) / 2)], points[points.length - 1]];

  return (
    <div className="g-trend">
      {(label || latestText !== null) && (
        <div className="g-trend-head">
          {label && <span className="g-trend-label">{label}</span>}
          {latestText !== null && (
            <span className="g-trend-latest">
              {latestText}
              {unit && <span className="g-tile-unit">{unit}</span>}
            </span>
          )}
        </div>
      )}
      <div className="g-trend-plot" style={{ height }} role="img" aria-label={ariaLabel}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none">
          {[25, 50, 75].map((y) => (
            <line key={y} className="g-trend-grid" x1="0" y1={y} x2="100" y2={y} />
          ))}
          {segments.map((segment, index) => (
            <path key={`area-${index}`} className="g-trend-area" d={areaPath(segment)} />
          ))}
          {segments.map((segment, index) => (
            <path key={`line-${index}`} className="g-trend-line" d={linePath(segment)} />
          ))}
        </svg>
      </div>
      <div className="g-trend-axis" aria-hidden="true">
        {ticks.map((point, index) => (
          <span key={`${point.label}-${index}`}>{point.label}</span>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 分项仪表（单项达成率，不做综合分——见取舍清单 C3）                    */
/* ------------------------------------------------------------------ */

export function GaugeArc({
  value,
  label,
  caption,
  tone = "info",
  ariaLabel,
}: {
  /** 0–1，null 表示未采集 */
  value: number | null;
  label: string;
  caption?: string;
  tone?: Tone;
  ariaLabel?: string;
}) {
  if (value === null || !Number.isFinite(value)) {
    return (
      <div className="g-gauge">
        <StatePlaceholder kind="not-collected" compact title="未采集" description="该项未跑采集，不显示 0 分。" />
        <span className="g-gauge-label">{label}</span>
      </div>
    );
  }
  const clamped = Math.min(1, Math.max(0, value));
  const arc = 145; // 半径 46 的半圆弧长 ≈ 144.5
  return (
    <div className="g-gauge">
      <svg viewBox="0 0 120 74" role="img" aria-label={ariaLabel ?? `${label} ${(clamped * 100).toFixed(1)}%`}>
        <path className="g-gauge-track" d="M14,62 A46,46 0 0 1 106,62" />
        <path
          className={`g-gauge-fill is-${tone}`}
          d="M14,62 A46,46 0 0 1 106,62"
          strokeDasharray={arc}
          strokeDashoffset={arc * (1 - clamped)}
        />
      </svg>
      <span className="g-gauge-value">{(clamped * 100).toFixed(clamped === 1 ? 0 : 1)}%</span>
      <span className="g-gauge-label">{label}</span>
      {caption && <span className="g-gauge-caption">{caption}</span>}
    </div>
  );
}
