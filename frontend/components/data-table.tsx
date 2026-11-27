"use client";

import type { ReactNode } from "react";

export type DataColumn<T> = {
  key: string;
  label: ReactNode;
  /** 列宽，百分比或固定值；不填则均分剩余宽度 */
  width?: string;
  className?: string;
  /** 单元格是否可省略（默认 true，标题类列可关掉换成单行省略样式） */
  render: (row: T) => ReactNode;
};

/** 序号列固定占 5%，其余列按传入百分比等比缩放到 95%，避免总宽溢出把最后一列压没。 */
function colWidth(width?: string): string | undefined {
  if (!width) return undefined;
  const percent = width.match(/^(\d+(?:\.\d+)?)%$/);
  if (percent) return `${(Number(percent[1]) * 0.94).toFixed(2)}%`;
  return width;
}

/**
 * 工作台统一清单表格：序号、标题、属性列、状态、时间，一行一条。
 * 样式与分页见 workbench.css 的 .data-table / .data-pager。
 */
export function DataTable<T>({ columns, rows, rowKey, startIndex = 0, onRow, empty, className = "", selectedKey, rowClassName }: {
  columns: Array<DataColumn<T>>;
  rows: T[];
  rowKey: (row: T) => string;
  startIndex?: number;
  onRow?: (row: T) => void;
  empty?: ReactNode;
  className?: string;
  selectedKey?: string | null;
  rowClassName?: (row: T) => string;
}) {
  return <div className="table-scroll data-table-scroll">
    <table className={`data-table ${className}`.trim()}>
      <colgroup><col style={{ width: "52px" }}/>{columns.map((column) => <col key={column.key} style={column.width ? { width: colWidth(column.width) } : undefined}/>)}</colgroup>
      <thead><tr><th className="col-no">序号</th>{columns.map((column) => <th key={column.key} className={column.className}>{column.label}</th>)}</tr></thead>
      <tbody>{rows.map((row, index) => {
        const key = rowKey(row);
        return <tr key={key} className={`${selectedKey === key ? "is-selected " : ""}${rowClassName ? rowClassName(row) : ""}`.trim()} onClick={onRow ? () => onRow(row) : undefined}>
          <td className="col-no">{String(startIndex + index + 1).padStart(2, "0")}</td>
          {columns.map((column) => <td key={column.key} className={column.className}>{column.render(row)}</td>)}
        </tr>;
      })}</tbody>
    </table>
    {!rows.length && empty}
  </div>;
}
