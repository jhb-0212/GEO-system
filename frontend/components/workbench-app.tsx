"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Badge, Button, Icon, Panel, SelectInput, TextInput, type IconName } from "./ui";
import { FaqWorkspace, MaterialsWorkspace } from "./knowledge-workbench";
import { initialDemoRounds, MonitoringRounds } from "./monitoring-rounds";
import { ChannelsWorkspace } from "./channels-workspace";
import { EnginesWorkspace } from "./engines-workspace";
import { StatisticsWorkspace } from "./statistics-workspace";
import { QuestionsWorkspace } from "./questions-workspace";
import { SamplesWorkspace } from "./samples-workspace";
import { PublishingWorkspace } from "./publishing-workspace";
import { DiagnosticsWorkspace } from "./diagnostics-workspace";
import { ContentWorkspace } from "./content-workspace";
import { workbenchClient } from "@/lib/workbench/client";
import type { Lead, MonitoringRound, MonitoringTask, ReviewItem, Section, Tone, WorkbenchSnapshot } from "@/lib/workbench/types";

const navigation: { id: Section; label: string; icon: IconName; group: "workspace" | "system" }[] = [
  { id: "overview", label: "工作概览", icon: "grid", group: "workspace" },
  { id: "projects", label: "项目管理", icon: "layers", group: "workspace" },
  { id: "monitoring", label: "监测任务", icon: "pulse", group: "workspace" },
  { id: "diagnostics", label: "内部排障", icon: "pulse", group: "system" },
  { id: "questions", label: "题库与目标词", icon: "blocks", group: "workspace" },
  { id: "samples", label: "样本与引用", icon: "check", group: "workspace" },
  { id: "publishing", label: "内容发布", icon: "layers", group: "workspace" },
  { id: "channels", label: "渠道台账", icon: "folder", group: "workspace" },
  { id: "statistics", label: "统计看板", icon: "grid", group: "workspace" },
  { id: "reviews", label: "内容审核", icon: "check", group: "workspace" },
  { id: "leads", label: "线索管理", icon: "users", group: "workspace" },
  { id: "faq", label: "FAQ 编辑", icon: "blocks", group: "workspace" },
  { id: "materials", label: "素材管理", icon: "folder", group: "workspace" },
  { id: "activity", label: "操作日志", icon: "history", group: "system" },
  { id: "engines", label: "AI 平台入口", icon: "blocks", group: "system" },
  { id: "components", label: "组件规范", icon: "blocks", group: "system" },
];

const sectionInfo: Record<Section, { title: string; subtitle: string }> = {
  overview: { title: "工作概览", subtitle: "掌握项目进展与值得关注的变化" },
  projects: { title: "项目管理", subtitle: "统一查看在管项目与运行状态" },
  monitoring: { title: "监测任务", subtitle: "追踪各引擎采样任务的执行进度" },
  diagnostics: { title: "内部排障", subtitle: "集中查看失败样本、失败码、重试与 trace" },
  questions: { title: "题库与目标词", subtitle: "管理监测问题、版本与目标词" },
  samples: { title: "样本与引用", subtitle: "回看回答、复核样本和引用归属" },
  publishing: { title: "内容发布", subtitle: "登记账号、建任务、回填回执与核实" },
  channels: { title: "渠道台账", subtitle: "管理渠道、域名与归属" },
  statistics: { title: "统计看板", subtitle: "查看有效回答与品牌呈现" },
  reviews: { title: "内容审核", subtitle: "处理待审核内容与证据复核" },
  leads: { title: "线索管理", subtitle: "整理咨询线索与跟进进度" },
  faq: { title: "FAQ 编辑", subtitle: "整理常见问题、答案与展示状态" },
  materials: { title: "素材管理", subtitle: "整理品牌图片、文档与案例素材" },
  activity: { title: "操作日志", subtitle: "查看关键操作与协作记录" },
  engines: { title: "AI 平台入口", subtitle: "查看平台目录，维护入口并测试连接" },
  components: { title: "组件规范", subtitle: "工作台基础组件的统一样式" },
};

function statusTone(status: string): Tone {
  if (["运行中", "已完成", "已通过", "已转化"].includes(status)) return "green";
  if (["进行中", "跟进中"].includes(status)) return "blue";
  if (["需复核", "待审核", "待跟进", "筹备中"].includes(status)) return "amber";
  if (["已驳回", "失败", "已流失"].includes(status)) return "red";
  return "slate";
}

function projectName(snapshot: WorkbenchSnapshot, id: string) {
  return snapshot.projects.find((project) => project.id === id)?.name ?? "未知项目";
}

function TrendChart({ values }: { values: (number | null)[] }) {
  if (!values.some((value) => value !== null)) return <div className="chart-empty">暂无有效样本</div>;
  const segments: string[] = [];
  let active: string[] = [];
  values.forEach((value, index) => {
    if (value === null) { if (active.length) segments.push(active.join(" ")); active = []; }
    else active.push(`${28 + index * (517 / Math.max(1, values.length - 1))},${160 - value * 1.28}`);
  });
  if (active.length) segments.push(active.join(" "));
  return <div className="trend-chart"><div className="chart-y"><span>100%</span><span>75%</span><span>50%</span><span>25%</span></div><svg viewBox="0 0 585 180" role="img" aria-label="近十二周品牌提及率变化"><path d="M28 31H558M28 75H558M28 119H558M28 163H558" stroke="#e9edf3" strokeDasharray="4 5"/>{segments.map((points, index) => <polyline key={index} points={points} fill="none" stroke="#3e70ef" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>)}</svg><div className="chart-x"><span>12 周前</span><span>6 周前</span><span>本周</span></div></div>;
}

