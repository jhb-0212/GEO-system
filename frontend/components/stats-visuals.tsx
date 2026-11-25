"use client";

export type VizTone = "blue" | "teal" | "amber" | "red" | "slate";

const TONE_COLOR: Record<VizTone, string> = {
  blue: "#176c6b",
  teal: "#2f8f88",
  amber: "#b98a3e",
  red: "#b4553f",
  slate: "#7c8b84",
};


export function vizColor(tone: VizTone): string {
  return TONE_COLOR[tone];
}

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "--" : `${(value * 100).toFixed(1)}%`;
}

export interface DonutSegment {
  label: string;
  value: number;
  tone: VizTone;
}

export function DonutChart({ segments, centerValue, centerLabel, ariaLabel }: {
  segments: DonutSegment[];
  centerValue: string | number;
  centerLabel: string;
  ariaLabel: string;
}) {
  const total = segments.reduce((sum, item) => sum + Math.max(0, item.value), 0);
  const visible = segments.filter((item) => item.value > 0);
  if (!total || !visible.length) return <div className="viz-empty">暂无数据</div>;
  const stops = visible.map((item, index) => {
    const start = (visible.slice(0, index).reduce((sum, segment) => sum + segment.value, 0) / total) * 100;
    const end = (visible.slice(0, index + 1).reduce((sum, segment) => sum + segment.value, 0) / total) * 100;
    return `${TONE_COLOR[item.tone]} ${start.toFixed(2)}% ${end.toFixed(2)}%`;
  }).join(", ");  return <div className="viz-donut-layout" role="img" aria-label={ariaLabel}>
    <div className="viz-donut-shell">
      <div className="viz-donut" style={{ background: `conic-gradient(${stops})` }}>
        <div className="viz-donut-hole"><strong>{centerValue}</strong><span>{centerLabel}</span></div>
      </div>
    </div>
    <ul className="viz-legend">
      {segments.map((item) => <li key={item.label} className={item.value ? "" : "is-zero"}>
        <i style={{ background: TONE_COLOR[item.tone] }} />
        <span>{item.label}</span>
        <strong>{item.value}</strong>
        <small>{total ? `${((item.value / total) * 100).toFixed(1)}%` : "0.0%"}</small>
      </li>)}
    </ul>
  </div>;
}

export interface RateBarItem {
  label: string;
  value: number | null;
  display?: string;
  hint?: string;
  tone: VizTone;
}

export function RateBars({ items, ariaLabel }: { items: RateBarItem[]; ariaLabel: string }) {
  return <div className="viz-rate-list" role="img" aria-label={ariaLabel}>
    {items.map((item) => {
      const width = item.value === null ? 0 : Math.min(100, Math.max(0, item.value * 100));
      return <div className="viz-rate-row" key={item.label}>
        <div className="viz-rate-head">
          <span>{item.label}</span>
          <strong style={{ color: TONE_COLOR[item.tone] }}>{item.display ?? percent(item.value)}</strong>
        </div>
        <div className="viz-rate-track">
          <i style={{ width: `${width}%`, background: TONE_COLOR[item.tone] }} />
        </div>
        {item.hint && <small>{item.hint}</small>}
      </div>;
    })}
  </div>;
}

export interface ColumnItem {
  label: string;
  value: number;
  note: string;
  tone: VizTone;
}

export function ColumnCompare({ items, ariaLabel }: { items: ColumnItem[]; ariaLabel: string }) {
  const max = Math.max(1, ...items.map((item) => item.value));
  return <div className="viz-columns" role="img" aria-label={ariaLabel}>
    {items.map((item) => <div className="viz-column" key={item.label}>
      <strong>{item.value}</strong>
      <div className="viz-column-track">
        <i style={{ height: `${Math.max(4, (item.value / max) * 100)}%`, background: TONE_COLOR[item.tone] }} />
      </div>
      <span>{item.label}</span>
      <small style={{ color: TONE_COLOR[item.tone] }}>{item.note}</small>
    </div>)}
  </div>;
}

export interface StackSegment {
  label: string;
  value: number;
  tone: VizTone;
}

export function StackedBar({ segments, ariaLabel, footnote }: { segments: StackSegment[]; ariaLabel: string; footnote?: string }) {
  const total = segments.reduce((sum, item) => sum + Math.max(0, item.value), 0);
  if (!total) return <div className="viz-empty">暂无数据</div>;
  return <div className="viz-stack-block">
    <div className="viz-stack" role="img" aria-label={ariaLabel}>
      {segments.filter((item) => item.value > 0).map((item) => <i
        key={item.label}
        style={{ width: `${(item.value / total) * 100}%`, background: TONE_COLOR[item.tone] }}
        title={`${item.label} ${item.value}`}
      />)}
    </div>
    <ul className="viz-stack-legend">
      {segments.map((item) => <li key={item.label}>
        <i style={{ background: TONE_COLOR[item.tone] }} />
        <span>{item.label}</span>
        <strong>{item.value}</strong>
        <small>{total ? `${((item.value / total) * 100).toFixed(1)}%` : "0.0%"}</small>
      </li>)}
    </ul>
    {footnote && <p className="viz-footnote">{footnote}</p>}
  </div>;
}

export interface BarItem {
  label: string;
  value: number;
  display?: string;
  hint?: string;
  tone?: VizTone;
}

export function HorizontalBars({ items, ariaLabel, maxItems = 10, emptyText = "暂无数据", scaleMax }: {
  items: BarItem[];
  ariaLabel: string;
  maxItems?: number;
  emptyText?: string;
  scaleMax?: number;
}) {
  const visible = items.slice(0, maxItems);
  if (!visible.length) return <div className="viz-empty">{emptyText}</div>;
  const max = Math.max(1e-9, scaleMax ?? Math.max(1, ...visible.map((item) => item.value)));
  return <div className="viz-hbars" role="img" aria-label={ariaLabel}>
    {visible.map((item, index) => <div className="viz-hbar" key={`${item.label}-${index}`}>
      <span className="viz-hbar-label" title={item.label}>{item.label}</span>
      <div className="viz-hbar-track">
        <i style={{ width: `${Math.max(2, (item.value / max) * 100)}%`, background: TONE_COLOR[item.tone ?? "blue"] }} />
      </div>
      <strong>{item.display ?? item.value}</strong>
      {item.hint && <small>{item.hint}</small>}
    </div>)}
  </div>;
}

export function VizEmpty({ text }: { text: string }) {
  return <div className="viz-empty">{text}</div>;
}
