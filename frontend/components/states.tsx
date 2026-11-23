"use client";

import type { ReactNode } from "react";

import { Icon, type IconName } from "./ui";

export type StateKind = "empty" | "not-collected" | "loading" | "error" | "permission";

const STATE_ICON: Record<StateKind, IconName> = {
  empty: "folder",
  "not-collected": "info",
  loading: "refresh",
  error: "info",
  permission: "lock",
};

const STATE_DEFAULT_TITLE: Record<StateKind, string> = {
  empty: "暂无数据",
  "not-collected": "尚未采集",
  loading: "正在加载",
  error: "加载失败",
  permission: "无权查看",
};

/**
 * 统一状态占位。
 *
 * 四条硬规则（对齐取舍清单 C9：不许用 0 假装有数据）：
 * 1. 没数据 → empty，说清"怎么才会有数据"；
 * 2. 有指标但还没跑采集 → not-collected，**绝不显示 0**；
 * 3. 加载中 → loading，用骨架/文案，不用裸转圈；
 * 4. 失败 → error，必须带重试动作或可复制的错误码。
 */
export function StatePlaceholder({
  kind = "empty",
  title,
  description,
  action,
  compact = false,
}: {
  kind?: StateKind;
  title?: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`g-state is-${kind}${compact ? " is-compact" : ""}`} role="status">
      <span className="g-state-badge">
        <Icon name={STATE_ICON[kind]} size={18} />
      </span>
      <p className="g-state-title">{title ?? STATE_DEFAULT_TITLE[kind]}</p>
      {description && <p className="g-state-desc">{description}</p>}
      {action && <div className="g-state-actions">{action}</div>}
      {kind === "loading" && (
        <div style={{ width: "min(320px, 80%)", display: "grid", gap: 8 }} aria-hidden="true">
          <i className="g-skeleton" />
          <i className="g-skeleton" style={{ width: "70%" }} />
        </div>
      )}
    </div>
  );
}

/** 表格内联空行：不占整块高度，用于 tbody 里没记录的情况 */
export function TableEmptyRow({ colSpan, text = "暂无数据", hint }: { colSpan: number; text?: string; hint?: string }) {
  return (
    <tr>
      <td colSpan={colSpan} style={{ padding: 0, border: 0 }}>
        <StatePlaceholder kind="empty" compact title={text} description={hint} />
      </td>
    </tr>
  );
}