function Header({ title, subtitle, action }: { title: string; subtitle: string; action?: React.ReactNode }) {
  return <div className="section-header"><div><div className="breadcrumb">GEO 工作台 <Icon name="chevronRight" size={14} /> {title}</div><h1>{title}</h1><p>{subtitle}</p></div>{action && <div className="section-actions">{action}</div>}</div>;
}

function EmptyTable({ message }: { message: string }) {
  return <div className="empty-table"><span className="empty-icon"><Icon name="folder" size={24} /></span><strong>暂无数据</strong><p>{message}</p></div>;
}

function readDemoRounds(): { rounds: MonitoringRound[]; generatedKeys: string[] } {
  const fallback = { rounds: initialDemoRounds.map((round) => ({ ...round })), generatedKeys: [] as string[] };
  if (typeof window === "undefined") return fallback;
  try {
    const saved = window.sessionStorage.getItem("geo-monitoring-rounds-demo-v1");
    if (!saved) return fallback;
    const parsed: unknown = JSON.parse(saved);
    if (!parsed || typeof parsed !== "object") return fallback;
    const data = parsed as { rounds?: unknown; generatedKeys?: unknown };
    return {
      rounds: Array.isArray(data.rounds) ? data.rounds.filter((round): round is MonitoringRound => round && typeof round.id === "string" && typeof round.project_id === "string" && typeof round.seq === "number") : fallback.rounds,
      generatedKeys: Array.isArray(data.generatedKeys) ? data.generatedKeys.filter((key): key is string => typeof key === "string") : fallback.generatedKeys,
    };
  } catch { return fallback; }
}

