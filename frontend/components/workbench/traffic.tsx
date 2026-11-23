"use client";

import { useEffect, useState } from "react";
import { Button, Panel } from "../ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { TrafficSummary } from "@/lib/workbench/types";

const DAY_OPTIONS = [7, 30, 90] as const;
const DONUT_COLORS = ["#3d6be5", "#2f9e6f", "#e0a33c", "#8b6bd6", "#5d6c7e", "#c9574d"];

/** 纯 SVG 环图：渠道按事件数占比，不引图表库。 */
function Donut({ rows }: { rows: { label: string; value: number }[] }) {
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  if (total === 0) return <p className="knowledge-empty">窗口内没有渠道数据。</p>;
  const radius = 56;
  const circumference = 2 * Math.PI * radius;
  const segments = rows.map((row, index) => ({
    label: row.label,
    dash: (row.value / total) * circumference,
    color: DONUT_COLORS[index % DONUT_COLORS.length],
    order: index,
  }));
  const drawn = segments.map((segment) => ({
    ...segment,
    // 起点 = 前面所有扇形的长度之和；用纯函数算，避免渲染期改外部变量
    offset: segments.filter((item) => item.order < segment.order).reduce((sum, item) => sum + item.dash, 0),
  }));
  return <div className="traffic-donut">
    <svg viewBox="0 0 160 160" role="img" aria-label="渠道访问占比">
      {drawn.map((segment) => <circle
        key={segment.label}
        cx="80" cy="80" r={radius}
        fill="none"
        stroke={segment.color}
        strokeWidth="18"
        strokeDasharray={`${segment.dash} ${circumference - segment.dash}`}
        strokeDashoffset={-segment.offset}
      />)}
    </svg>
    <ul className="traffic-legend">
      {rows.map((row, index) => <li key={row.label}>
        <span className="traffic-swatch" style={{ background: DONUT_COLORS[index % DONUT_COLORS.length] }} />
        {row.label}
        <small>{row.value} · {((row.value / total) * 100).toFixed(1)}%</small>
      </li>)}
    </ul>
  </div>;
}

/** B3 流量：三个计数并列，渠道环图只画事件数占比。 */
export function TrafficWorkspace({ mode, projectId, canRead }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean;
}) {
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<TrafficSummary | null>(null);
  const [loadedKey, setLoadedKey] = useState("");
  const [error, setError] = useState("");

  const requestKey = `${mode}:${projectId}:${days}`;
  const loading = mode === "live" && canRead && !!projectId && projectId !== "all" && loadedKey !== requestKey;

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.trafficSummary(projectId, days)
      .then((result) => { if (active) { setData(result); setError(""); setLoadedKey(requestKey); } })
      .catch((cause) => {
        if (!active) return;
        setData(null);
        setError(cause instanceof Error ? cause.message : "流量数据加载失败");
        setLoadedKey(requestKey);
      });
    return () => { active = false; };
  }, [mode, canRead, projectId, days, requestKey]);

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">流量仅真实接口模式可用。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有统计查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  return <Panel className="knowledge-list-panel traffic-panel">
    <div className="panel-heading">
      <div><h3>流量</h3><p>PV、会话、去重访客各自计数；不做减法、不互相推算。</p></div>
      <div className="toolbar-extra">
        {DAY_OPTIONS.map((option) => (
          <Button key={option} variant={days === option ? undefined : "secondary"} onClick={() => setDays(option)}>近 {option} 天</Button>
        ))}
        <Button variant="secondary" onClick={() => setLoadedKey("")}>刷新</Button>
      </div>
    </div>

    {error && <p className="form-error" role="alert">{error}</p>}
    {loading && <p className="knowledge-empty">正在加载流量数据…</p>}

    {data && !loading && <>
      <div className="traffic-cards">
        <div className="traffic-card"><span>PV（访问次数）</span><strong>{data.totals.pv}</strong><small>非机器人事件条数</small></div>
        <div className="traffic-card"><span>会话数</span><strong>{data.totals.sessions}</strong><small>按 session_id 去重</small></div>
        <div className="traffic-card"><span>去重访客</span><strong>{data.totals.visitors}</strong><small>按 IP 哈希去重，原文不落库</small></div>
        <div className="traffic-card traffic-card-muted"><span>机器人访问（已剔除）</span><strong>{data.totals.bot_events}</strong><small>不进任何分母</small></div>
      </div>

      <div className="traffic-split">
        <div className="traffic-block">
          <h4>渠道（按事件数）</h4>
          <Donut rows={data.by_channel.map((row) => ({ label: row.channel, value: row.events }))} />
        </div>
        <div className="traffic-block">
          <h4>地区</h4>
          {data.by_region.length === 0
            ? <p className="knowledge-empty">窗口内没有地区数据（历史事件未带地区）。</p>
            : <table className="traffic-table">
              <thead><tr><th>地区</th><th>事件数</th><th>去重访客</th></tr></thead>
              <tbody>
                {data.by_region.map((row) => <tr key={row.region}>
                  <td>{row.region}</td><td>{row.events}</td><td>{row.visitors}</td>
                </tr>)}
              </tbody>
            </table>}
        </div>
      </div>

      <ul className="tracks-notes traffic-notes">
        {data.notes.map((note) => <li key={note}>{note}</li>)}
      </ul>
    </>}
  </Panel>;
}
