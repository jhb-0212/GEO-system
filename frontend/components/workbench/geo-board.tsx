"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Icon } from "../ui";
import type { IconName } from "../ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { GeoBoard, GeoBoardKpi, GeoBoardLeadEvent, GeoBoardReportKind, GeoBoardReportRow } from "@/lib/workbench/types";

const DAY_OPTIONS = [7, 30, 90] as const;
const PAGE_SIZE = 10;
/** 报表类型：前两档按样本答案口径分，后两档分别看问题意图与品牌命中。 */
const REPORT_KINDS: { id: GeoBoardReportKind; label: string; icon: IconName }[] = [
  { id: "all", label: "全部报表", icon: "layers" },
  { id: "search", label: "搜索报表", icon: "search" },
  { id: "qa", label: "问答报表", icon: "blocks" },
  { id: "intent", label: "意图报表", icon: "spark" },
  { id: "brand", label: "品牌报表", icon: "check" },
];

function formatNumber(value: number): string {
  return value.toLocaleString("zh-CN");
}

function formatTime(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function shortDate(value: string): string {
  return value.slice(5).replace("-", "/");
}

/** 迷你柱：纯 SVG，不引图表库；柱数等于窗口天数，越靠右越近。 */
function Spark({ values, demo }: { values: number[]; demo: boolean }) {
  const peak = Math.max(1, ...values);
  const gap = 0.6;
  return <svg className={`geo-spark ${demo ? "is-demo" : ""}`} viewBox={`0 0 ${values.length * 3} 24`} preserveAspectRatio="none" role="img" aria-label="近窗口每日新增柱状">
    {values.map((value, index) => {
      const height = value === 0 ? 1.6 : Math.max(2, (value / peak) * 22);
      return <rect key={index} x={index * 3} y={24 - height} width={3 - gap} height={height} rx={0.5} opacity={value === 0 ? 0.45 : 1}/>;
    })}
  </svg>;
}

/** 累计收录折线：只画窗口内累计，末端标最后一个值；不画网格以外的装饰。 */
function CumulativeLine({ items }: { items: { date: string; value: number }[] }) {
  if (!items.length) return <p className="geo-empty">窗口内暂无收录记录。</p>;
  const width = 320;
  const height = 96;
  const peak = Math.max(1, ...items.map((item) => item.value));
  const stepX = items.length > 1 ? width / (items.length - 1) : width;
  const points = items.map((item, index) => {
    const x = index * stepX;
    const y = height - (item.value / peak) * (height - 10);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  const last = items[items.length - 1];
  const lastY = height - (last.value / peak) * (height - 10);
  return <div className="geo-line-wrap">
    <svg className="geo-line" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="累计收录量折线">
      <defs>
        <linearGradient id="geo-line-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"/>
          <stop offset="100%"/>
        </linearGradient>
      </defs>
      <polygon points={`0,${height} ${points.join(" ")} ${width},${height}`} fill="url(#geo-line-fill)"/>
      <polyline points={points.join(" ")}/>
      <circle cx={width} cy={lastY} r="3.2"/>
    </svg>
    <div className="geo-line-axis"><span>{shortDate(items[0].date)}</span><span>{shortDate(last.date)}</span></div>
    <p className="geo-line-last">窗口累计 <strong>{formatNumber(last.value)}</strong> 条</p>
  </div>;
}

function KpiCard({ kpi }: { kpi: GeoBoardKpi }) {
  return <article className={`geo-kpi ${kpi.source === "demo" ? "is-demo" : ""}`}>
    <div className="geo-kpi-head">
      <span>{kpi.label}</span>
      {kpi.source === "demo" && <em title={kpi.note}>演示</em>}
    </div>
    <div className="geo-kpi-value">{formatNumber(kpi.value)}<small>{kpi.unit}</small></div>
    <div className="geo-kpi-delta">近 {kpi.window_days} 天 <strong>+{formatNumber(kpi.window_value)}</strong></div>
    <Spark values={kpi.spark} demo={kpi.source === "demo"}/>
  </article>;
}

/** 平台柱状：一平台一色，纵轴按量级取整刻度，柱顶标条数；不引图表库。 */
const ENGINE_COLORS = ["#7c4dd8", "#f4692b", "#4f7cf5", "#10c9c0", "#b18ef0", "#f6b21b", "#8a2be2", "#ff7a45", "#3b82f6", "#22c7c0", "#9b6bd8", "#ffc04d", "#c3d0e8"];

function niceStep(max: number): number {
  const raw = Math.max(1, max / 4);
  const steps = [1, 2, 5, 10, 20, 25, 30, 50, 100, 200, 500, 1000];
  return steps.find((step) => step >= raw) ?? Math.ceil(raw);
}

function EngineChart({ items, total }: { items: GeoBoard["engine_share"]["items"]; total: number }) {
  const peak = Math.max(1, ...items.map((item) => item.value));
  const step = niceStep(peak);
  const ceiling = Math.max(step, (Math.floor(peak / step) + 1) * step);
  const ticks: number[] = [];
  for (let value = 0; value <= ceiling; value += step) ticks.push(value);
  return <div className="geo-engchart">
    <div className="geo-engchart-axis" aria-hidden="true">
      {ticks.map((value) => <span key={value} style={{ bottom: `${(value / ceiling) * 100}%` }}>{formatNumber(value)}</span>)}
    </div>
    <div className="geo-engchart-plot">
      {ticks.map((value) => <i key={value} style={{ bottom: `${(value / ceiling) * 100}%` }}/>)}
      <div className="geo-engchart-bars">
        {items.map((item, index) => {
          const height = Math.max(2, (item.value / ceiling) * 100);
          return <div
            className="geo-engchart-col"
            key={item.engine_id}
            title={`${item.engine_name} · ${formatNumber(item.value)} 条${item.share === null ? "" : ` · 占 ${(item.share * 100).toFixed(0)}%`}`}
          >
            <div className="geo-engchart-track">
              <em style={{ height: `${height}%`, background: ENGINE_COLORS[index % ENGINE_COLORS.length] }}/>
              <b style={{ bottom: `calc(${height}% + 4px)` }}>{formatNumber(item.value)}</b>
            </div>
            <span className="geo-engchart-name">{item.engine_name}</span>
          </div>;
        })}
      </div>
    </div>
    <p className="geo-engchart-foot">近窗口有效样本 {formatNumber(total)} 条 · 柱高为问题条数，横轴按平台；同一条问题只落一个平台。</p>
  </div>;
}

function ReportTable({ rows, start }: { rows: GeoBoardReportRow[]; start: number }) {
  if (!rows.length) return <p className="geo-empty">该引擎在窗口内没有引用证据；换一个平台或放宽窗口再试。</p>;
  return <div className="geo-table-scroll"><table className="geo-table geo-report-table">
    <thead><tr><th className="geo-col-index">#</th><th>训练词</th><th>最新搜索词场景</th><th>发布平台</th><th className="geo-col-action">操作</th></tr></thead>
    <tbody>{rows.map((row, index) => <tr key={row.citation_id}>
      <td className="geo-col-index">{start + index}</td>
      <td className="geo-cell-strong">{row.training_word || "—"}</td>
      <td className="geo-cell-wrap">{row.answer_entity}{row.reviewed && <span className="geo-badge">已复核</span>}</td>
      <td>{row.platform}</td>
      <td className="geo-col-action">
        <a href={row.voucher_url} target="_blank" rel="noreferrer">查看凭证</a>
        {row.official_url && <a href={row.official_url} target="_blank" rel="noreferrer">官方链接</a>}
      </td>
    </tr>)}</tbody>
  </table></div>;
}

function LeadRows({ rows, start }: { rows: GeoBoardLeadEvent[]; start: number }) {
  if (!rows.length) return <p className="geo-empty">还没有线索事件；访问埋点或表单接入后这里会出现记录。</p>;
  return <div className="geo-table-scroll"><table className="geo-table geo-report-table geo-lead-table">
    <thead><tr>
      <th className="geo-col-index">#</th>
      <th>全部事件</th>
      <th>地区</th>
      <th>IP 摘要</th>
      <th>时间</th>
    </tr></thead>
    <tbody>{rows.map((row, index) => <tr key={`${row.occurred_at}-${index}`}>
      <td className="geo-col-index">{start + index}</td>
      <td><span className="geo-lead-event">{row.event}</span><span className="geo-lead-source">{row.source}</span></td>
      <td>{row.region}</td>
      <td className="geo-cell-mono" title="只存 IP 哈希前 8 位，原文不落库">{row.ip_masked}</td>
      <td className="geo-cell-mono">{formatTime(row.occurred_at)}</td>
    </tr>)}</tbody>
  </table></div>;
}

/** 页码窗口：页数多时首尾 + 当前页左右各 2 页，中间用省略号收紧。 */
function pageWindow(page: number, pages: number): (number | "gap")[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, index) => index + 1);
  const items: (number | "gap")[] = [1];
  const start = Math.max(2, page - 2);
  const end = Math.min(pages - 1, page + 2);
  if (start > 2) items.push("gap");
  for (let value = start; value <= end; value += 1) items.push(value);
  if (end < pages - 1) items.push("gap");
  items.push(pages);
  return items;
}

function Pager({ page, pages, total, onChange, noun, pageSize, onPageSizeChange, centered }: {
  page: number; pages: number; total: number; onChange: (page: number) => void; noun: string;
  pageSize?: number; onPageSizeChange?: (size: number) => void; centered?: boolean;
}) {
  const [jump, setJump] = useState("");
  const submitJump = () => {
    const value = Number(jump);
    if (Number.isInteger(value) && value >= 1 && value <= pages) onChange(value);
    setJump("");
  };
  return <div className={`geo-pager ${centered ? "is-plain" : ""}`}>
    {!centered && <span className="geo-pager-total">共 {formatNumber(total)} 条{noun}</span>}
    <div className="geo-pager-controls">
      {pageSize && onPageSizeChange && <select className="geo-pager-size" value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))} aria-label="每页条数">
        {[10, 20, 50].map((size) => <option key={size} value={size}>{size} 条/页</option>)}
      </select>}
      <button type="button" className="geo-page-btn" disabled={page <= 1} onClick={() => onChange(page - 1)} aria-label="上一页">‹</button>
      {pageWindow(page, pages).map((item, index) => item === "gap"
        ? <span className="geo-page-gap" key={`gap-${index}`}>…</span>
        : <button type="button" key={item} className={`geo-page-btn ${item === page ? "is-current" : ""}`} onClick={() => onChange(item)} aria-current={item === page ? "page" : undefined}>{item}</button>)}
      <button type="button" className="geo-page-btn" disabled={page >= pages} onClick={() => onChange(page + 1)} aria-label="下一页">›</button>
      <label className="geo-page-jump">前往<input
        inputMode="numeric"
        value={jump}
        onChange={(event) => setJump(event.target.value.replace(/[^\d]/g, ""))}
        onKeyDown={(event) => { if (event.key === "Enter") submitJump(); }}
      />页</label>
    </div>
  </div>;
}