export function WorkbenchApp() {
  const router = useRouter();
  const [section, setSection] = useState<Section>("overview");
  const [snapshot, setSnapshot] = useState<WorkbenchSnapshot | null>(null);
  const [projectId, setProjectId] = useState("all");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [leadModal, setLeadModal] = useState(false);
  const [taskDetail, setTaskDetail] = useState<MonitoringTask | null>(null);
  const [mobileNav, setMobileNav] = useState(false);
  const [saving, setSaving] = useState(false);
  const [leadForm, setLeadForm] = useState({ contactName: "", phone: "", interest: "", source: "官网表单" });
  const [demoRounds, setDemoRounds] = useState<MonitoringRound[]>(() => readDemoRounds().rounds);
  const [generatedRoundKeys, setGeneratedRoundKeys] = useState<string[]>(() => readDemoRounds().generatedKeys);
  const snapshotRequestId = useRef(0);

  useEffect(() => {
    if (snapshot?.source !== "mock") return;
    try {
      window.sessionStorage.setItem("geo-monitoring-rounds-demo-v1", JSON.stringify({ rounds: demoRounds, generatedKeys: generatedRoundKeys }));
    } catch { /* The demo still works when browser storage is unavailable. */ }
  }, [demoRounds, generatedRoundKeys, snapshot?.source]);

  const load = useCallback(async (selectedProject?: string) => {
    const requestId = ++snapshotRequestId.current;
    setLoading(true);
    setError("");
    try {
      const data = await workbenchClient.snapshot(selectedProject);
      if (requestId === snapshotRequestId.current) setSnapshot(data);
    } catch (cause) {
      if (requestId === snapshotRequestId.current) setError(cause instanceof Error ? cause.message : "加载失败");
    } finally {
      if (requestId === snapshotRequestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    const requestId = ++snapshotRequestId.current;
    workbenchClient.snapshot().then((data) => {
      if (active && requestId === snapshotRequestId.current) {
        setSnapshot(data);
        if (data.source === "live" && data.projects[0]) setProjectId(data.projects[0].id);
      }
    }).catch((cause) => {
      if (active && requestId === snapshotRequestId.current) setError(cause instanceof Error ? cause.message : "加载失败");
    }).finally(() => {
      if (active && requestId === snapshotRequestId.current) setLoading(false);
    });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  function navigate(next: Section) {
    setSection(next);
    setSearch("");
    setStatusFilter("all");
    setMobileNav(false);
  }

  function chooseProject(value: string) {
    setProjectId(value);
    setLeadModal(false);
    if (snapshot?.source === "live") void load(value);
  }

  const filteredProjects = useMemo(() => snapshot?.projects.filter((project) => (projectId === "all" || project.id === projectId) && `${project.name} ${project.code} ${project.owner}`.toLowerCase().includes(search.toLowerCase())) ?? [], [snapshot, projectId, search]);
  const filteredTasks = useMemo(() => snapshot?.tasks.filter((task) => (projectId === "all" || task.projectId === projectId) && (statusFilter === "all" || task.status === statusFilter) && `${task.id} ${task.question} ${task.engine}`.toLowerCase().includes(search.toLowerCase())) ?? [], [snapshot, projectId, search, statusFilter]);
  const filteredLeads = useMemo(() => snapshot?.leads.filter((lead) => (projectId === "all" || lead.projectId === projectId) && (statusFilter === "all" || lead.status === statusFilter) && `${lead.contactName} ${lead.interest} ${lead.source}`.toLowerCase().includes(search.toLowerCase())) ?? [], [snapshot, projectId, search, statusFilter]);
  const filteredReviews = useMemo(() => snapshot?.reviews.filter((review) => (projectId === "all" || review.projectId === projectId) && (statusFilter === "all" || review.status === statusFilter) && `${review.title} ${review.author}`.toLowerCase().includes(search.toLowerCase())) ?? [], [snapshot, projectId, search, statusFilter]);

  async function submitLead(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!snapshot) return;
    const targetProject = projectId === "all" ? snapshot.projects[0]?.id : projectId;
    if (!targetProject) { setToast("请先选择项目"); return; }
    setSaving(true);
    try {
      const lead = await workbenchClient.createLead({ ...leadForm, projectId: targetProject });
      setSnapshot((current) => current ? { ...current, leads: [lead, ...current.leads] } : current);
      setLeadModal(false);
      setLeadForm({ contactName: "", phone: "", interest: "", source: "官网表单" });
      setToast(snapshot.source === "mock" ? "已添加到演示列表，未写入正式数据" : "线索已保存");
    } catch (cause) {
      setToast(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function reviewItem(item: ReviewItem, status: "已通过" | "已驳回") {
    try {
      const updated = await workbenchClient.review(item.id, status);
      setSnapshot((current) => current ? { ...current, reviews: current.reviews.map((review) => review.id === item.id ? updated : review) } : current);
      setToast(status === "已通过" ? "演示审核已通过，未写入正式数据" : "演示审核已驳回，未写入正式数据");
    } catch (cause) {
      setToast(cause instanceof Error ? cause.message : "操作失败");
    }
  }

  function exportLeads() {
    const rows = [["编号", "联系人", "电话", "意向", "来源", "状态"], ...filteredLeads.map((lead) => [lead.id, lead.contactName, lead.phone, lead.interest, lead.source, lead.status])];
    const csv = "\uFEFF" + rows.map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "geo-leads-demo.csv";
    link.click();
    URL.revokeObjectURL(url);
    setToast("已导出当前列表（演示数据）");
  }

  async function logout() {
    await workbenchClient.logout();
    router.replace("/login");
    router.refresh();
  }

  const pendingReviews = snapshot?.reviews.filter((item) => item.status === "待审核").length ?? 0;
  const currentProject = projectId === "all" ? "全部项目" : snapshot?.projects.find((project) => project.id === projectId)?.name ?? "全部项目";
  const info = sectionInfo[section];

  return <div className="app-shell">
    {mobileNav && <button className="mobile-scrim" aria-label="关闭菜单" onClick={() => setMobileNav(false)} />}
    <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
      <div className="sidebar-brand"><span className="brand-mark">G</span><span className="sidebar-brand-text">GEO<span className="brand-dot">.</span><small>WORKSPACE</small></span></div>
      <div className="sidebar-context"><span className="context-icon"><Icon name="spark" size={18}/></span><div><strong>品牌运营中心</strong><small>INTERNAL CONSOLE</small></div><Icon name="chevronDown" size={15}/></div>
      <nav aria-label="工作台导航">
        <p className="nav-caption">工作空间</p>
        {navigation.filter((item) => item.group === "workspace").map((item) => <button key={item.id} className={`nav-item ${section === item.id ? "active" : ""}`} onClick={() => navigate(item.id)}><Icon name={item.icon} size={19}/><span>{item.label}</span>{item.id === "reviews" && pendingReviews > 0 && <em>{pendingReviews}</em>}{item.id === "leads" && snapshot?.leadAccess === "forbidden" && <small className="nav-permission">无权限</small>}</button>)}
        <p className="nav-caption nav-caption-system">系统与规范</p>
        {navigation.filter((item) => item.group === "system").map((item) => <button key={item.id} className={`nav-item ${section === item.id ? "active" : ""}`} onClick={() => navigate(item.id)}><Icon name={item.icon} size={19}/><span>{item.label}</span></button>)}
      </nav>
      <div className="sidebar-bottom"><div className="sidebar-help"><span><Icon name="info" size={18}/></span><strong>前端 B · {snapshot?.source === "live" ? "接口联调" : "演示模式"}</strong><p>{snapshot?.source === "live" ? "数据来自后端，权限仍由后端接口校验。" : "数据仅用于页面与交互开发，正式权限由后端接口提供。"}</p></div><button className="sidebar-profile" onClick={logout}><span className="avatar">GE</span><span><strong>{snapshot?.source === "live" ? snapshot.userName ?? "当前账号" : "演示账号"}</strong><small>{snapshot?.source === "live" ? "后端认证会话" : "前端演示会话"}</small></span><Icon name="logout" size={17}/></button></div>
    </aside>

    <div className="app-main"><header className="topbar"><button className="mobile-menu" aria-label="打开菜单" onClick={() => setMobileNav(true)}><Icon name="menu"/></button><div className="topbar-location"><span className="topbar-product">GEO 品牌工作台</span><span className="topbar-divider">/</span><strong>{info.title}</strong></div><div className="topbar-right"><span className="environment-pill"><i/> {snapshot ? (snapshot.source === "live" ? "真实接口" : "演示环境") : "加载中"}</span><button className="top-icon-button" aria-label="查看待审核" onClick={() => navigate("reviews")}><Icon name="bell" size={20}/>{pendingReviews > 0 && <i/>}</button><span className="topbar-user"><span className="avatar small">GE</span><strong>{snapshot?.source === "live" ? "当前账号" : "演示账号"}</strong><Icon name="chevronDown" size={15}/></span></div></header>
      <main className="content-area"><div className="content-inner">
        <div className="demo-banner"><Icon name="info" size={17}/><span>{snapshot ? (snapshot.source === "live" ? "已连接后端。项目权限来自当前账号；未接通的业务不会显示演示成功。" : "前端演示模式：页面数据为模拟内容，登录和操作不代表正式权限。") : "正在确认数据来源…"}</span></div>
        <Header title={info.title} subtitle={info.subtitle} action={<><div className="project-select-wrap"><Icon name="folder" size={17}/><select value={projectId} aria-label="选择项目" onChange={(event) => chooseProject(event.target.value)}>{snapshot?.source !== "live" && <option value="all">全部项目</option>}{snapshot?.projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select><Icon name="chevronDown" size={15}/></div>{section === "leads" && snapshot?.leadAccess === "allowed" && (snapshot.source === "mock" || snapshot.permissions?.includes("lead.write")) && !loading && <Button icon="plus" onClick={() => setLeadModal(true)}>新增线索</Button>}{section === "monitoring" && <Button variant="secondary" icon="refresh" onClick={() => void load(projectId)}>刷新任务</Button>}</>}/>
        {error && <div className="load-error" role="alert"><Icon name="info" size={18}/>{error}<Button variant="secondary" onClick={() => void load(projectId)}>重试</Button></div>}
        {loading && !snapshot ? <div className="loading-panel">正在加载工作台…</div> : snapshot && <>
          {section === "overview" && <Overview snapshot={snapshot} projectName={(id) => projectName(snapshot, id)} onNavigate={navigate} onTask={setTaskDetail} />}
          {section === "projects" && <Projects snapshot={snapshot} projects={filteredProjects} search={search} onSearch={setSearch} />}
          {section === "monitoring" && <><MonitoringRounds key={projectId} mode={snapshot.source} projectId={projectId} projects={snapshot.projects} rounds={demoRounds} setRounds={setDemoRounds} generatedKeys={generatedRoundKeys} setGeneratedKeys={setGeneratedRoundKeys} canExecute={snapshot.source === "mock" || !!snapshot.permissions?.includes("monitoring.execute")} onNotice={setToast} onGenerated={() => void load(projectId)}/><Monitoring snapshot={snapshot} tasks={filteredTasks} search={search} status={statusFilter} onSearch={setSearch} onStatus={setStatusFilter} onTask={setTaskDetail} /></>}
          {section === "diagnostics" && <DiagnosticsWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes("monitoring.read")} />}
          {section === "questions" && <QuestionsWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes("question.read")} canWrite={snapshot.source === "mock" || !!snapshot.permissions?.includes("question.write")} onNotice={setToast}/>}
          {section === "samples" && <SamplesWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes("monitoring.read")} canReview={snapshot.source === "mock" || !!snapshot.permissions?.includes("evidence.review")} canReadChannels={snapshot.source === "mock" || !!snapshot.permissions?.includes("channel.read")} canDownloadEvidence={snapshot.source === "mock" || !!snapshot.permissions?.includes("evidence.read")} onNotice={setToast}/>}
          {section === "publishing" && <PublishingWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes("publish.read")} canExecute={snapshot.source === "mock" || !!snapshot.permissions?.includes("publish.execute")} onNotice={setToast}/>}
          {section === "channels" && <ChannelsWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes("channel.read")} canWrite={snapshot.source === "mock" || !!snapshot.permissions?.includes("channel.write")} onNotice={setToast}/>}
          {section === "statistics" && <StatisticsWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes("stats.read")} canExport={snapshot.source === "mock" || !!snapshot.permissions?.includes("export.data")} onNotice={setToast}/>}
          {section === "reviews" && (snapshot.source === "live" ? <ContentWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={!!snapshot.permissions?.includes("content.read")} canWrite={!!snapshot.permissions?.includes("content.write")} canReview={!!snapshot.permissions?.includes("content.review")} onNotice={setToast}/> : <Reviews snapshot={snapshot} reviews={filteredReviews} search={search} status={statusFilter} onSearch={setSearch} onStatus={setStatusFilter} onReview={reviewItem} />)}
          {section === "leads" && <Leads snapshot={snapshot} leads={filteredLeads} search={search} status={statusFilter} onSearch={setSearch} onStatus={setStatusFilter} onExport={exportLeads} />}
          {section === "faq" && <FaqWorkspace key={`faq-${projectId}`} mode={snapshot.source} projectId={projectId} projects={snapshot.projects} onNotice={setToast} />}
          {section === "materials" && <MaterialsWorkspace key={`materials-${projectId}`} mode={snapshot.source} projectId={projectId} projects={snapshot.projects} onNotice={setToast} />}
          {section === "activity" && <ActivityView snapshot={snapshot} />}
          {section === "engines" && <EnginesWorkspace mode={snapshot.source} canManage={snapshot.isSystemAdmin === true} canVerify={snapshot.isSystemAdmin === true || snapshot.permissions?.includes("engine.verify") === true} onNotice={setToast}/>}
          {section === "components" && <ComponentsView mode={snapshot.source} onToast={setToast} />}
        </>}
        <footer className="page-footer"><span>GEO SYSTEM · FRONTEND B</span><span>当前视图：{currentProject}　·　2026</span></footer>
      </div></main>
    </div>

    {toast && <div className="toast" role="status"><Icon name="check" size={17}/>{toast}</div>}
    {leadModal && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setLeadModal(false); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="lead-modal-title"><div className="modal-header"><div><p className="eyebrow">NEW LEAD</p><h2 id="lead-modal-title">新增线索</h2></div><button className="icon-button" aria-label="关闭" onClick={() => setLeadModal(false)}><Icon name="close" size={19}/></button></div><p className="modal-description">填写咨询信息，提交后会出现在当前列表中。</p><form onSubmit={submitLead}><div className="form-grid"><TextInput label="联系人 *" required value={leadForm.contactName} onChange={(event) => setLeadForm({ ...leadForm, contactName: event.target.value })} placeholder="例如：张女士"/><TextInput label="联系电话" value={leadForm.phone} onChange={(event) => setLeadForm({ ...leadForm, phone: event.target.value })} placeholder="请输入联系电话"/><TextInput label="意向课程" value={leadForm.interest} onChange={(event) => setLeadForm({ ...leadForm, interest: event.target.value })} placeholder="例如：少儿英语"/><SelectInput label="线索来源" value={leadForm.source} onChange={(event) => setLeadForm({ ...leadForm, source: event.target.value })}><option>官网表单</option><option>公众号</option><option>自然搜索</option><option>活动页面</option><option>其他</option></SelectInput></div><div className="modal-actions"><Button type="button" variant="secondary" onClick={() => setLeadModal(false)}>取消</Button><Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存线索"}</Button></div></form></div></div>}
    {taskDetail && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setTaskDetail(null); }}><div className="modal task-modal" role="dialog" aria-modal="true" aria-labelledby="task-modal-title"><div className="modal-header"><div><p className="eyebrow">MONITORING TASK</p><h2 id="task-modal-title">任务详情</h2></div><button className="icon-button" aria-label="关闭" onClick={() => setTaskDetail(null)}><Icon name="close" size={19}/></button></div><div className="task-details"><span>任务编号</span><strong>{taskDetail.id}</strong><span>监测问题</span><strong>{taskDetail.question}</strong><span>AI 引擎</span><strong>{taskDetail.engine}</strong><span>执行状态</span><Badge tone={statusTone(taskDetail.status)} dot>{taskDetail.status}</Badge><span>完成进度</span><strong>{taskDetail.progress}%</strong></div><div className="modal-actions"><Button variant="secondary" onClick={() => setTaskDetail(null)}>关闭</Button></div></div></div>}
  </div>;
}

