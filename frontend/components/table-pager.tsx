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
  // 计数文案只有一种句式（「共 N 条」），单页与多页不再各写一套：
  // 之前单页写「共 N 条」、多页写「显示 X 条 / 共 Y 条」，同一份表格换个页大小就变文案。
  // 单页时不渲染翻页控件，但保留计数：否则用户分不清是空数据还是还没加载。
  if (total <= pageSize) return <div className="table-footer"><span>共 {total} 条</span></div>;
  return <div className="table-footer">
    <span>共 {total} 条</span>
    <span className="knowledge-panel-foot">
      <Button variant="secondary" disabled={page <= 1 || loading} onClick={() => onChange(page - 1)}>上一页</Button>
      <span>{page} / {pageCount}</span>
      <Button variant="secondary" disabled={page >= pageCount || loading} onClick={() => onChange(page + 1)}>下一页</Button>
    </span>
  </div>;
}
