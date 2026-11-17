"use client";

import { Button } from "./ui";

/**
 * 表格分页页脚：页大小由调用方传入，避免在每个面板里写死 20 / 100。
 * 只有一页且已加载完时不渲染，保持页面干净。
 */
export function TablePager({ page, total, pageSize, loading, onChange }: {
  page: number;
  total: number;
  pageSize: number;
  loading?: boolean;
  onChange: (page: number) => void;
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const shown = Math.max(0, Math.min(pageSize, total - (page - 1) * pageSize));
  if (total <= pageSize) return null;
  return <div className="table-footer">
    <span>显示 {shown} 条 / 共 {total} 条</span>
    <span className="knowledge-panel-foot">
      <Button variant="secondary" disabled={page <= 1 || loading} onClick={() => onChange(page - 1)}>上一页</Button>
      <span>{page} / {pageCount}</span>
      <Button variant="secondary" disabled={page >= pageCount || loading} onClick={() => onChange(page + 1)}>下一页</Button>
    </span>
  </div>;
}