function Overview({ snapshot, projectName: nameOf, onNavigate, onTask }: { snapshot: WorkbenchSnapshot; projectName: (id: string) => string; onNavigate: (section: Section) => void; onTask: (task: MonitoringTask) => void }) {
  const demo = snapshot.source === "mock";
  const metrics = [
    { label: "在管项目", value: snapshot.projects.length.toString(), unit: "个", change: "+2", icon: "layers" as IconName, tone: "blue" },
    { label: demo ? "本周监测任务" : "监测任务", value: demo ? "48" : snapshot.tasks.length.toString(), unit: "项", change: "+12.8%", icon: "pulse" as IconName, tone: "cyan" },
    { label: "待处理审核", value: snapshot.reviews.filter((review) => review.status === "待审核").length.toString(), unit: "项", change: "需关注", icon: "check" as IconName, tone: "amber" },
    { label: "当前可见线索", value: snapshot.leadAccess === "allowed" ? snapshot.leads.length.toString() : "—", unit: snapshot.leadAccess === "allowed" ? "条" : "", change: "+18.6%", icon: "users" as IconName, tone: "violet" },
  ];
  return <><div className="welcome-strip"><div><span className="eyebrow">WORKSPACE OVERVIEW</span><h2>欢迎来到 GEO 工作台 <span>✳</span></h2><p>{demo ? `当前有 ${snapshot.reviews.filter((review) => review.status === "待审核").length} 项演示审核内容等待处理。` : "项目数据、监测任务和统计指标已接入后端。"}</p></div><div className="welcome-symbol"><span>G</span><i/></div></div>
    <div className="metrics-grid">{metrics.map((metric) => <Panel key={metric.label} className="metric-card"><div className="metric-top"><span>{metric.label}</span><span className={`metric-icon metric-${metric.tone}`}><Icon name={metric.icon} size={20}/></span></div><div className="metric-main"><strong>{metric.value}</strong><small>{metric.unit}</small></div><div className="metric-foot">{demo ? <><span className={metric.change === "需关注" ? "metric-attention" : "metric-growth"}>{metric.change !== "需关注" && <Icon name="arrowUp" size={12}/>} {metric.change}</span><span>较上周</span></> : <span>来自后端接口</span>}</div></Panel>)}</div>
    <div className="insights-grid"><Panel className="chart-panel"><div className="panel-heading"><div><h3>品牌提及趋势</h3><p>过去 12 周的监测表现</p></div><span className="soft-pill">近 12 周 <Icon name="chevronDown" size={14}/></span></div><div className="chart-summary"><strong>{demo ? "76.8%" : snapshot.brandMentionRate === null || snapshot.brandMentionRate === undefined ? "—" : `${(snapshot.brandMentionRate * 100).toFixed(1)}%`}</strong><Badge tone="green">{demo ? "↑ 8.2%" : snapshot.trend.length ? "有效样本" : "暂无样本"}</Badge></div><TrendChart values={snapshot.trend}/></Panel><Panel className="engine-panel"><div className="panel-heading"><div><h3>引擎覆盖分布</h3><p>不同 AI 引擎的任务占比</p></div><Icon name="more" size={19}/></div>{snapshot.engines.length ? <><div className="engine-donut" aria-label="引擎任务占比"><div><strong>{snapshot.engines.length}</strong><span>个引擎</span></div></div><div className="engine-legend">{snapshot.engines.map((engine) => <div key={engine.name}><span><i style={{ backgroundColor: engine.color }}/>{engine.name}</span><strong>{engine.share}%</strong></div>)}</div></> : <div className="engine-empty">当前项目暂无任务分布</div>}</Panel></div>
    <div className="lower-grid"><Panel className="tasks-panel"><div className="panel-heading"><div><h3>近期监测任务</h3><p>需要持续跟进的任务进度</p></div><button className="text-link" onClick={() => onNavigate("monitoring")}>查看全部 <Icon name="arrowRight" size={15}/></button></div><div className="table-scroll"><table><thead><tr><th>任务 / 问题</th><th>项目</th><th>引擎</th><th>状态</th><th>进度</th><th></th></tr></thead><tbody>{snapshot.tasks.slice(0, 4).map((task) => <tr key={task.id}><td><strong className="table-title">{task.question}</strong><small className="table-sub">{task.id}</small></td><td>{nameOf(task.projectId)}</td><td>{task.engine}</td><td><Badge tone={statusTone(task.status)} dot>{task.status}</Badge></td><td><div className="progress-inline"><span><i style={{ width: `${task.progress}%` }}/></span>{task.progress}%</div></td><td><button className="icon-button" aria-label={`查看 ${task.id}`} onClick={() => onTask(task)}><Icon name="chevronRight" size={17}/></button></td></tr>)}</tbody></table>{!snapshot.tasks.length && <EmptyTable message="当前项目暂无监测任务"/>}</div></Panel><Panel className="activity-panel"><div className="panel-heading"><div><h3>最近动态</h3><p>团队协作与系统操作</p></div><button className="icon-button" aria-label="查看日志" onClick={() => onNavigate("activity")}><Icon name="chevronRight" size={17}/></button></div><div className="activity-list">{snapshot.activities.map((activity) => <div className="activity-row" key={activity.id}><span className={`activity-dot dot-${activity.tone}`}/><div><p><strong>{activity.actor}</strong> {activity.action}</p><span>{activity.target}</span><small>{activity.time}</small></div></div>)}{!snapshot.activities.length && <EmptyTable message={snapshot.permissions?.includes("audit.read") ? "当前项目暂无操作记录" : "当前账号无审计查看权限"}/>}</div></Panel></div>
  </>;
}

