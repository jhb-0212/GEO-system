"use client";

import { useState } from "react";

const PAGE_SIZE_OPTIONS = [20, 50, 100];

/** 页码窗口：页数多时保留首尾，中间用省略号收口，避免页码条被几十个按钮撑开。 */
function pageItems(page: number, pageCount: number): Array<number | "gap"> {
  if (pageCount <= 7) return Array.from({ length: pageCount }, (_, index) => index + 1);
  const items: Array<number | "gap"> = [1];
  const start = Math.max(2, Math.min(page - 1, pageCount - 4));
  const end = Math.min(pageCount - 1, Math.max(page + 1, 5));
  if (start > 2) items.push("gap");
  for (let value = start; value <= end; value += 1) items.push(value);
  if (end < pageCount - 1) items.push("gap");
  items.push(pageCount);
  return items;
}

/**
 * 列表页脚：共 N 条 · 每页条数 · 页码 · 前往第 N 页。
 * 总数和翻页控件放在同一行，一眼能确认"看到的是第几条到第几条"。
 */
export function DataPager({ page, total, pageSize, loading, onPage, onPageSize }: {
  page: number; total: number; pageSize: number; loading?: boolean;
  onPage: (page: number) => void;
  onPageSize?: (pageSize: number) => void;
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  // 「前往」输入框只在用户改过之后用草稿值，翻页后自动回到当前页码，不用 effect 回写。
  const [draft, setDraft] = useState<string | null>(null);
  const jump = draft ?? String(page);
  if (total === 0) return null;

  function commitJump() {
    const target = Number(jump);
    setDraft(null);
    if (!Number.isFinite(target) || target < 1) return;
    const next = Math.min(pageCount, Math.floor(target));
    if (next !== page) onPage(next);
  }

  return <div className="data-pager">
    <span className="data-pager-total">共 {total} 条</span>
    {onPageSize && <label className="data-pager-size">每页
      <select value={pageSize} disabled={loading} onChange={(event) => onPageSize(Number(event.target.value))}>
        {PAGE_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size} 条</option>)}
      </select>
    </label>}
    <span className="data-pager-pages">
      <button type="button" className="data-page-btn" aria-label="上一页" disabled={page <= 1 || loading} onClick={() => onPage(page - 1)}>‹</button>
      {pageItems(page, pageCount).map((item, index) => item === "gap"
        ? <span className="data-page-gap" key={`gap-${index}`}>…</span>
        : <button type="button" key={item} className={`data-page-btn${item === page ? " is-active" : ""}`} disabled={loading} aria-current={item === page ? "page" : undefined} onClick={() => onPage(item)}>{item}</button>)}
      <button type="button" className="data-page-btn" aria-label="下一页" disabled={page >= pageCount || loading} onClick={() => onPage(page + 1)}>›</button>
    </span>
    <label className="data-pager-jump">前往
      <input type="text" inputMode="numeric" value={jump} disabled={loading} onChange={(event) => setDraft(event.target.value.replace(/[^\d]/g, ""))} onKeyDown={(event) => { if (event.key === "Enter") commitJump(); }} onBlur={commitJump}/>
      页
    </label>
  </div>;
}
