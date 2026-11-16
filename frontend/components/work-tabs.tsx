"use client";

import type { ReactNode } from "react";

export type WorkTabItem<T extends string> = {
  id: T;
  label: string;
  count?: number;
};

export function WorkTabs<T extends string>({ items, active, onChange, ariaLabel, extra }: {
  items: WorkTabItem<T>[];
  active: T;
  onChange: (id: T) => void;
  ariaLabel: string;
  extra?: ReactNode;
}) {
  return <div className="work-tabs" role="tablist" aria-label={ariaLabel}>
    {items.map((item) => <button
      type="button"
      role="tab"
      aria-selected={active === item.id}
      key={item.id}
      className={`work-tab ${active === item.id ? "active" : ""}`}
      onClick={() => onChange(item.id)}
    >{item.label}{item.count !== undefined && <em>{item.count}</em>}</button>)}
    {extra && <div className="work-tabs-extra">{extra}</div>}
  </div>;
}