function TableToolbar({ search, onSearch, status, onStatus, statuses, extra }: { search: string; onSearch: (value: string) => void; status?: string; onStatus?: (value: string) => void; statuses?: string[]; extra?: React.ReactNode }) {
  return <div className="table-toolbar"><div className="toolbar-left"><div className="search-field"><Icon name="search" size={18}/><input aria-label="搜索列表" placeholder="搜索名称、编号或关键词" value={search} onChange={(event) => onSearch(event.target.value)}/></div>{statuses && onStatus && <div className="filter-select"><Icon name="filter" size={16}/><select aria-label="筛选状态" value={status} onChange={(event) => onStatus(event.target.value)}><option value="all">全部状态</option>{statuses.map((item) => <option key={item}>{item}</option>)}</select><Icon name="chevronDown" size={14}/></div>}</div>{extra && <div className="toolbar-extra">{extra}</div>}</div>;
}

function Projects({ snapshot, projects, search, onSearch }: { snapshot: WorkbenchSnapshot; projects: WorkbenchSnapshot["projects"]; search: string; onSearch: (value: string) => void }) {
  return <Panel className="list-panel"><div className="panel-heading list-heading"><div><h3>全部项目 <span className="count-chip">{projects.length}</span></h3><p>项目数据按当前账号的授权范围展示</p></div><Badge tone="blue">项目视图</Badge></div><TableToolbar search={search} onSearch={onSearch}/><div className="table-scroll"><table><thead><tr><th>项目名称</th><th>项目编号</th><th>负责人</th><th>渠道数</th><th>监测任务</th><th>状态</th><th>最近更新</th></tr></thead><tbody>{projects.map((project) => <tr key={project.id}><td><span className="project-cell"><span className="project-mini-icon"><Icon name="layers" size={18}/></span><strong>{project.name}</strong></span></td><td><code>{project.code}</code></td><td>{project.owner}</td><td>{snapshot.source === "mock" ? project.channels : "—"}</td><td>{snapshot.source === "mock" ? project.tasks : "—"}</td><td><Badge tone={statusTone(project.status)} dot>{project.status}</Badge></td><td>{project.updatedAt}</td></tr>)}</tbody></table>{!projects.length && <EmptyTable message="没有匹配的项目"/>}</div><div className="table-footer">显示 {projects.length} 个项目 <span>当前账号可访问的项目</span></div></Panel>;
}

