"use client";

import { useEffect, useRef, useState } from "react";
import { beijingNowParts } from "@/lib/workbench/time";
import { Icon } from "./ui";

const pad = (n: number) => String(n).padStart(2, "0");

function parseDate(value: string): { y: number; m: number; d: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? { y: Number(match[1]), m: Number(match[2]), d: Number(match[3]) } : null;
}

function parseMonth(value: string): { y: number; m: number } | null {
  const match = /^(\d{4})-(\d{2})$/.exec(value);
  return match ? { y: Number(match[1]), m: Number(match[2]) } : null;
}

/**
 * 自研日期/月份选择控件：不再依赖浏览器原生 date/month input，
 * 弹层日历由组件渲染，占位文案与显示格式在所有浏览器一致。
 * value 格式：mode="date" 为 YYYY-MM-DD，mode="month" 为 YYYY-MM。
 */
export function DateField({ id, label, mode, value, onChange }: {
  id: string;
  label: string;
  mode: "date" | "month";
  value: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  // 今天的判定锚定北京标准时间，不跟随浏览器本地时区
  const [today] = useState(beijingNowParts);
  const [view, setView] = useState(() => {
    const parsed = mode === "month" ? parseMonth(value) : parseDate(value);
    return parsed ?? { y: today.y, m: today.m };
  });

  useEffect(() => {
    if (!open) return;
    function onDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const dateValue = parseDate(value);
  const monthValue = parseMonth(value);
  const display = mode === "month"
    ? (monthValue ? `${monthValue.y}年${monthValue.m}月` : "请选择月份")
    : (dateValue ? `${dateValue.y}年${dateValue.m}月${dateValue.d}日` : "请选择日期");
  const selectedKey = value || "";

  function shift(delta: number) {
    setView((current) => {
      const next = new Date(current.y, current.m - 1 + delta, 1);
      return { y: next.getFullYear(), m: next.getMonth() + 1 };
    });
  }

  const startWeekday = (new Date(view.y, view.m - 1, 1).getDay() + 6) % 7; // 周一 = 0
  const daysInMonth = new Date(view.y, view.m, 0).getDate();
  const cells: (number | null)[] = [];
  for (let i = 0; i < startWeekday; i += 1) cells.push(null);
  for (let d = 1; d <= daysInMonth; d += 1) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  return <div className="date-field" id={id} ref={rootRef}>
    <span>{label}</span>
    <button type="button" className="date-trigger" aria-label={label} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((current) => !current)}>
      <span className={value ? "" : "is-placeholder"}>{display}</span>
      <Icon name="calendar" size={14} />
    </button>
    {open && <div className="date-pop" role="dialog" aria-label={`${label}选择`}>
      <div className="date-pop-head">
        <button type="button" className="date-pop-nav" aria-label="上一页" onClick={() => shift(mode === "month" ? -12 : -1)}>‹</button>
        <strong>{view.y}年{mode === "date" ? `${view.m}月` : ""}</strong>
        <button type="button" className="date-pop-nav" aria-label="下一页" onClick={() => shift(mode === "month" ? 12 : 1)}>›</button>
      </div>
      {mode === "date" && <>
        <div className="date-pop-week"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div>
        <div className="date-pop-grid">
          {cells.map((day, index) => day === null
            ? <span key={`empty-${index}`} />
            : (() => {
              const key = `${view.y}-${pad(view.m)}-${pad(day)}`;
              const isToday = view.y === today.y && view.m === today.m && day === today.d;
              return <button type="button" key={key} className={`date-day${isToday ? " is-today" : ""}${selectedKey === key ? " is-selected" : ""}`} onClick={() => { onChange(key); setOpen(false); }}>{day}</button>;
            })())}
        </div>
      </>}
      {mode === "month" && <div className="date-pop-months">
        {Array.from({ length: 12 }, (_, index) => index + 1).map((m) => {
          const key = `${view.y}-${pad(m)}`;
          return <button type="button" key={key} className={`date-month${selectedKey === key ? " is-selected" : ""}${today.y === view.y && today.m === m ? " is-today" : ""}`} onClick={() => { onChange(key); setOpen(false); }}>{m}月</button>;
        })}
      </div>}
    </div>}
  </div>;
}
