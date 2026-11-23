"use client";

import { Children, Fragment, cloneElement, isValidElement, useEffect, useId, useSyncExternalStore } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactElement, ReactNode, SelectHTMLAttributes } from "react";
import type { Tone } from "@/lib/workbench/types";

export type IconName = "grid" | "layers" | "pulse" | "check" | "users" | "history" | "blocks" | "search" | "bell" | "chevronDown" | "chevronRight" | "arrowRight" | "arrowUp" | "plus" | "download" | "filter" | "more" | "calendar" | "clock" | "external" | "close" | "info" | "user" | "lock" | "logout" | "menu" | "folder" | "spark" | "upload" | "eye" | "refresh" | "printer";

export function Icon({ name, size = 20, className = "" }: { name: IconName; size?: number; className?: string }) {
  const paths: Record<IconName, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
    layers: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 4v5"/></>,
    pulse: <><path d="M3 12h4l3-7 4 14 3-7h4"/></>,
    check: <><path d="m5 12 4 4L19 6"/></>,
    users: <><circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M17 5a3 3 0 0 1 0 6M21 20v-2a6 6 0 0 0-4-5.66"/></>,
    history: <><path d="M3 12a9 9 0 1 0 2.5-6.2M3 4v4h4M12 7v5l3 2"/></>,
    blocks: <><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></>,
    chevronDown: <><path d="m6 9 6 6 6-6"/></>,
    chevronRight: <><path d="m9 6 6 6-6 6"/></>,
    arrowRight: <><path d="M4 12h16m-6-6 6 6-6 6"/></>,
    arrowUp: <><path d="M12 20V4m-6 6 6-6 6 6"/></>,
    plus: <><path d="M12 4v16M4 12h16"/></>,
    download: <><path d="M12 3v12m-4-4 4 4 4-4M4 17v3h16v-3"/></>,
    filter: <><path d="M4 6h16M7 12h10m-7 6h4"/></>,
    more: <><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    external: <><path d="M13 4h7v7m0-7-9 9"/><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"/></>,
    close: <><path d="M5 5 19 19M19 5 5 19"/></>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
    lock: <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>,
    logout: <><path d="M9 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4M15 8l4 4-4 4m4-4H9"/></>,
    menu: <><path d="M4 7h16M4 12h16M4 17h16"/></>,
    folder: <><path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></>,
    spark: <><path d="m12 3 1.8 6.2L20 11l-6.2 1.8L12 19l-1.8-6.2L4 11l6.2-1.8L12 3ZM19 18l.5 1.5L21 20l-1.5.5L19 22l-.5-1.5L17 20l1.5-.5L19 18Z"/></>,
    upload: <><path d="M12 16V4m-4 4 4-4 4 4M4 17v3h16v-3"/></>,
    eye: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></>,
    refresh: <><path d="M20 7V3l-3 3a8 8 0 1 0 3 7M20 3h-5"/></>,
    printer: <><path d="M7 8V4h10v4M6 8h12a3 3 0 0 1 3 3v6h-4M7 17H3v-6a3 3 0 0 1 3-3"/><rect x="7" y="14" width="10" height="6" rx="1"/></>,
  };
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function Button({ children, variant = "primary", icon, className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "quiet" | "danger"; icon?: IconName }) {
  return <button className={`btn btn-${variant} ${className}`} {...props}>{icon && <Icon name={icon} size={17} />}{children}</button>;
}

export function Badge({ children, tone = "slate", dot = false }: { children: ReactNode; tone?: Tone; dot?: boolean }) {
  return <span className={`badge badge-${tone}`}>{dot && <i className="badge-dot" />}{children}</span>;
}

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement(node)) return textOf((node.props as { children?: ReactNode }).children);
  return "";
}

/** 只取标题块里的 h3 文本做存储 key：不把下拉菜单、角标里的数字混进去，状态才稳定。 */
function headingText(node: ReactNode): string {
  let found = "";
  const visit = (current: ReactNode) => {
    if (found || current === null || current === undefined) return;
    if (Array.isArray(current)) {
      current.forEach(visit);
      return;
    }
    if (isValidElement(current)) {
      if (current.type === "h3") {
        found = textOf((current.props as { children?: ReactNode }).children);
        return;
      }
      visit((current.props as { children?: ReactNode }).children);
    }
  };
  visit(node);
  return found.replace(/\s+/g, "");
}

// 折叠状态存在 localStorage；用 useSyncExternalStore 读，避免"effect 里 setState"
// 造成的首帧错位与规则告警。服务端渲染拿 null（走默认值），水合后自动切到真实状态。
const collapseListeners = new Set<() => void>();

function subscribeCollapse(callback: () => void) {
  collapseListeners.add(callback);
  return () => {
    collapseListeners.delete(callback);
  };
}

function readCollapsed(key: string): boolean | null {
  try {
    const value = window.localStorage.getItem(key);
    return value === "1" ? true : value === "0" ? false : null;
  } catch {
    return null;
  }
}

/**
 * 面板容器。带 `panel-heading` 的面板自动获得「收起 / 展开」按钮：
 * 折叠只把 `panel` 除标题以外的直接子元素改成 `display:none`，DOM 结构不变
 * （`.list-panel > .table-scroll` 这类直接子选择器照常生效），也不卸载内容，
 * 所以未保存的表单草稿、分页、滚动位置都不会丢。状态按面板标题记在 localStorage。
 */