/** GEO 数据大屏：对外汇报用的单视图；demo 卡显式标注，不与真实数混合。 */
export function GeoBoardWorkspace({ mode, projectId, canRead }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean;
}) {
  const [days, setDays] = useState<number>(30);
  const [engineId, setEngineId] = useState<string | null>(null);
  const [reportKind, setReportKind] = useState<GeoBoardReportKind>("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZE);
  const [leadPage, setLeadPage] = useState(1);
  const [data, setData] = useState<GeoBoard | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  /** 默认浅色（贴竞品浅底报表）；深色留给现场投屏。 */
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const boardRef = useRef<HTMLDivElement | null>(null);

  const live = mode === "live" && canRead && !!projectId && projectId !== "all";

  useEffect(() => {
    if (!live) return;
    let active = true;
    setLoading(true);
    workbenchClient.geoBoard(projectId, { days, engineId: engineId ?? undefined, page, pageSize, leadPage, reportKind })
      .then((result) => {
        if (!active) return;
        setData(result);
        setError("");
      })
      .catch((cause) => {
        if (!active) return;
        setData(null);
        setError(cause instanceof Error ? cause.message : "数据大屏加载失败");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [live, projectId, days, engineId, reportKind, page, leadPage, reloadKey]);

  useEffect(() => {
    const onChange = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  if (mode === "mock") return <p className="geo-empty geo-empty-page">数据大屏只用真实接口模式；演示数据请在真实项目内查看（无记录时会显式标「演示」）。</p>;
  if (!canRead) return <p className="geo-empty geo-empty-page">当前账号没有统计查看权限。</p>;
  if (!projectId || projectId === "all") return <p className="geo-empty geo-empty-page">请先选择具体项目。</p>;

  const toggleFullscreen = async () => {
    if (!boardRef.current) return;
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await boardRef.current.requestFullscreen();
    } catch {
      setFullscreen((value) => !value);
    }
  };

  const changeDays = (value: number) => {
    setDays(value);
    setPage(1);
    setLeadPage(1);
  };
  const changeEngine = (value: string | null) => {
    setEngineId(value);
    setPage(1);
  };
  const changeReportKind = (value: GeoBoardReportKind) => {
    setReportKind(value);
    setPage(1);
  };

  return <div className={`geo-board ${theme === "dark" ? "is-dark" : ""} ${fullscreen ? "is-fullscreen" : ""}`} ref={boardRef}>
    <header className="geo-board-head">
      <div>
        <span className="geo-kicker">GEO · DATA BOARD</span>
        <h2>GEO 数据大屏</h2>
        <p>{data ? `窗口 ${data.project_window.start_date} ~ ${data.project_window.end_date} · ${data.project_window.timezone}` : "正在读取项目窗口…"}</p>
      </div>
      <div className="geo-board-actions">
        {DAY_OPTIONS.map((option) => <Button key={option} variant={days === option ? undefined : "secondary"} onClick={() => changeDays(option)}>近 {option} 天</Button>)}
        <Button variant="secondary" onClick={() => setReloadKey((value) => value + 1)}>刷新</Button>
        <Button variant="secondary" onClick={() => setTheme((value) => (value === "light" ? "dark" : "light"))}>{theme === "light" ? "深色" : "浅色"}</Button>
        <Button variant="secondary" onClick={() => { void toggleFullscreen(); }}>{fullscreen ? "退出全屏" : "全屏投屏"}</Button>
      </div>
    </header>

    {error && <p className="geo-error" role="alert">{error}</p>}
    {data?.has_demo && <p className="geo-demo-banner">本屏含「演示」样例卡：对应指标在本项目没有任何记录，卡片数字为内置样例，可直接替换为真实采集后的数值。</p>}

    <section className="geo-kpi-grid">
      {(data?.kpis ?? []).map((kpi) => <KpiCard key={kpi.key} kpi={kpi}/>)}
      {!data && loading && [0, 1, 2, 3].map((index) => <article className="geo-kpi is-skeleton" key={index}/>)}
    </section>

    <div className="geo-grid-2">
      <section className="geo-panel">
        <div className="geo-panel-head">
          <h3>Top 关键词</h3>
          <span>训练词 × 推荐词（关联问题数）</span>
        </div>
        {data?.top_keywords.items.length ? <ul className="geo-rank-list">
          {data.top_keywords.items.map((item) => <li key={item.keyword_id}>
            <b className={item.rank <= 3 ? "is-top" : ""}>{item.rank}</b>
            <div className="geo-rank-main">
              <strong>{item.name}</strong>
              <div className="geo-rank-track"><span style={{ width: `${Math.max(4, (item.citations / Math.max(1, Math.max(...data.top_keywords.items.map((row) => row.citations)))) * 100)}%` }}/></div>
            </div>
            <em>{item.questions}<small> 推荐词</small></em>
            <i>{item.citations}<small> 引用</small></i>
          </li>)}
        </ul> : <p className="geo-empty">{loading ? "正在加载关键词榜…" : "还没有启用中的关键词；先到「监测问题与关键词」建词。"}</p>}
      </section>

      <section className="geo-panel">
        <div className="geo-panel-head">
          <h3>累计收录量明细</h3>
          <span>{data?.indexed_series.source === "demo" ? "演示样例 · 曲线按日累计" : "近窗口按日累计 · 引用证据"}</span>
        </div>
        {data ? <CumulativeLine items={data.indexed_series.items}/> : <p className="geo-empty">正在加载收录曲线…</p>}
      </section>
    </div>

    <section className="geo-panel">
      <div className="geo-panel-head">
        <h3><i className="geo-panel-dot"/>各平台问题占比</h3>
        <span>近窗口有效样本数 · 共 {formatNumber(data?.engine_share.total ?? 0)} 条</span>
      </div>
      {data?.engine_share.items.length ? <EngineChart items={data.engine_share.items} total={data.engine_share.total}/>
        : <p className="geo-empty">{loading ? "正在加载平台占比…" : "还没有有效样本；先跑一轮监测任务。"}</p>}
    </section>

    <section className="geo-panel">
      <div className="geo-panel-head">
        <h3>报表明细</h3>
        <span>{data ? `更新时间 ${data.project_window.end_date}` : "按引擎看每个训练词在 AI 回答里引用了谁"}</span>
      </div>
      <div className="geo-report-kinds" role="tablist" aria-label="报表类型">
        {REPORT_KINDS.map((kind) => <button
          type="button"
          role="tab"
          key={kind.id}
          aria-selected={reportKind === kind.id}
          className={`geo-report-kind ${reportKind === kind.id ? "active" : ""}`}
          onClick={() => changeReportKind(kind.id)}
        ><Icon name={kind.icon} size={15}/>{kind.label}</button>)}
      </div>
      <p className="geo-report-notice">特别申明：引用证据来自 AI 回答快照，同一问题在不同时间、设备上可能给出不同结果，以「查看凭证」指向的原始链接为准。</p>
      <div className="geo-engine-tabs" role="tablist" aria-label="按引擎筛选报表明细">
        {(data?.report.engines ?? [{ engine_id: null, engine_name: "全部", value: 0 }]).map((engine, index) => <button
          type="button"
          role="tab"
          aria-selected={(engine.engine_id ?? null) === engineId}
          key={engine.engine_id ?? "all"}
          className={`geo-engine-tab ${(engine.engine_id ?? null) === engineId ? "active" : ""}`}
          onClick={() => changeEngine(engine.engine_id)}
        ><i className="geo-engine-logo" style={{ background: ENGINE_COLORS[index % ENGINE_COLORS.length] }}>{engine.engine_name.slice(0, 1)}</i>{engine.engine_name}<em>{formatNumber(engine.value)}</em></button>)}
      </div>
      {data ? <>
        <ReportTable rows={data.report.rows} start={(data.report.page - 1) * pageSize + 1}/>
        <Pager page={data.report.page} pages={data.report.pages} total={data.report.total} onChange={setPage} noun="引用" pageSize={pageSize} onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}/>
      </> : <p className="geo-empty">正在加载报表明细…</p>}
    </section>

    <section className="geo-panel">
      <div className="geo-panel-head">
        <h3>线索事件列表</h3>
        <span>访问官网 + 提交线索 · IP 只显示哈希前 8 位</span>
      </div>
      {data ? <>
        <LeadRows rows={data.lead_events.rows} start={(data.lead_events.page - 1) * PAGE_SIZE + 1}/>
        <Pager page={data.lead_events.page} pages={data.lead_events.pages} total={data.lead_events.total} onChange={setLeadPage} noun="事件" centered/>
      </> : <p className="geo-empty">正在加载线索事件…</p>}
    </section>

    {(data?.notes.length ?? 0) > 0 && <footer className="geo-board-notes">
      <h4>口径说明</h4>
      <ul>{data?.notes.map((note) => <li key={note}>{note}</li>)}</ul>
    </footer>}
  </div>;
}