function Monitoring({ snapshot, tasks, search, status, onSearch, onStatus, onTask }: { snapshot: WorkbenchSnapshot; tasks: MonitoringTask[]; search: string; status: string; onSearch: (value: string) => void; onStatus: (value: string) => void; onTask: (task: MonitoringTask) => void }) {
  return <><div className="section-stat-row"><div><Icon name="pulse" size={20}/><span>任务总数</span><strong>{tasks.length}</strong></div><div><Icon name="clock" size={20}/><span>待执行</span><strong>{tasks.filter((task) => task.status === "待执行").length}</strong></div><div><Icon name="check" size={20}/><span>已完成</span><strong>{tasks.filter((task) => task.status === "已完成").length}</strong></div></div><Panel className="list-panel"><div className="panel-heading list-heading"><div><h3>监测任务列表</h3><p>按问题、引擎和执行状态查看任务</p></div><Badge tone="slate">只读视图</Badge></div><TableToolbar search={search} onSearch={onSearch} status={status} onStatus={onStatus} statuses={["待执行", "进行中", "需复核", "已完成", "失败"]}/><div className="table-scroll"><table><thead><tr><th>任务编号</th><th>监测问题</th><th>项目</th><th>AI 引擎</th><th>状态</th><th>完成进度</th><th>更新时间</th><th></th></tr></thead><tbody>{tasks.map((task) => <tr key={task.id}><td><code>{task.id}</code></td><td><strong className="table-title">{task.question}</strong></td><td>{projectName(snapshot, task.projectId)}</td><td>{task.engine}</td><td><Badge tone={statusTone(task.status)} dot>{task.status}</Badge></td><td><div className="progress-inline"><span><i style={{ width: `${task.progress}%` }}/></span>{task.progress}%</div></td><td>{task.updatedAt}</td><td><button className="icon-button" aria-label={`查看 ${task.id}`} onClick={() => onTask(task)}><Icon name="eye" size={17}/></button></td></tr>)}</tbody></table>{!tasks.length && <EmptyTable message={snapshot.source === "live" ? "当前项目暂无可访问的监测任务" : "没有匹配的任务"}/>}</div><div className="table-footer">显示 {tasks.length} 条任务 <span>任务执行由后端服务负责</span></div></Panel></>;
}

