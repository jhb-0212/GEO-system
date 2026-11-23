"use client";

import { useEffect, useState } from "react";
import { Button, Panel } from "../ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { DashboardMetric, DashboardTracks } from "@/lib/workbench/types";

const DAY_OPTIONS = [7, 30, 90] as const;

function metricValue(metric: DashboardMetric) {
  if (metric.unit === "%") {
    return metric.value === null ? "无法计算" : `${(metric.value * 100).toFixed(1)}%`;
  }
  return String(metric.numerator);
}

/** 双轨大屏：两列并排，每列用自己的分母；中间刻意不放「合计」。 */
export function DashboardTracksWorkspace({ mode, projectId, canRead }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean;
}) {
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<DashboardTracks | null>(null);
  const [loadedKey, setLoadedKey] = useState("");
  const [error, setError] = useState("");

  const requestKey = `${mode}:${projectId}:${days}`;
  const loading = mode === "live" && canRead && !!projectId && projectId !== "all" && loadedKey !== requestKey;

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.dashboardTracks(projectId, days)
      .then((result) => { if (active) { setData(result); setError(""); setLoadedKey(requestKey); } })
      .catch((cause) => {
        if (!active) return;
        setData(null);
        setError(cause instanceof Error ? cause.message : "双轨数据加载失败");
        setLoadedKey(requestKey);
      });
    return () => { active = false; };
  }, [mode, canRead, projectId, days, requestKey]);

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">双轨大屏仅真实接口模式可用。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有统计查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  return <Panel className="knowledge-list-panel dashboard-tracks">
    <div className="panel-heading">
      <div><h3>双轨大屏</h3><p>{data?.disclaimer ?? "投放侧与测量侧分母不同，本屏不提供合并总分。"}</p></div>
      <div className="toolbar-extra">
        {DAY_OPTIONS.map((option) => (
          <Button key={option} variant={days === option ? undefined : "secondary"} onClick={() => setDays(option)}>近 {option} 天</Button>
        ))}
        <Button variant="secondary" onClick={() => setLoadedKey("")}>刷新</Button>
      </div>
    </div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {loading && <p className="knowledge-empty">正在加载双轨数据…</p>}
    {data && !loading && <div className="tracks-grid">
      {data.tracks.map((track) => (
        <div className={`tracks-col tracks-col-${track.track}`} key={track.track}>
          <div className="tracks-col-head">
            <strong>{track.label}</strong>
            <span>窗口 {track.window_days} 天</span>
          </div>
          <div className="tracks-metrics">
            {track.metrics.map((metric) => (
              <div className="tracks-metric" key={metric.key}>
                <span>{metric.label}</span>
                <strong className={metric.has_data ? "" : "tracks-metric-empty"}>{metricValue(metric)}</strong>
                <small>
                  {metric.unit === "%" ? `${metric.numerator} / ${metric.denominator}` : `共 ${metric.numerator} 条`}
                </small>
              </div>
            ))}
          </div>
          <ul className="tracks-notes">
            {track.notes.map((note) => <li key={note}>{note}</li>)}
          </ul>
        </div>
      ))}
    </div>}
    {data && !loading && <p className="tracks-footnote">两侧分母不同（任务 vs 样本），因此本屏不提供跨轨合计；需要跨轨判断时请回诊断报告逐项看。</p>}
  </Panel>;
}
