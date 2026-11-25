"use client";

import { useState } from "react";

import { Badge, Button, DetailModal, Icon, Panel, type IconName } from "../ui";
import { workbenchClient } from "@/lib/workbench/client";
import { formatAuditAction, formatAuditTarget, formatDateTime, formatIsoDate, formatSerialNo } from "@/lib/workbench/format";
import { PERMISSION, describeRole, groupPermissions } from "@/lib/workbench/permissions";
import type { Lead, MonitoringTask, Section, WorkbenchSnapshot } from "@/lib/workbench/types";
import { EmptyTable, TrendChart, displayUserName, engineGradient, projectName, statusTone } from "./shared";

/* ------------------------------------------------------------------
 * 这几个视图从 workbench-app.tsx 里搬出来，行为一字未改。
 * 目的：主文件只留「状态 + 布局 + 路由表」，页面级组件各占一个文件。
 * ------------------------------------------------------------------ */

export function Overview({ snapshot, projectName: nameOf, onNavigate, onTask }: { snapshot: WorkbenchSnapshot; projectName: (id: string) => string; onNavigate: (section: Section) => void; onTask: (task: MonitoringTask) => void }) {
  const demo = snapshot.source === "mock";
  const [trendDays, setTrendDays] = useState(14);
  const trendValues = snapshot.trend.slice(-trendDays);
  const trendDates = (snapshot.trendDates ?? []).slice(-trendDays);
  const trendStart = trendDates[0] ? formatIsoDate(trendDates[0]) : "";
  const trendEnd = trendDates[trendDates.length - 1] ? formatIsoDate(trendDates[trendDates.length - 1]) : "";
  const metrics = [
    { label: "在管项目", value: snapshot.projects.length.toString(), unit: "个", change: "+2", note: "全部可见项目", icon: "layers" as IconName, tone: "blue" },
    { label: demo ? "本周监测任务" : "监测任务", value: demo ? "48" : (snapshot.taskTotal ?? snapshot.tasks.length).toString(), unit: "项", change: "+12.8%", note: "当前项目累计", icon: "pulse" as IconName, tone: "cyan" },
    { label: "待处理审核", value: demo ? snapshot.reviews.filter((review) => review.status === "待审核").length.toString() : (snapshot.reviewTotal ?? snapshot.reviews.length).toString(), unit: "项", change: "需关注", note: "等待审核的内容", icon: "check" as IconName, tone: "amber" },
    { label: "当前可见线索", value: snapshot.leadAccess === "allowed" ? snapshot.leads.length.toString() : "—", unit: snapshot.leadAccess === "allowed" ? "条" : "", change: "+18.6%", note: snapshot.leadAccess === "allowed" ? "最新统计" : snapshot.leadAccess === "forbidden" ? "无查看权限" : "请先选择项目", icon: "users" as IconName, tone: "violet" },
  ];
  return <>{snapshot.truncated && <p className="knowledge-footnote" role="status">任务较多，当前先展示 {snapshot.tasks.length} / 共 {snapshot.taskTotal ?? snapshot.tasks.length} 条，待审内容展示 {snapshot.reviews.length} / 共 {snapshot.reviewTotal ?? snapshot.reviews.length} 条；上方计数为总数，更多明细请到对应页面查看。</p>}
    <div className="metrics-grid">{metrics.map((metric) => <Panel key={metric.label} className="metric-card"><div className="metric-top"><span>{metric.label}</span><span className={`metric-icon metric-${metric.tone}`}><Icon name={metric.icon} size={20}/></span></div><div className="metric-main"><strong>{metric.value}</strong><small>{metric.unit}</small></div><div className="metric-foot">{demo ? <><span className={metric.change === "需关注" ? "metric-attention" : "metric-growth"}>{metric.change !== "需关注" && <Icon name="arrowUp" size={12}/>} {metric.change}</span><span>较上周</span></> : <span>{metric.note}</span>}</div></Panel>)}</div>
    <div className="insights-grid"><Panel className="chart-panel"><div className="panel-heading"><div><h3>品牌提及趋势</h3><p>过去 {trendDays} 天{trendStart && trendEnd ? ` · ${trendStart} 至 ${trendEnd}` : ""}</p></div><details className="range-select"><summary><span>近 {trendDays} 天</span><Icon name="chevronDown" size={14}/></summary><div className="select-menu-list range-menu">{[7, 14, 30].map((value) => <button type="button" key={value} className={trendDays === value ? "selected" : ""} onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); setTrendDays(value); }}>近 {value} 天</button>)}</div></details></div><div className="chart-summary"><strong>{demo ? "76.8%" : snapshot.brandMentionRate === null || snapshot.brandMentionRate === undefined ? "—" : `${(snapshot.brandMentionRate * 100).toFixed(1)}%`}</strong><Badge tone="green">{demo ? "↑ 8.2%" : snapshot.trend.some((value) => value !== null) ? "有效样本" : "暂无样本"}</Badge></div><TrendChart values={trendValues} dates={trendDates} days={trendValues.length}/></Panel><Panel className="engine-panel"><div className="panel-heading"><div><h3>引擎覆盖分布</h3><p>不同 AI 引擎的任务占比</p></div><details className="more-menu"><summary aria-label="引擎分布更多操作"><Icon name="more" size={19}/></summary><div className="more-menu-list"><button type="button" onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); onNavigate("engines"); }}>查看引擎台账</button><button type="button" onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); onNavigate("statistics"); }}>查看统计看板</button><button type="button" onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); onNavigate("monitoring"); }}>查看监测任务</button></div></details></div>{snapshot.engines.length ? <><div className="engine-donut" aria-label="引擎任务占比" style={{ background: engineGradient(snapshot.engines) }}><div><strong>{snapshot.engines.length}</strong><span>个引擎</span></div></div><div className="engine-legend">{snapshot.engines.map((engine) => <div key={engine.name}><span><i style={{ backgroundColor: engine.color }}/>{engine.name}</span><strong>{engine.share}%</strong></div>)}</div></> : <div className="engine-empty">当前项目暂无任务分布</div>}</Panel></div>
    <div className="lower-grid"><Panel className="tasks-panel"><div className="panel-heading"><div><h3>近期监测任务</h3><p>需要持续跟进的任务进度</p></div><button className="text-link" onClick={() => onNavigate("monitoring")}>查看全部 <Icon name="arrowRight" size={15}/></button></div><div className="table-scroll"><table><thead><tr><th>任务 / 问题</th><th>项目</th><th>引擎</th><th>状态</th><th></th></tr></thead><tbody>{snapshot.tasks.slice(0, 3).map((task) => <tr key={task.id}><td><strong className="table-title">{task.question}</strong><small className="table-sub">任务 #{task.serialNo || "—"}</small></td><td>{nameOf(task.projectId)}</td><td>{task.engine}</td><td><Badge tone={statusTone(task.status)} dot>{task.status}</Badge></td><td><button className="icon-button" aria-label={`查看 ${task.question}`} onClick={() => onTask(task)}><Icon name="chevronRight" size={17}/></button></td></tr>)}</tbody></table>{!snapshot.tasks.length && <EmptyTable message="当前项目暂无监测任务"/>}</div></Panel><Panel className="activity-panel"><div className="panel-heading"><div><h3>最近动态</h3><p>团队协作与系统操作</p></div><button className="text-link" onClick={() => onNavigate("activity")}>查看全部 <Icon name="arrowRight" size={15}/></button></div><div className="activity-list">{snapshot.activities.slice(0, 3).map((activity) => <div className="activity-row" key={activity.id}><span className={`activity-dot dot-${activity.tone}`}/><div><p><strong>{activity.actor}</strong> {activity.action}</p><span>{activity.serialNo ? `操作 #${activity.serialNo} · ` : ""}{activity.target}</span><small>{activity.time}</small></div></div>)}{!snapshot.activities.length && <EmptyTable message={snapshot.permissions?.includes(PERMISSION.AUDIT_READ) ? "当前项目暂无操作记录" : "当前账号无审计查看权限"} />}</div></Panel></div>
  </>;
}

export function TableToolbar({ search, onSearch, status, onStatus, statuses, extra }: { search: string; onSearch: (value: string) => void; status?: string; onStatus?: (value: string) => void; statuses?: string[]; extra?: React.ReactNode }) {
  return <div className="table-toolbar"><div className="toolbar-left"><div className="search-field"><Icon name="search" size={18}/><input aria-label="搜索列表" placeholder="搜索名称、编号或关键词" value={search} onChange={(event) => onSearch(event.target.value)}/></div>{statuses && onStatus && <div className="filter-select"><Icon name="filter" size={16}/><select aria-label="筛选状态" value={status} onChange={(event) => onStatus(event.target.value)}><option value="all">全部状态</option>{statuses.map((item) => <option key={item}>{item}</option>)}</select><Icon name="chevronDown" size={14}/></div>}</div>{extra && <div className="toolbar-extra">{extra}</div>}</div>;
}

export function Projects({ projects, search, onSearch, canConfirm, onConfirm }: { projects: WorkbenchSnapshot["projects"]; search: string; onSearch: (value: string) => void; canConfirm: boolean; onConfirm: (project: WorkbenchSnapshot["projects"][number], priority: number) => void }) {
  const [priorities, setPriorities] = useState<Record<string, number>>({});
  const priorityOf = (project: WorkbenchSnapshot["projects"][number]) => priorities[project.id] ?? project.priority;
  const hasUnsavedPriority = (project: WorkbenchSnapshot["projects"][number]) => priorities[project.id] !== undefined && priorities[project.id] !== project.priority;
  return <Panel className="list-panel projects-panel"><div className="panel-heading list-heading"><div><h3>全部项目 <span className="count-chip">{projects.length}</span></h3><p>项目数据按当前账号的授权范围展示；优先级由业务负责人确认</p></div><Badge tone="blue">项目视图</Badge></div><TableToolbar search={search} onSearch={onSearch}/>
    <div className="table-scroll">
      <table className="projects-table">
        <thead><tr><th>项目名称</th><th>项目编号</th><th>负责人</th><th>优先级</th><th>资料确认</th><th>渠道数</th><th>监测任务</th><th>状态</th><th>最近更新</th></tr></thead>
        <tbody>{projects.map((project) => <tr key={project.id}>
          <td><span className="project-cell"><span className="project-mini-icon"><Icon name="layers" size={18}/></span><strong>{project.name}</strong></span></td>
          <td><code>{project.code}</code></td>
          <td>{project.owner}</td>
          <td>{canConfirm ? <select className="knowledge-filter" aria-label={`${project.name} 优先级`} value={priorityOf(project)} onChange={(event) => setPriorities((current) => ({ ...current, [project.id]: Number(event.target.value) }))}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>P{value}</option>)}</select> : `P${project.priority}`}{hasUnsavedPriority(project) && <Badge tone="amber">未保存</Badge>}</td>
          <td>{project.businessConfirmedAt ? <Badge tone="green">已确认</Badge> : <Badge tone="amber">待确认</Badge>}{canConfirm && <Button variant="quiet" onClick={() => onConfirm(project, priorityOf(project))}>{hasUnsavedPriority(project) ? "保存并确认" : project.businessConfirmedAt ? "重新确认" : "确认资料"}</Button>}</td>
          <td>{project.channels}</td><td>{project.tasks}</td>
          <td><Badge tone={statusTone(project.status)} dot>{project.status}</Badge></td>
          <td>{project.updatedAt}</td>
        </tr>)}</tbody>
      </table>
      {!projects.length && <EmptyTable message="没有匹配的项目"/>}
    </div>
    <div className="project-cards">{projects.map((project) => <article className="project-card" key={project.id}>
      <div className="project-card-head"><span className="project-cell"><span className="project-mini-icon"><Icon name="layers" size={18}/></span><strong>{project.name}</strong></span><Badge tone={statusTone(project.status)} dot>{project.status}</Badge></div>
      <div className="project-card-meta"><code>{project.code}</code><span>{project.owner}</span><span>更新 {project.updatedAt}</span></div>
      <div className="project-card-stats"><span>渠道 <b>{project.channels}</b></span><span>任务 <b>{project.tasks}</b></span><span>优先级 <b>P{priorityOf(project)}</b></span></div>
      <div className="project-card-foot">
        {canConfirm ? <select className="knowledge-filter" aria-label={`${project.name} 优先级`} value={priorityOf(project)} onChange={(event) => setPriorities((current) => ({ ...current, [project.id]: Number(event.target.value) }))}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>P{value}</option>)}</select> : null}
        {project.businessConfirmedAt ? <Badge tone="green">已确认</Badge> : <Badge tone="amber">待确认</Badge>}
        {canConfirm && <Button variant="secondary" onClick={() => onConfirm(project, priorityOf(project))}>{hasUnsavedPriority(project) ? "保存" : "确认"}</Button>}
      </div>
    </article>)}</div>
    <div className="table-footer">显示 {projects.length} 个项目 <span>{canConfirm ? "优先级改完需点「保存并确认」才会保存" : "当前账号无确认权限"}</span></div>
  </Panel>;
}