function Reviews({ snapshot, reviews, search, status, onSearch, onStatus, onReview }: { snapshot: WorkbenchSnapshot; reviews: ReviewItem[]; search: string; status: string; onSearch: (value: string) => void; onStatus: (value: string) => void; onReview: (item: ReviewItem, status: "已通过" | "已驳回") => void }) {
  return <Panel className="list-panel"><div className="panel-heading list-heading"><div><h3>审核队列 <span className="count-chip amber">{reviews.filter((item) => item.status === "待审核").length} 待处理</span></h3><p>内容版本与证据复核统一进入审核队列</p></div><Badge tone="amber">等待审核</Badge></div><TableToolbar search={search} onSearch={onSearch} status={status} onStatus={onStatus} statuses={["待审核", "已通过", "已驳回"]}/><div className="review-list">{reviews.map((review) => <article className="review-card" key={review.id}><span className="review-symbol"><Icon name={review.type === "监测证据" ? "eye" : "layers"} size={20}/></span><div className="review-body"><div className="review-title-row"><h4>{review.title}</h4><Badge tone={statusTone(review.status)} dot>{review.status}</Badge></div><p>{review.type} <span>·</span> {projectName(snapshot, review.projectId)}</p><div className="review-meta"><span><Icon name="user" size={14}/>{review.author} 提交</span><span><Icon name="clock" size={14}/>{review.submittedAt}</span><code>{review.id}</code></div></div>{review.status === "待审核" && <div className="review-actions"><Button variant="secondary" disabled={snapshot.source !== "mock"} onClick={() => onReview(review, "已驳回")}>驳回</Button><Button disabled={snapshot.source !== "mock"} onClick={() => onReview(review, "已通过")}>通过审核</Button></div>}</article>)}{!reviews.length && <EmptyTable message={snapshot.source === "live" ? "审核接口尚待联调" : "没有匹配的审核项"}/>}</div><div className="table-footer">显示 {reviews.length} 条审核记录 <span>{snapshot.source === "mock" ? "操作仅影响当前演示环境" : "真实审核操作待接口联调"}</span></div></Panel>;
}

