"use client";

import { useEffect, useState } from "react";
import { Button, Panel } from "../ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { HealthCheckItemRecord, HealthCheckRun, HealthCheckRunSummary } from "@/lib/workbench/types";

const STATUS_TEXT: Record<string, string> = { pass: "达成", fail: "未达成", unknown: "无法计算" };
const CATEGORY_ORDER = ["知识库", "测量", "投放", "对外"];

function ratioText(item: HealthCheckItemRecord) {
  if (item.denominator === 0) return `${item.numerator} / 0`;
  if (item.unit === "%") return `${item.numerator} / ${item.denominator}（${(item.numerator / item.denominator * 100).toFixed(1)}%）`;
  return `${item.numerator} / ${item.denominator} ${item.unit}`;
}

function stamp(iso: string) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

/** B5 体检：逐项达成率，不合成总分。 */
export function HealthCheckWorkspace({ mode, projectId, canRead }: {
  mode: "mock" | "live"; projectId: string; canRead: boolean;
}) {
  const [data, setData] = useState<HealthCheckRun | null>(null);
  const [history, setHistory] = useState<HealthCheckRunSummary[]>([]);
  const [selected, setSelected] = useState<string>("latest");
  const [loadedKey, setLoadedKey] = useState("");
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);

  const requestKey = `${mode}:${projectId}:${selected}`;
  const loading = mode === "live" && canRead && !!projectId && projectId !== "all" && loadedKey !== requestKey;

  useEffect(() => {
    if (mode !== "live" || !canRead || !projectId || projectId === "all") return;
    let active = true;
    const load = async () => {
      try {
        const runs = await workbenchClient.healthCheckHistory(projectId);
        if (!active) return;
        setHistory(runs);
        if (runs.length === 0) {
          setData(null);
          setError("");
          setLoadedKey(requestKey);
          return;
        }
        const target = selected === "latest" ? runs[0].run_id : selected;
        const snapshot = await workbenchClient.healthCheckRun(projectId, target);
        if (!active) return;
        setData(snapshot);
        setError("");
        setLoadedKey(requestKey);
      } catch (cause) {
        if (!active) return;
        setData(null);
        setError(cause instanceof Error ? cause.message : "体检数据加载失败");
        setLoadedKey(requestKey);
      }
    };
    void load();
    return () => { active = false; };
  }, [mode, canRead, projectId, selected, requestKey]);

  const runNow = async () => {
    if (!projectId || projectId === "all" || running) return;
    setRunning(true);
    setError("");
    try {
      const snapshot = await workbenchClient.runHealthCheck(projectId);
      setData(snapshot);
      setHistory((current) => [{
        run_id: snapshot.run_id, ruleset_version: snapshot.ruleset_version,
        created_at: snapshot.created_at, totals: snapshot.totals,
      }, ...current].slice(0, 20));
      setSelected("latest");
      setLoadedKey("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "体检执行失败");
    } finally {
      setRunning(false);
    }
  };

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">体检仅真实接口模式可用。</p></Panel>;
  if (!canRead) return <Panel className="knowledge-list-panel"><p className="knowledge-empty">当前账号没有统计查看权限。</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择具体项目。</p></Panel>;

  const grouped = CATEGORY_ORDER
    .map((category) => ({ category, items: data?.items.filter((item) => item.category === category) ?? [] }))
    .filter((group) => group.items.length > 0);

  return <Panel className="knowledge-list-panel health-check">
    <div className="panel-heading">
      <div>
        <h3>体检</h3>
        <p>{data ? `规则版本 ${data.ruleset_version} · 生成于 ${stamp(data.created_at)}` : "跑一次体检，逐项看哪一项没做。"}</p>
      </div>
      <div className="toolbar-extra">
        {history.length > 0 && <select className="health-history" value={selected} onChange={(event) => setSelected(event.target.value)}>
          <option value="latest">最近一次</option>
          {history.map((run) => <option key={run.run_id} value={run.run_id}>{stamp(run.created_at)} · 通过 {run.totals.passed}/{run.totals.total}</option>)}
        </select>}
        <Button variant="secondary" onClick={() => { setLoadedKey(""); void runNow(); }} disabled={running}>
          {running ? "正在体检…" : data ? "重新体检" : "跑一次体检"}
        </Button>
      </div>
    </div>

    {error && <p className="form-error" role="alert">{error}</p>}
    {loading && <p className="knowledge-empty">正在加载体检结果…</p>}

    {!loading && !data && !error && <p className="knowledge-empty">这个项目还没有跑过体检。</p>}

    {data && !loading && <>
      <div className="health-totals">
        <div className="health-total"><span>共</span><strong>{data.totals.total}</strong><span>项</span></div>
        <div className="health-total health-total-pass"><span>达成</span><strong>{data.totals.passed}</strong></div>
        <div className="health-total health-total-fail"><span>未达成</span><strong>{data.totals.failed}</strong></div>
        <div className="health-total health-total-unknown"><span>无法计算</span><strong>{data.totals.unknown}</strong></div>
        <small>这里只是项数计数，不折算成百分制总分。</small>
      </div>

      {grouped.map((group) => (
        <div className="health-group" key={group.category}>
          <h4>{group.category}</h4>
          <div className="health-rows">
            {group.items.map((item) => (
              <div className={`health-row health-row-${item.status}`} key={item.check_key}>
                <span className={`health-pill health-pill-${item.status}`}>{STATUS_TEXT[item.status]}</span>
                <div className="health-main">
                  <strong>{item.label}</strong>
                  <small>{ratioText(item)} · 目标 ≥{item.target_percent}%</small>
                  {item.status !== "pass" && <p className="health-hint">{item.hint}</p>}
                </div>
                <span className="health-ratio">{item.ratio === null ? "—" : `${(item.ratio * 100).toFixed(0)}%`}</span>
              </div>
            ))}
          </div>
        </div>
      ))}

      <p className="health-footnote">{data.disclaimer ?? "体检只逐项算达成率，不合成总分；分母为 0 的项标「无法计算」，不按 0 分处理。"}</p>
    </>}
  </Panel>;
}