export function Monitoring({ snapshot, tasks, search, status, onSearch, onStatus, onTask, onManualTask, onNotice }: { snapshot: WorkbenchSnapshot; tasks: MonitoringTask[]; search: string; status: string; onSearch: (value: string) => void; onStatus: (value: string) => void; onTask: (task: MonitoringTask) => void; onManualTask: (task: MonitoringTask) => void; onNotice: (message: string) => void }) {
  const [entryHelp, setEntryHelp] = useState<MonitoringTask | null>(null);
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const totalPages = Math.max(1, Math.ceil(tasks.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageTasks = tasks.slice((safePage - 1) * pageSize, safePage * pageSize);

  function changeSearch(value: string) {
    setPage(1);
    onSearch(value);
  }

  function changeStatus(value: string) {
    setPage(1);
    onStatus(value);
  }

  function changePage(next: number) {
    setPage(next);
    if (typeof document !== "undefined") document.querySelector(".monitor-list")?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function copyQuestion(task: MonitoringTask) {
    const text = task.questionTitle || task.question;
    if (!navigator.clipboard?.writeText) {
      onNotice("当前环境不支持自动复制，请手动复制题目");
      return;
    }
    void navigator.clipboard.writeText(text)
      .then(() => onNotice("题目原文已复制"))
      .catch(() => onNotice("题目复制失败，请手动复制"));
  }

  function openAppEntry(task: MonitoringTask) {
    copyQuestion(task);
    if (task.engineCode === "wechat_search_ai") {
      setEntryHelp(task);
      onNotice("微信搜一搜是 App 内灰度入口，请按步骤操作");
      return;
    }
    if (!task.entryUrl) {
      onNotice("该入口尚未配置官方 URL，请按平台入口页人工打开");
      return;
    }
    window.open(task.entryUrl, "_blank", "noopener,noreferrer");
    onNotice("已在新标签打开官方入口，当前页将跳到该任务的手测表单");
    onManualTask(task);
  }

  const taskSnapshot = snapshot.tasks;
  const taskTotal = snapshot.taskTotal ?? taskSnapshot.length;
  const pendingCount = taskSnapshot.filter((task) => task.status === "待执行").length;
  const doneCount = taskSnapshot.filter((task) => task.status === "已完成").length;
  const failedCount = taskSnapshot.filter((task) => task.status === "失败").length;
  const cancelledCount = taskSnapshot.filter((task) => task.status === "已取消").length;

  return <><div className="section-stat-row section-stat-row-five"><div><Icon name="pulse" size={20}/><span>任务总数</span><strong>{taskTotal}</strong></div><div><Icon name="clock" size={20}/><span>待执行</span><strong>{pendingCount}</strong></div><div><Icon name="check" size={20}/><span>已完成</span><strong>{doneCount}</strong></div><div><Icon name="bell" size={20}/><span>失败</span><strong>{failedCount}</strong></div><div><Icon name="close" size={20}/><span>已取消</span><strong>{cancelledCount}</strong></div></div><Panel className="list-panel"><div className="panel-heading list-heading"><div><h3>监测任务列表</h3><p>按问题、引擎和执行状态查看任务；网页端、手机客户端与应用内入口可跳到手测表单，网页端还可打开官方入口</p></div><Badge tone="slate">执行记录</Badge></div><TableToolbar search={search} onSearch={changeSearch} status={status} onStatus={changeStatus} statuses={["待执行", "进行中", "需复核", "已完成", "失败", "已取消", "待核实"]}/>
<div className="monitor-list">
  {pageTasks.map((task) => {
    const manualEntryTask = (task.entryType === "app_search" || task.entryType === "web_user" || task.entryType === "app_user") && task.status === "待执行";
    const entryKindName = task.entryType === "web_user" ? "网页端" : task.entryType === "app_user" ? "手机客户端" : "应用内";
    const showEntryLink = manualEntryTask && task.entryType !== "app_user";
    return <article className="monitor-row" key={task.id}>
      <div className="monitor-row-main">
        <div className="monitor-row-meta">
          <span className="monitor-id">任务 #{task.serialNo || "—"}</span>
          <span>{projectName(snapshot, task.projectId)}</span>
          <span>{task.engine}{manualEntryTask ? ` · ${task.entryName || `${entryKindName}入口`} · 人工采样` : ""}</span>
        </div>
        <strong className="monitor-question">{task.question}</strong>
        <small className="monitor-updated">更新于 {formatDateTime(task.updatedAt)}</small>
      </div>
      <div className="monitor-row-side">
        <Badge tone={statusTone(task.status)} dot>{task.status}</Badge>
        <div className="monitor-actions">
          {showEntryLink && <Button variant="quiet" onClick={() => openAppEntry(task)}>{task.engineCode === "wechat_search_ai" ? "操作步骤" : "打开入口"}</Button>}
          {manualEntryTask && <Button variant="quiet" onClick={() => onManualTask(task)}>去采样</Button>}
          <button className="icon-button" aria-label={`查看 ${task.question}`} onClick={() => onTask(task)}><Icon name="eye" size={17}/></button>
        </div>
      </div>
    </article>;
  })}
  {!tasks.length && <EmptyTable message={snapshot.source === "live" ? "当前项目暂无可访问的监测任务" : "没有匹配的任务"}/>}
</div>
<div className="table-footer monitor-footer"><span>共 {snapshot.taskTotal ?? tasks.length} 条任务 · 第 {safePage} / {totalPages} 页，每页 {pageSize} 条{snapshot.truncated ? ` · 当前已加载 ${tasks.length} 条` : ""}</span><div className="monitor-pager"><Button variant="secondary" disabled={safePage <= 1} onClick={() => changePage(safePage - 1)}>上一页</Button><Button variant="secondary" disabled={safePage >= totalPages} onClick={() => changePage(safePage + 1)}>下一页</Button></div></div>
</Panel>{entryHelp && <DetailModal eyebrow="APP SEARCH" title={entryHelp.engine} subtitle="应用内入口人工采样步骤" onClose={() => setEntryHelp(null)}><p className="knowledge-footnote">微信搜一搜 AI 为 App 内灰度入口，网页 URL 不是搜索页；系统不提供网页直达，也不自动登录或抓取。</p><ol className="entry-steps"><li>打开微信 App，进入“发现 → 搜一搜”。</li><li>输入题目原文并触发 AI 搜索。</li><li>打开回答里的参考资料，复制需要登记的来源 URL。</li><li>回到工作台点“去采样”，在该任务的手测表单粘贴回答与来源。</li></ol><div className="knowledge-actions"><Button onClick={() => { const target = entryHelp; setEntryHelp(null); onManualTask(target); }}>去人工采样</Button><Button variant="secondary" onClick={() => setEntryHelp(null)}>关闭</Button></div></DetailModal>}</>;
}

export function Leads({ snapshot, leads, search, status, onSearch, onStatus, onExport, onUpdate, canExport, canWrite }: { snapshot: WorkbenchSnapshot; leads: Lead[]; search: string; status: string; onSearch: (value: string) => void; onStatus: (value: string) => void; onExport: () => void; onUpdate: (lead: Lead, status: Lead["status"]) => void; canExport: boolean; canWrite: boolean }) {
  if (snapshot.leadAccess !== "allowed") return <Panel className="lead-permission-panel"><Icon name="lock" size={25}/><h3>{snapshot.leadAccess === "forbidden" ? "当前账号无权查看线索" : "请先选择项目"}</h3><p>{snapshot.leadAccess === "forbidden" ? "当前账号无权查看这个项目的线索。其他页面仍可使用；如需线索权限，请联系项目管理员。" : "选择项目后再查看该项目的线索。"}</p></Panel>;
  return <Panel className="list-panel"><div className="panel-heading list-heading"><div><h3>咨询线索 <span className="count-chip">{leads.length}</span></h3><p>统一管理来自不同渠道的咨询信息</p></div><Badge tone="blue">线索视图</Badge></div><TableToolbar search={search} onSearch={onSearch} status={status} onStatus={onStatus} statuses={["待跟进", "跟进中", "已转化"]} extra={<Button variant="secondary" icon="download" disabled={!canExport} onClick={onExport}>导出当前列表</Button>}/><div className="table-scroll"><table><thead><tr><th>线索编号</th><th>联系人</th><th>联系电话</th><th>意向内容</th><th>自报 AI 产品</th><th>有效性</th><th>来源</th><th>所属项目</th><th>负责人</th><th>状态</th><th>备注</th><th>创建时间</th></tr></thead><tbody>{leads.map((lead) => <tr key={lead.id}><td><strong>线索 #{lead.serialNo || "—"}</strong></td><td><strong className="table-title">{lead.contactName}</strong></td><td>{lead.phone}</td><td>{lead.interest}</td><td>{lead.reportedAiProduct || "—"}</td><td>{lead.isValid === false ? <Badge tone="red">无效</Badge> : <Badge tone="green">有效</Badge>}</td><td>{lead.source}</td><td>{projectName(snapshot, lead.projectId)}</td><td>{lead.ownerName ?? "—"}</td><td><select className="knowledge-filter" aria-label="更新线索状态" value={lead.status} disabled={snapshot.source !== "live" || !canWrite} onChange={(event) => onUpdate(lead, event.target.value as Lead["status"])}><option value="待跟进">待跟进</option><option value="跟进中">跟进中</option><option value="已转化">已转化</option><option value="已流失">已流失</option></select></td><td>{lead.note ?? "—"}</td><td>{lead.createdAt}</td></tr>)}</tbody></table>{!leads.length && <EmptyTable message="没有匹配的线索"/>}</div><div className="table-footer">显示 {leads.length} 条线索 <span>导出会记录操作人，仅限有权限的账号</span></div></Panel>;
}

export function ActivityView({ snapshot }: { snapshot: WorkbenchSnapshot }) {
  const projectId = snapshot.activeProjectId ?? "";
  const [items, setItems] = useState(snapshot.activities);
  const [total, setTotal] = useState(snapshot.activityTotal ?? snapshot.activities.length);
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const visible = expanded ? items : items.slice(0, 6);
  const hasMore = items.length < total;
  async function loadMore() {
    if (!projectId || loading) return;
    setLoading(true);
    setError("");
    try {
      const result = await workbenchClient.auditLogs(projectId, page + 1, 20);
      const mapped = result.data.map((row) => ({
        id: row.id,
        serialNo: formatSerialNo(row.serial_no),
        actor: row.actor_name ?? "未知操作者",
        action: row.action,
        target: formatAuditTarget(row.target_type),
        time: formatDateTime(row.created_at),
        tone: "blue" as const,
      }));
      setItems((current) => [...current, ...mapped.filter((row) => !current.some((prev) => prev.id === row.id))]);
      setTotal(result.meta?.total ?? total);
      setPage((value) => value + 1);
      setExpanded(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "操作记录加载失败");
    } finally {
      setLoading(false);
    }
  }
  return <Panel className="list-panel"><div className="panel-heading list-heading"><div><h3>最近 {visible.length} 条操作记录</h3><p>关键动作的时间线与责任人</p></div><div className="activity-heading-actions"><Badge tone="slate">已加载 {items.length} / 共 {total} 条</Badge>{!expanded && items.length > 6 && <Button variant="secondary" onClick={() => setExpanded(true)}>展开已加载的 {items.length} 条</Button>}{expanded && hasMore && <Button variant="secondary" disabled={loading} onClick={() => void loadMore()}>{loading ? "加载中…" : "加载更多"}</Button>}{expanded && !hasMore && items.length > 6 && <Button variant="secondary" onClick={() => setExpanded(false)}>收起</Button>}</div></div>{error && <p className="knowledge-footnote">{error}</p>}<div className="timeline">{visible.map((activity) => <div className="timeline-item" key={activity.id}><span className={`timeline-marker dot-${activity.tone}`}/><div><div className="timeline-line"><strong>{activity.actor}</strong><span>{formatAuditAction(activity.action)}</span><small>{activity.time}</small></div><p>{activity.serialNo ? `操作 #${activity.serialNo} · ` : ""}{activity.target}</p></div></div>)}{!items.length && <EmptyTable message={snapshot.permissions?.includes(PERMISSION.AUDIT_READ) ? "当前项目暂无操作记录" : "当前账号无审计查看权限"}/>}</div></Panel>;
}

export function ProfileView({ snapshot }: { snapshot: WorkbenchSnapshot }) {
  const live = snapshot.source === "live";
  const name = live ? displayUserName(snapshot.userName) : "演示账号";
  const loginName = live ? (snapshot.username ?? "—") : "demo";
  const globalRole = snapshot.isSystemAdmin ? "系统管理员" : (live ? "普通成员" : "项目成员");
  const projectRole = snapshot.projectRoleCode ? describeRole(snapshot.projectRoleCode, false) : null;
  const sessionLabel = live ? "当前登录" : "演示登录";
  const permissions = snapshot.permissions ?? [];
  const groups = groupPermissions(permissions);
  const projects = snapshot.projects;
  const initial = name.trim().charAt(0).toUpperCase() || "U";
  return <div className="profile-grid">
    <Panel className="profile-hero" collapsible={false}>
      <div className="profile-hero-main">
        <span className="avatar profile-avatar">{initial}</span>
        <div className="profile-main">
          <div className="profile-title-row"><strong>{name}</strong><Badge tone={snapshot.isSystemAdmin ? "blue" : "slate"} dot>{globalRole}</Badge>{projectRole && <Badge tone="slate" dot>{projectRole}</Badge>}</div>
          <p className="profile-login"><Icon name="user" size={13}/> {loginName}</p>
          <p className="profile-session"><Icon name="lock" size={13}/> {sessionLabel}</p>
        </div>
      </div>
      <div className="profile-hero-side">
        <div className="profile-stat"><span>{projects.length}</span><small>可访问项目</small></div>
        <div className="profile-stat"><span>{permissions.length}</span><small>项目能力</small></div>
      </div>
    </Panel>
    <Panel className="profile-panel">
      <div className="panel-heading"><div><h3>访问权限</h3><p>当前账号在所选项目下具备的能力，按业务域分组</p></div><Badge tone="slate">{permissions.length} 项</Badge></div>
      {groups.length ? (
        <div className="profile-perm-groups">
          {groups.map((group) => (
            <div className="profile-perm-group" key={group.group}>
              <div className="profile-perm-group-title">{group.group}</div>
              <div className="profile-perm-items">
                {group.items.map((item) => (
                  <span className="profile-perm" key={item.code}>
                    <span className="profile-perm-name">{item.name}</span>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : <EmptyTable message="当前账号暂无额外权限标识" />}
    </Panel>
    <Panel className="profile-panel">
      <div className="panel-heading"><div><h3>可访问项目</h3><p>当前账号被授权进入的项目</p></div><Badge tone="blue">{projects.length} 个</Badge></div>
      <div className="profile-projects">
        {projects.map((project) => (
          <div key={project.id} className="profile-project">
            <span className="project-mini-icon"><Icon name="layers" size={17}/></span>
            <div className="profile-project-main"><strong>{project.name}</strong></div>
            <div className="profile-project-meta">
              <Badge tone={statusTone(project.status)} dot>{project.status}</Badge>
              {project.roleCode && <Badge tone="slate">{describeRole(project.roleCode, false)}</Badge>}
            </div>
          </div>
        ))}
        {!projects.length && <EmptyTable message="暂无可访问项目" />}
      </div>
    </Panel>
  </div>;
}