function Leads({ snapshot, leads, search, status, onSearch, onStatus, onExport }: { snapshot: WorkbenchSnapshot; leads: Lead[]; search: string; status: string; onSearch: (value: string) => void; onStatus: (value: string) => void; onExport: () => void }) {
  if (snapshot.leadAccess !== "allowed") return <Panel className="lead-permission-panel"><Icon name="lock" size={25}/><h3>{snapshot.leadAccess === "forbidden" ? "当前账号无权查看线索" : "请先选择项目"}</h3><p>{snapshot.leadAccess === "forbidden" ? "后端拒绝了这个项目的线索请求。项目、监测等其他页面仍可使用；如需线索权限，请联系项目管理员。" : "选择项目后再查看该项目的线索。"}</p></Panel>;
  return <Panel className="list-panel"><div className="panel-heading list-heading"><div><h3>咨询线索 <span className="count-chip">{leads.length}</span></h3><p>统一管理来自不同渠道的咨询信息</p></div><Badge tone="blue">线索视图</Badge></div><TableToolbar search={search} onSearch={onSearch} status={status} onStatus={onStatus} statuses={["待跟进", "跟进中", "已转化"]} extra={<Button variant="secondary" icon="download" disabled={snapshot.source !== "mock"} onClick={onExport}>导出当前列表</Button>}/><div className="table-scroll"><table><thead><tr><th>线索编号</th><th>联系人</th><th>联系电话</th><th>意向内容</th><th>来源</th><th>所属项目</th><th>状态</th><th>创建时间</th></tr></thead><tbody>{leads.map((lead) => <tr key={lead.id}><td><code>{lead.id}</code></td><td><strong className="table-title">{lead.contactName}</strong></td><td>{lead.phone}</td><td>{lead.interest}</td><td>{lead.source}</td><td>{projectName(snapshot, lead.projectId)}</td><td><Badge tone={statusTone(lead.status)} dot>{lead.status}</Badge></td><td>{lead.createdAt}</td></tr>)}</tbody></table>{!leads.length && <EmptyTable message="没有匹配的线索"/>}</div><div className="table-footer">显示 {leads.length} 条线索 <span>正式导出需由后端授权并记录审计</span></div></Panel>;
}

function ActivityView({ snapshot }: { snapshot: WorkbenchSnapshot }) {
  return <Panel className="list-panel"><div className="panel-heading list-heading"><div><h3>最近 20 条操作记录</h3><p>关键动作的时间线与责任人</p></div><Badge tone="slate">只读视图</Badge></div><div className="timeline">{snapshot.activities.map((activity) => <div className="timeline-item" key={activity.id}><span className={`timeline-marker dot-${activity.tone}`}/><div><div className="timeline-line"><strong>{activity.actor}</strong><span>{activity.action}</span><small>{activity.time}</small></div><p>{activity.target}</p></div></div>)}{!snapshot.activities.length && <EmptyTable message={snapshot.permissions?.includes("audit.read") ? "当前项目暂无操作记录" : "当前账号无审计查看权限"}/>}</div></Panel>;
}

function ComponentsView({ mode, onToast }: { mode: WorkbenchSnapshot["source"]; onToast: (message: string) => void }) {
  return <div className="component-grid"><Panel className="component-panel"><div className="panel-heading"><div><h3>按钮 Buttons</h3><p>主要操作、次要操作与轻量动作</p></div></div><div className="component-row"><Button onClick={() => onToast("主要操作")}>主要按钮</Button><Button variant="secondary" onClick={() => onToast("次要操作")}>次要按钮</Button><Button variant="quiet" onClick={() => onToast("轻量操作")}>文字按钮</Button><Button variant="danger" onClick={() => onToast("危险操作演示")}>危险操作</Button></div></Panel><Panel className="component-panel"><div className="panel-heading"><div><h3>状态标签 Status</h3><p>保持信息层级一致，颜色只承担辅助提示</p></div></div><div className="component-row"><Badge tone="blue" dot>进行中</Badge><Badge tone="green" dot>已完成</Badge><Badge tone="amber" dot>待审核</Badge><Badge tone="red" dot>已驳回</Badge><Badge tone="slate" dot>待执行</Badge></div></Panel><Panel className="component-panel wide"><div className="panel-heading"><div><h3>表单控件 Form</h3><p>面向高频录入场景，优先保证清晰可读</p></div></div><div className="form-grid component-form"><TextInput label="文本输入" placeholder="请输入内容"/><SelectInput label="下拉选择" defaultValue="广州基地 GEO 项目"><option>广州基地 GEO 项目</option><option>北辰教育品牌</option></SelectInput></div><div className="component-row"><label className="checkbox-sample"><input type="checkbox" defaultChecked/> 已选择</label><label className="checkbox-sample"><input type="checkbox"/> 未选择</label></div></Panel><Panel className="component-panel wide"><div className="panel-heading"><div><h3>文件操作 Upload</h3><p>上传接口尚未交付，组件仅验证文件选择交互</p></div></div><label className="upload-zone"><input type="file" onChange={(event) => onToast(event.target.files?.[0] ? `已选择：${event.target.files[0].name}（未上传）` : "未选择文件")}/><Icon name="upload" size={24}/><strong>点击选择文件</strong><span>{mode === "mock" ? "演示模式不会将文件上传到服务器" : "上传接口尚未交付，所选文件不会上传"}</span></label></Panel></div>;
}