export function Panel({
  children,
  className = "",
  collapsible = true,
  defaultCollapsed = false,
  title,
}: {
  children: ReactNode;
  className?: string;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  title?: string;
}) {
  const items = Children.toArray(children);
  const heading = items.find(
    (child): child is ReactElement<{ children?: ReactNode; className?: string }> =>
      isValidElement(child) &&
      typeof (child.props as { className?: string }).className === "string" &&
      ((child.props as { className?: string }).className as string).split(" ").includes("panel-heading"),
  );
  const key = `geo-panel:${title ?? className}:${headingText(heading?.props.children).slice(0, 28)}`;
  const stored = useSyncExternalStore(
    subscribeCollapse,
    () => (collapsible && heading ? readCollapsed(key) : null),
    () => null,
  );
  const collapsed = stored ?? defaultCollapsed;

  if (!heading) return <section className={`panel ${className}`.trim()}>{children}</section>;

  const toggle = () => {
    const next = !collapsed;
    try {
      window.localStorage.setItem(key, next ? "1" : "0");
    } catch {
      /* 存不下就只在本次会话生效 */
    }
    collapseListeners.forEach((listener) => listener());
  };

  const headingNode = collapsible ? (
    cloneElement(
      heading,
      { className: `${heading.props.className ?? ""} panel-heading-with-toggle`.trim() },
      <>
        {heading.props.children}
        <button
          type="button"
          className="panel-toggle"
          aria-expanded={!collapsed}
          aria-label={collapsed ? "展开模块" : "收起模块"}
          title={collapsed ? "展开" : "收起"}
          onClick={toggle}
        >
          <Icon name={collapsed ? "chevronRight" : "chevronDown"} size={16} />
        </button>
      </>,
    )
  ) : (
    heading
  );

  const classes = ["panel", className, collapsible ? "panel-collapsible" : "", collapsed ? "panel-is-collapsed" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <section className={classes}>
      {items.map((child, index) => (
        <Fragment key={index}>{child === heading ? headingNode : child}</Fragment>
      ))}
    </section>
  );
}

/** 统一的居中详情弹窗：遮罩点击、Esc 或右上角关闭；正文过高时只在弹窗内部滚动。 */
export function DetailModal({
  eyebrow,
  title,
  subtitle,
  onClose,
  children,
  wide = true,
}: {
  eyebrow: string;
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const titleId = useId();
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className={`modal detail-modal${wide ? " detail-modal-wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <div className="modal-header"><div><p className="eyebrow">{eyebrow}</p><h2 id={titleId}>{title}</h2>{subtitle && <p className="modal-description">{subtitle}</p>}</div><button type="button" className="icon-button" aria-label="关闭" onClick={onClose}><Icon name="close" size={19}/></button></div>
      <div className="knowledge-editor-panel detail-modal-body">{children}</div>
    </div>
  </div>;
}

/**
 * 条目级折叠容器：标题行（可点切换）+ 操作区（点击不触发切换）+ 可收起的内容区。
 * 折叠状态按 storageKey 记在 localStorage，与 Panel 共用同一套订阅机制，
 * 展开/收起不会卸载内容，表单草稿与滚动位置不丢失。
 */
export function CollapsibleItem({ title, actions, children, storageKey, defaultCollapsed = false, className = "" }: {
  title: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  storageKey: string;
  defaultCollapsed?: boolean;
  className?: string;
}) {
  const stored = useSyncExternalStore(
    subscribeCollapse,
    () => readCollapsed(`geo-item:${storageKey}`),
    () => null,
  );
  const collapsed = stored ?? defaultCollapsed;

  const toggle = () => {
    const next = !collapsed;
    try {
      window.localStorage.setItem(`geo-item:${storageKey}`, next ? "1" : "0");
    } catch {
      /* 存不下就只在本次会话生效 */
    }
    collapseListeners.forEach((listener) => listener());
  };

  return (
    <div className={`collapsible-item ${collapsed ? "is-collapsed" : ""} ${className}`.trim()}>
      <div className="collapsible-item-header">
        <button
          type="button"
          className="collapsible-item-toggle"
          aria-expanded={!collapsed}
          aria-label={collapsed ? "展开条目" : "收起条目"}
          title={collapsed ? "展开" : "收起"}
          onClick={toggle}
        >
          <Icon name={collapsed ? "chevronRight" : "chevronDown"} size={15} />
        </button>
        <button type="button" className="collapsible-item-title" aria-expanded={!collapsed} onClick={toggle}>{title}</button>
        {actions && <div className="collapsible-item-actions" onClick={(event) => event.stopPropagation()}>{actions}</div>}
      </div>
      {!collapsed && <div className="collapsible-item-content">{children}</div>}
    </div>
  );
}

export function TextInput({ label, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return <label className="field"><span className="field-label">{label}</span><input className="text-input" {...props} /></label>;
}

export function SelectInput({ label, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label: string; children: ReactNode }) {
  return <label className="field"><span className="field-label">{label}</span><select className="text-input" {...props}>{children}</select></label>;
}
