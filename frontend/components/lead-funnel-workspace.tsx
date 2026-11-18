"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Icon, Panel } from "./ui";
import { workbenchClient } from "@/lib/workbench/client";
import type { LeadFunnel, LeadFunnelGroup } from "@/lib/workbench/types";

const rate = (value: number | null) => value === null ? "--" : `${(value * 100).toFixed(1)}%`;

function GroupTable({ title, caption, rows }: { title: string; caption: string; rows: LeadFunnelGroup[] }) {
  return <div className="table-scroll"><table><thead><tr><th>{title}</th><th>总数</th><th>有效</th><th>已联系</th><th>已报名</th></tr></thead><tbody>
    {rows.map((item) => <tr key={item.key}><td><strong>{item.label}</strong></td><td>{item.total}</td><td>{item.valid}</td><td>{item.contacted}</td><td>{item.enrolled}</td></tr>)}
  </tbody></table>{!rows.length && <p className="knowledge-empty">{caption}</p>}</div>;
}

export function LeadFunnelWorkspace({ mode, projectId, leadAccess }: {
  mode: "mock" | "live"; projectId: string; leadAccess: "allowed" | "forbidden" | "unavailable";
}) {
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [funnel, setFunnel] = useState<LeadFunnel | null>(null);
  const [loadedKey, setLoadedKey] = useState("");
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const requestKey = `${projectId}:${startDate}:${endDate}:${reload}`;
  const loading = mode === "live" && leadAccess === "allowed" && !!projectId && projectId !== "all" && loadedKey !== requestKey;

  useEffect(() => {
    if (mode !== "live" || leadAccess !== "allowed" || !projectId || projectId === "all") return;
    let active = true;
    workbenchClient.leadFunnel(projectId, startDate || undefined, endDate || undefined)
      .then((data) => { if (active) { setFunnel(data); setError(""); setLoadedKey(requestKey); } })
      .catch((cause) => { if (active) { setFunnel(null); setError(cause instanceof Error ? cause.message : "线索漏斗加载失败"); setLoadedKey(requestKey); } });
    return () => { active = false; };
  }, [mode, projectId, leadAccess, startDate, endDate, requestKey]);

  if (mode === "mock") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">线索漏斗请切换到真实接口模式查看。</p></Panel>;
  if (leadAccess !== "allowed") return <Panel className="lead-permission-panel"><Icon name="lock" size={25}/><h3>{leadAccess === "forbidden" ? "当前账号无权查看线索" : "请先选择项目"}</h3><p>{leadAccess === "forbidden" ? "后端拒绝了这个项目的线索请求。项目、监测等其他页面仍可使用；如需线索权限，请联系项目管理员。" : "选择项目后再查看该项目的线索漏斗。"}</p></Panel>;
  if (!projectId || projectId === "all") return <Panel className="knowledge-list-panel"><p className="knowledge-empty">请先选择一个项目。</p></Panel>;

  return <div className="statistics-workspace">
    <Panel className="knowledge-list-panel">
      <div className="panel-heading">
        <div><h3>线索漏斗</h3><p>按创建时间筛选；日期按项目时区解析。已报名计入已联系，分母为咨询总量</p></div>
        <div className="toolbar-extra">
          <label className="date-field" htmlFor="funnel-start"><span>开始日期</span><input id="funnel-start" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
          <label className="date-field" htmlFor="funnel-end"><span>结束日期</span><input id="funnel-end" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
          {(startDate || endDate) && <Button variant="secondary" onClick={() => { setStartDate(""); setEndDate(""); }}>清空</Button>}
          <Button variant="secondary" icon="refresh" onClick={() => setReload((value) => value + 1)}>刷新</Button>
          {funnel && <Badge tone="blue">{funnel.total} 条线索</Badge>}
        </div>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && <p className="knowledge-empty">正在加载线索漏斗…</p>}
      {!loading && !funnel && !error && <p className="knowledge-empty">暂无线索数据</p>}
      {funnel && !loading && <>
        <div className="stats-cards">
          <div><span>咨询总量</span><strong>{funnel.total}</strong></div>
          <div><span>有效线索</span><strong>{funnel.valid}</strong></div>
          <div><span>已联系</span><strong>{funnel.contacted}</strong></div>
          <div><span>已报名</span><strong>{funnel.enrolled}</strong></div>
          <div><span>已流失</span><strong>{funnel.lost}</strong></div>
          <div><span>联系率</span><strong>{rate(funnel.contact_rate)}</strong></div>
        </div>
        <p className="stats-excluded">状态：未跟进 {funnel.status_counts.unknown} · 已联系 {funnel.status_counts.contacted} · 已报名 {funnel.status_counts.enrolled} · 已流失 {funnel.status_counts.lost}</p>
        <div className="table-scroll"><table><thead><tr><th>阶段</th><th>数量</th><th>占总线索</th><th>阶段转化</th></tr></thead><tbody>
          {funnel.stages.map((stage) => <tr key={stage.key}><td><strong>{stage.label}</strong></td><td>{stage.count}</td><td>{rate(stage.rate)}</td><td>{rate(stage.step_rate)}</td></tr>)}
        </tbody></table></div>
        <div className="panel-heading"><div><h3>按来源</h3><p>线索自报的原始来源，保留未归因分组</p></div><Badge tone="blue">{funnel.by_source.length} 组</Badge></div>
        <GroupTable title="来源" caption="暂无来源分组" rows={funnel.by_source} />
        <div className="panel-heading"><div><h3>按渠道</h3><p>发布回执渠道归因；未匹配时单列为未归因渠道</p></div><Badge tone="blue">{funnel.by_channel.length} 组</Badge></div>
        <GroupTable title="渠道" caption="暂无渠道分组" rows={funnel.by_channel} />
        <div className="panel-heading"><div><h3>按题目</h3><p>线索来源题目用于内容侧归因</p></div><Badge tone="blue">{funnel.by_question.length} 组</Badge></div>
        <GroupTable title="题目" caption="暂无题目分组" rows={funnel.by_question} />
      </>}
    </Panel>
  </div>;
}
