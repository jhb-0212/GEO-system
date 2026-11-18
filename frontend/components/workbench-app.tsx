"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Badge, Button, Icon, Panel, SelectInput, TextInput, type IconName } from "./ui";
import { FaqWorkspace, MaterialsWorkspace } from "./knowledge-workbench";
import { initialDemoRounds, MonitoringRounds } from "./monitoring-rounds";
import { ChannelsWorkspace } from "./channels-workspace";
import { EnginesWorkspace } from "./engines-workspace";
import { StatisticsWorkspace } from "./statistics-workspace";
import { MonthlyReportWorkspace } from "./monthly-report-workspace";
import { LeadFunnelWorkspace } from "./lead-funnel-workspace";
import { QuestionsWorkspace } from "./questions-workspace";
import { SamplesWorkspace } from "./samples-workspace";
import { PublishingWorkspace } from "./publishing-workspace";
import { DiagnosticsWorkspace } from "./diagnostics-workspace";
import { ContentWorkspace } from "./content-workspace";
import { CompetitorsWorkspace } from "./competitors-workspace";
import { BrandWorkspace } from "./brand-workspace";
import { MetricsWorkspace } from "./metrics-workspace";
import { MembersWorkspace } from "./members-workspace";
import { PlansWorkspace } from "./plans-workspace";
import { QuotesWorkspace } from "./quotes-workspace";
import { BudgetWorkspace } from "./budget-workspace";
import { workbenchClient } from "@/lib/workbench/client";
import { readAccountHistory, recordAccount } from "@/lib/workbench/account-history";
import { getSectionInfo, navigation, type NavItemConfig } from "@/lib/workbench/navigation";
import { PERMISSION, describeRole, groupPermissions } from "@/lib/workbench/permissions";
import { canSeeNavItem } from "@/lib/workbench/visibility";
import { useWorkbenchActions } from "@/lib/workbench/use-workbench-actions";
import type { ContentVersionRecord, Lead, MonitoringRound, MonitoringTask, ReviewItem, Section, Tone, WorkbenchSnapshot } from "@/lib/workbench/types";

type NavItem = NavItemConfig;

/** 演示模式的内容审核数据：把审核项适配成与真实接口一致的版本记录，复用同一个面板。 */
function toDemoVersion(item: ReviewItem): ContentVersionRecord {
  return {
    version_id: item.id,
    item_id: item.id,
    title: item.title,
    version_no: 1,
    status: item.status === "已通过" ? "approved" : item.status === "已驳回" ? "rejected" : "pending_review",
    kind: item.type,
    channel_id: null,
    author_name: item.author,
    submitted_at: item.submittedAt,
  };
}

function statusTone(status: string): Tone {
  if (["运行中", "已完成", "已通过", "已转化"].includes(status)) return "green";
  if (["进行中", "跟进中"].includes(status)) return "blue";
  if (["需复核", "待审核", "待跟进", "筹备中", "待核实"].includes(status)) return "amber";
  if (["已驳回", "失败", "已流失"].includes(status)) return "red";
  return "slate";
}

function projectName(snapshot: WorkbenchSnapshot, id: string) {
  return snapshot.projects.find((project) => project.id === id)?.name ?? "未知项目";
}

/**
 * 引擎占比圆环按真实 share 分段。
 * 之前圆环是写死的 CSS 渐变，图例百分比变了圆环纹丝不动，属于「图和数据对不上」。
 * share 合计不一定等于 100（后端按任务数算占比后取整），这里按合计归一化。
 */
function engineGradient(engines: WorkbenchSnapshot["engines"]): string | undefined {
  const total = engines.reduce((sum, engine) => sum + Math.max(0, engine.share), 0);
  if (!total) return undefined;
  let cursor = 0;
  const stops = engines.map((engine) => {
    const start = cursor;
    cursor += (Math.max(0, engine.share) / total) * 100;
    return `${engine.color} ${start.toFixed(2)}% ${cursor.toFixed(2)}%`;
  });
  return `conic-gradient(${stops.join(", ")})`;
}

function TrendChart({ values, weeks }: { values: (number | null)[]; weeks: number }) {
  if (!values.some((value) => value !== null)) return <div className="chart-empty">暂无有效样本</div>;
  const segments: string[] = [];
  let active: string[] = [];
  values.forEach((value, index) => {
    if (value === null) { if (active.length) segments.push(active.join(" ")); active = []; }
    else active.push(`${28 + index * (517 / Math.max(1, values.length - 1))},${160 - value * 1.28}`);
  });
  if (active.length) segments.push(active.join(" "));
  return <div className="trend-chart"><div className="chart-y"><span>100%</span><span>75%</span><span>50%</span><span>25%</span></div><svg viewBox="0 0 585 180" role="img" aria-label={`近 ${weeks} 周品牌提及率变化`}><path d="M28 31H558M28 75H558M28 119H558M28 163H558" stroke="#e9edf3" strokeDasharray="4 5"/>{segments.map((points, index) => <polyline key={index} points={points} fill="none" stroke="#3e70ef" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>)}</svg><div className="chart-x"><span>{weeks} 周前</span><span>{Math.round(weeks / 2)} 周前</span><span>本周</span></div></div>;
}

function Header({ title, subtitle, action, onHome }: { title: string; subtitle: string; action?: React.ReactNode; onHome: () => void }) {
  return <div className="section-header"><div><div className="breadcrumb"><button type="button" className="breadcrumb-home" onClick={onHome}>GEO 工作台</button> <Icon name="chevronRight" size={14} /> {title}</div><h1>{title}</h1><p>{subtitle}</p></div>{action && <div className="section-actions">{action}</div>}</div>;
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

const sectionIds = new Set<Section>(navigation.map((item) => item.id));

function readSectionFromLocation(): Section {
  if (typeof window === "undefined") return "overview";
  const value = new URLSearchParams(window.location.search).get("section");
  return value && sectionIds.has(value as Section) ? value as Section : "overview";
}

function readProjectFromLocation(): string {
  if (typeof window === "undefined") return "all";
  const value = new URLSearchParams(window.location.search).get("project_id");
  return value || "all";
}

function writeLocation(section: Section, projectId: string, mode: "push" | "replace" = "push") {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.set("section", section);
  const tabParams = ["sample_tab", "publish_tab", "question_tab", "stats_tab", "content_tab"];
  const keepTab = section === "samples" ? "sample_tab" : section === "publishing" ? "publish_tab" : section === "questions" ? "question_tab" : section === "statistics" ? "stats_tab" : section === "reviews" ? "content_tab" : "";
  tabParams.forEach((param) => { if (param !== keepTab) url.searchParams.delete(param); });
  if (projectId && projectId !== "all") url.searchParams.set("project_id", projectId);
  else url.searchParams.delete("project_id");
  if (url.href === window.location.href) return;
  window.history[mode === "push" ? "pushState" : "replaceState"]({ section, projectId }, "", url);
}

export function WorkbenchApp() {
  const router = useRouter();
  const [requestedSection, setRequestedSection] = useState<Section>("overview");
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
  const [accountMenu, setAccountMenu] = useState(false);
  const [accountHistory, setAccountHistory] = useState(readAccountHistory);
  const [passwordModal, setPasswordModal] = useState(false);
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [passwordForm, setPasswordForm] = useState({ current: "", next: "", confirm: "" });
  const [leadForm, setLeadForm] = useState({ contactName: "", phone: "", interest: "", source: "官网表单", reportedAiProduct: "", isValid: true });
  const [demoRounds, setDemoRounds] = useState<MonitoringRound[]>(() => readDemoRounds().rounds);
  const [generatedRoundKeys, setGeneratedRoundKeys] = useState<string[]>(() => readDemoRounds().generatedKeys);
  const snapshotRequestId = useRef(0);
  const accountRef = useRef<HTMLDivElement>(null);
  const projectSelectRef = useRef<HTMLDetailsElement>(null);

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
    const initialSection = readSectionFromLocation();
    const initialProject = readProjectFromLocation();
    workbenchClient.snapshot(initialProject === "all" ? undefined : initialProject).then((data) => {
      if (active && requestId === snapshotRequestId.current) {
        setRequestedSection(initialSection);
        setSnapshot(data);
        if (data.source === "live") {
          const fallback = data.activeProjectId ?? data.projects[0]?.id;
          const available = data.projects.some((project) => project.id === initialProject) ? initialProject : fallback;
          if (available) {
            setProjectId(available);
            writeLocation(initialSection, available, "replace");
          }
        }
      }
    }).catch((cause) => {
      if (active && requestId === snapshotRequestId.current) setError(cause instanceof Error ? cause.message : "加载失败");
    }).finally(() => {
      if (active && requestId === snapshotRequestId.current) setLoading(false);
    });
    return () => { active = false; };
  }, []);

  const actions = useWorkbenchActions({ snapshot, projectId, setSnapshot, notify: setToast, reload: load });

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (snapshot?.source !== "live") return;
    const login = snapshot.username;
    if (login) recordAccount(login);
  }, [snapshot?.source, snapshot?.username]);

  function refreshAccountHistory() {
    setAccountHistory(readAccountHistory());
  }

  function navigate(next: Section) {
    setRequestedSection(next);
    setSearch("");
    setStatusFilter("all");
    setMobileNav(false);
    writeLocation(next, projectId);
  }

  function chooseProject(value: string) {
    setProjectId(value);
    setLeadModal(false);
    writeLocation(readSectionFromLocation(), value);
    if (snapshot?.source === "live") void load(value);
  }

  useEffect(() => {
    function handlePopState() {
      const nextSection = readSectionFromLocation();
      const nextProject = readProjectFromLocation();
      setRequestedSection(nextSection);
      setSearch("");
      setStatusFilter("all");
      setMobileNav(false);
      setProjectId(nextProject);
      if (snapshot?.source === "live") void load(nextProject === "all" ? undefined : nextProject);
    }
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [load, snapshot?.source]);

  useEffect(() => {
    if (!snapshot) return;
    const visible = navigation.filter((item) => canSeeNavItem(item, snapshot));
    if (!visible.some((item) => item.id === requestedSection)) {
      writeLocation("overview", projectId, "replace");
    }
  }, [snapshot, requestedSection, projectId]);

  useEffect(() => {
    if (!accountMenu) return;
    function handlePointerDown(event: PointerEvent) {
      if (accountRef.current && !accountRef.current.contains(event.target as Node)) setAccountMenu(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setAccountMenu(false);
    }
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [accountMenu]);

  useEffect(() => {
    function closeOnOutside(event: PointerEvent) {
      if (projectSelectRef.current?.open && !projectSelectRef.current.contains(event.target as Node)) {
        projectSelectRef.current.removeAttribute("open");
      }
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") projectSelectRef.current?.removeAttribute("open");
    }
    document.addEventListener("pointerdown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  const filteredProjects = useMemo(() => snapshot?.projects.filter((project) => (projectId === "all" || project.id === projectId) && `${project.name} ${project.code} ${project.owner}`.toLowerCase().includes(search.toLowerCase())) ?? [], [snapshot, projectId, search]);
  const filteredTasks = useMemo(() => snapshot?.tasks.filter((task) => (projectId === "all" || task.projectId === projectId) && (statusFilter === "all" || task.status === statusFilter) && `${task.id} ${task.question} ${task.engine}`.toLowerCase().includes(search.toLowerCase())) ?? [], [snapshot, projectId, search, statusFilter]);
  const filteredLeads = useMemo(() => snapshot?.leads.filter((lead) => (projectId === "all" || lead.projectId === projectId) && (statusFilter === "all" || lead.status === statusFilter) && `${lead.contactName} ${lead.interest} ${lead.source}`.toLowerCase().includes(search.toLowerCase())) ?? [], [snapshot, projectId, search, statusFilter]);

  async function submitLead(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    const saved = await actions.submitLead(leadForm);
    if (saved) {
      setLeadModal(false);
      setLeadForm({ contactName: "", phone: "", interest: "", source: "官网表单", reportedAiProduct: "", isValid: true });
    }
    setSaving(false);
  }

  async function logout() {
    await workbenchClient.logout();
    router.replace("/login");
    router.refresh();
  }

  async function addAccount() {
    setAccountMenu(false);
    await workbenchClient.logout();
    router.replace("/login");
    router.refresh();
  }

  async function switchToAccount(name: string) {
    setAccountMenu(false);
    await workbenchClient.logout();
    router.replace(`/login?username=${encodeURIComponent(name)}`);
    router.refresh();
  }

  function openProfile() {
    setAccountMenu(false);
    navigate("profile");
  }

  function openPasswordModal() {
    setAccountMenu(false);
    setPasswordError("");
    setPasswordForm({ current: "", next: "", confirm: "" });
    setPasswordModal(true);
  }

  async function submitPassword(event: React.FormEvent) {
    event.preventDefault();
    setPasswordError("");
    if (passwordForm.next.length < 8) {
      setPasswordError("新密码至少 8 位");
      return;
    }
    if (passwordForm.next !== passwordForm.confirm) {
      setPasswordError("两次输入的新密码不一致");
      return;
    }
    if (passwordForm.current === passwordForm.next) {
      setPasswordError("新密码不能与原密码相同");
      return;
    }
    setPasswordSaving(true);
    try {
      await workbenchClient.changePassword(passwordForm.current, passwordForm.next);
      setPasswordModal(false);
      setPasswordForm({ current: "", next: "", confirm: "" });
      // 后端改密会让旧令牌失效，BFF 已把新令牌写回会话 cookie，当前浏览器不需要重新登录
      setToast("密码已修改，其他设备上的登录状态已失效");
    } catch (cause) {
      setPasswordError(cause instanceof Error ? cause.message : "修改失败，请稍后再试");
    } finally {
      setPasswordSaving(false);
    }
  }

  const pendingReviews = snapshot?.reviews.filter((item) => item.status === "待审核").length ?? 0;
  const currentLogin = snapshot?.source === "live" ? (snapshot.username ?? snapshot.userName ?? "当前账号") : "demo";
  const otherAccounts = accountHistory.filter((item) => item.username !== currentLogin);
  const currentProject = projectId === "all" ? "全部项目" : snapshot?.projects.find((project) => project.id === projectId)?.name ?? "全部项目";
  // 真实接口模式按能力码收菜单：public 全量；project 看当前项目；global 看全局能力；system 只给系统管理员。
  const canSee = (item: NavItem) => canSeeNavItem(item, snapshot);
  const canEditContent = snapshot?.source !== "live" || snapshot.permissions?.includes(PERMISSION.CONTENT_WRITE) === true;
  const navLabel = (item: (typeof navigation)[number]) => {
    if ((item.id === "faq" || item.id === "materials") && snapshot?.source === "live" && !canEditContent) {
      return item.id === "faq" ? "FAQ 查看" : "素材查看";
    }
    return item.label;
  };
  const visibleNavigation = navigation.filter(canSee);
  // URL 里可能带着无权限的旧 section；渲染时回落到概览，不把隐藏页面重新画出来。
  const section = visibleNavigation.some((item) => item.id === requestedSection) ? requestedSection : "overview";
  const info = getSectionInfo(section);
  const displayInfo = (section === "faq" || section === "materials") && snapshot?.source === "live" && !canEditContent
    ? { title: section === "faq" ? "FAQ 查看" : "素材查看", subtitle: section === "faq" ? "查看常见问题与答案（只读）" : "查看品牌素材（只读）" }
    : info;

  return <div className="app-shell">
    {mobileNav && <button className="mobile-scrim" aria-label="关闭菜单" onClick={() => setMobileNav(false)} />}
    <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
      <div className="sidebar-brand"><span className="brand-mark">G</span><span className="sidebar-brand-text">GEO<span className="brand-dot">.</span><small>WORKSPACE</small></span></div>
      <button type="button" className="sidebar-context" onClick={() => navigate("overview")}><span className="context-icon"><Icon name="spark" size={18}/></span><div><strong>品牌运营中心</strong><small>INTERNAL CONSOLE</small></div></button>
      <nav aria-label="工作台导航">
        <p className="nav-caption">工作空间</p>
        {visibleNavigation.filter((item) => item.group === "workspace").map((item) => <button key={item.id} className={`nav-item ${section === item.id ? "active" : ""}`} onClick={() => navigate(item.id)}><Icon name={item.icon} size={19}/><span>{navLabel(item)}</span>{item.id === "reviews" && pendingReviews > 0 && <em>{pendingReviews}</em>}</button>)}
        <p className="nav-caption nav-caption-system">系统与规范</p>
        {visibleNavigation.filter((item) => item.group === "system").map((item) => <button key={item.id} className={`nav-item ${section === item.id ? "active" : ""}`} onClick={() => navigate(item.id)}><Icon name={item.icon} size={19}/><span>{navLabel(item)}</span></button>)}
      </nav>
      <div className="sidebar-bottom"><div className="sidebar-help"><span><Icon name="info" size={18}/></span><strong>前端 B · {snapshot?.source === "live" ? "接口联调" : "演示模式"}</strong><p>{snapshot?.source === "live" ? "数据来自后端，权限仍由后端接口校验。" : "数据仅用于页面与交互开发，正式权限由后端接口提供。"}</p></div><div className="sidebar-profile"><button type="button" className="sidebar-profile-main" onClick={openProfile}><span className="avatar">GE</span><span><strong>{snapshot?.source === "live" ? snapshot.userName ?? "当前账号" : "演示账号"}</strong><small>{snapshot?.source === "live" ? "后端认证会话" : "前端演示会话"}</small></span></button><button type="button" className="sidebar-profile-logout" aria-label="退出登录" onClick={(event) => { event.stopPropagation(); void logout(); }}><Icon name="logout" size={17}/></button></div></div>
    </aside>

    <div className="app-main"><header className="topbar"><button className="mobile-menu" aria-label="打开菜单" onClick={() => setMobileNav(true)}><Icon name="menu"/></button><div className="topbar-location"><span className="topbar-product">GEO 品牌工作台</span><span className="topbar-divider">/</span><strong>{displayInfo.title}</strong></div><div className="topbar-right"><span className="environment-pill"><i/> {snapshot ? (snapshot.source === "live" ? "真实接口" : "演示环境") : "加载中"}</span><button className="top-icon-button" aria-label="查看待审核" onClick={() => navigate("reviews")}><Icon name="bell" size={20}/>{pendingReviews > 0 && <i/>}</button><div className="topbar-account" ref={accountRef}><button type="button" className="topbar-user" aria-haspopup="menu" aria-expanded={accountMenu} onClick={() => { refreshAccountHistory(); setAccountMenu((open) => !open); }}><span className="avatar small">GE</span><strong>{snapshot?.source === "live" ? snapshot.userName ?? "当前账号" : "演示账号"}</strong><Icon name="chevronDown" size={15}/></button>{accountMenu && <div className="account-menu" role="menu"><p>当前登录：{currentLogin}</p><button type="button" role="menuitem" onClick={openProfile}>个人中心</button>{otherAccounts.length > 0 && <><p className="account-menu-group">其他账号</p>{otherAccounts.map((item) => <button key={item.username} type="button" role="menuitem" onClick={() => void switchToAccount(item.username)}>{item.username}</button>)}</>}<button type="button" role="menuitem" onClick={() => void addAccount()}>添加账号</button><button type="button" role="menuitem" onClick={openPasswordModal}>修改密码</button><button type="button" role="menuitem" onClick={() => void logout()}>退出登录</button></div>}</div></div></header>
      <main className="content-area"><div className="content-inner">
        <div className="demo-banner"><Icon name="info" size={17}/><span>{snapshot ? (snapshot.source === "live" ? "已连接后端。项目权限来自当前账号；未接通的业务不会显示演示成功。" : "前端演示模式：页面数据为模拟内容，登录和操作不代表正式权限。") : "正在确认数据来源…"}</span></div>
        <Header title={displayInfo.title} subtitle={displayInfo.subtitle} onHome={() => navigate("overview")} action={<><details className="project-select" ref={projectSelectRef}><summary className="project-select-wrap"><Icon name="folder" size={17}/><span>{snapshot ? (projectId === "all" ? "全部项目" : projectName(snapshot, projectId)) : "选择项目"}</span><Icon name="chevronDown" size={15}/></summary><div className="select-menu-list">{snapshot?.source !== "live" && <button type="button" className={projectId === "all" ? "selected" : ""} onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); chooseProject("all"); }}>全部项目</button>}{snapshot?.projects.map((project) => <button type="button" key={project.id} className={project.id === projectId ? "selected" : ""} onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); chooseProject(project.id); }}>{project.name}</button>)}</div></details>{section === "leads" && snapshot?.leadAccess === "allowed" && (snapshot.source === "mock" || snapshot.permissions?.includes(PERMISSION.LEAD_WRITE)) && !loading && <Button icon="plus" onClick={() => setLeadModal(true)}>新增线索</Button>}{section === "monitoring" && <Button variant="secondary" icon="refresh" onClick={() => void load(projectId)}>刷新任务</Button>}</>}/>
        {error && <div className="load-error" role="alert"><Icon name="info" size={18}/>{error}<Button variant="secondary" onClick={() => void load(projectId)}>重试</Button></div>}
        {loading && !snapshot ? <div className="loading-panel">正在加载工作台…</div> : snapshot && <>
          {section === "overview" && <Overview snapshot={snapshot} projectName={(id) => projectName(snapshot, id)} onNavigate={navigate} onTask={setTaskDetail} />}
          {section === "projects" && <Projects projects={filteredProjects} search={search} onSearch={setSearch} canConfirm={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.PROJECT_CONFIRM)} onConfirm={actions.confirmProject} />}
          {section === "monitoring" && <><details className="rounds-fold"><summary><span><Icon name="layers" size={17}/>监测轮次与批量生成</span><small>展开后可新建轮次、批量生成监测任务</small><Icon name="chevronDown" size={15}/></summary><MonitoringRounds key={projectId} mode={snapshot.source} projectId={projectId} projects={snapshot.projects} rounds={demoRounds} setRounds={setDemoRounds} generatedKeys={generatedRoundKeys} setGeneratedKeys={setGeneratedRoundKeys} canExecute={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.MONITORING_EXECUTE)} onNotice={setToast} onGenerated={() => void load(projectId)}/></details><Monitoring snapshot={snapshot} tasks={filteredTasks} search={search} status={statusFilter} onSearch={setSearch} onStatus={setStatusFilter} onTask={setTaskDetail} /></>}
          {section === "diagnostics" && <DiagnosticsWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.MONITORING_EXECUTE) || !!snapshot.permissions?.includes(PERMISSION.PROJECT_MEMBER_MANAGE)} isSystemAdmin={snapshot.source === "live" && snapshot.isSystemAdmin === true} />}
          {section === "questions" && <QuestionsWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.QUESTION_READ)} canWrite={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.QUESTION_WRITE)} onNotice={setToast}/>}
          {section === "samples" && <SamplesWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.MONITORING_READ)} canReview={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.EVIDENCE_REVIEW)} canReadChannels={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.CHANNEL_READ)} canDownloadEvidence={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.EVIDENCE_READ)} canCreate={snapshot.source === "live" && !!snapshot.permissions?.includes(PERMISSION.MONITORING_EXECUTE)} canUploadEvidence={snapshot.source === "live" && (!!snapshot.permissions?.includes(PERMISSION.MONITORING_EXECUTE) || !!snapshot.permissions?.includes(PERMISSION.EVIDENCE_REVIEW))} onNotice={setToast}/>}
          {section === "publishing" && <PublishingWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.PUBLISH_READ)} canExecute={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.PUBLISH_EXECUTE)} onNotice={setToast}/>}
          {section === "channels" && <ChannelsWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.CHANNEL_READ)} canWrite={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.CHANNEL_WRITE)} canExport={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.EXPORT_DATA)} onNotice={setToast}/>}
          {section === "statistics" && <StatisticsWorkspace key={projectId} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.STATS_READ)} canExport={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.EXPORT_DATA)} canCheckVisibility={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.MONITORING_EXECUTE)} onNotice={setToast}/>}
          {section === "monthly" && <MonthlyReportWorkspace key={`monthly-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.STATS_READ)} />}
          {section === "funnel" && <LeadFunnelWorkspace key={`funnel-${projectId}`} mode={snapshot.source} projectId={projectId} leadAccess={snapshot.leadAccess ?? "unavailable"} />}
          {section === "reviews" && <ContentWorkspace key={projectId} mode={snapshot.source} projectId={projectId} demoItems={snapshot.source === "mock" ? snapshot.reviews.map(toDemoVersion) : undefined} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.CONTENT_READ)} canWrite={snapshot.source === "live" && !!snapshot.permissions?.includes(PERMISSION.CONTENT_WRITE)} canReview={snapshot.source === "live" && !!snapshot.permissions?.includes(PERMISSION.CONTENT_REVIEW)} onNotice={setToast}/>}
          {section === "leads" && <Leads snapshot={snapshot} leads={filteredLeads} search={search} status={statusFilter} onSearch={setSearch} onStatus={setStatusFilter} onExport={actions.exportLeads} onUpdate={actions.updateLeadStatus} canExport={snapshot.source === "live" && !!snapshot.permissions?.includes(PERMISSION.EXPORT_DATA)} canWrite={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.LEAD_WRITE)} />}
          {section === "faq" && <FaqWorkspace key={`faq-${projectId}`} mode={snapshot.source} projectId={projectId} projects={snapshot.projects} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.CONTENT_READ)} canWrite={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.CONTENT_WRITE)} onNotice={setToast} />}
          {section === "materials" && <MaterialsWorkspace key={`materials-${projectId}`} mode={snapshot.source} projectId={projectId} projects={snapshot.projects} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.CONTENT_READ)} canWrite={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.CONTENT_WRITE)} onNotice={setToast} />}
          {section === "competitors" && <CompetitorsWorkspace key={`competitors-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.MONITORING_READ)} canWrite={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.COMPETITOR_WRITE)} onNotice={setToast} />}
          {section === "brand" && <BrandWorkspace key={`brand-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.MONITORING_READ)} canWrite={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.BRAND_MANAGE)} onNotice={setToast} />}
          {section === "metrics" && <MetricsWorkspace key={`metrics-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.STATS_READ)} canWrite={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.METRIC_MANAGE)} onNotice={setToast} />}
          {section === "members" && <MembersWorkspace key={`members-${projectId}`} mode={snapshot.source} projectId={projectId} canManage={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.PROJECT_MEMBER_MANAGE)} isSystemAdmin={snapshot.source === "live" && snapshot.isSystemAdmin === true} onNotice={setToast} />}
          {section === "plans" && <PlansWorkspace key={`plans-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.CONTENT_READ)} canWrite={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.CONTENT_WRITE)} onNotice={setToast} />}
          {section === "quotes" && <QuotesWorkspace key={`quotes-${projectId}`} mode={snapshot.source} projectId={projectId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.CONTENT_READ)} canWrite={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.CONTENT_WRITE)} canReview={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.CONTENT_REVIEW)} onNotice={setToast} />}
          {section === "budget" && <BudgetWorkspace key={`budget-${projectId}`} mode={snapshot.source} projectId={projectId} currentUserId={snapshot.currentUserId} canRead={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.BUDGET_READ)} canWrite={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.BUDGET_WRITE)} canApprove={snapshot.source === "mock" || !!snapshot.permissions?.includes(PERMISSION.BUDGET_APPROVE)} onNotice={setToast} />}
          {section === "activity" && <ActivityView key={snapshot.activeProjectId ?? "all"} snapshot={snapshot} />}
          {section === "engines" && <EnginesWorkspace mode={snapshot.source} canManage={snapshot.isSystemAdmin === true} canVerify={snapshot.isSystemAdmin === true || snapshot.globalPermissions?.includes(PERMISSION.ENGINE_VERIFY) === true} onNotice={setToast}/>}
          {section === "profile" && <ProfileView snapshot={snapshot} />}
        </>}
        <footer className="page-footer"><span>GEO SYSTEM · FRONTEND B</span><span>当前视图：{currentProject}　·　2026</span></footer>
      </div></main>
    </div>

    {toast && <div className="toast" role="status"><Icon name="check" size={17}/>{toast}</div>}
    {passwordModal && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !passwordSaving) setPasswordModal(false); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="password-modal-title"><div className="modal-header"><div><p className="eyebrow">ACCOUNT</p><h2 id="password-modal-title">修改密码</h2></div><button className="icon-button" aria-label="关闭" disabled={passwordSaving} onClick={() => setPasswordModal(false)}><Icon name="close" size={19}/></button></div><p className="modal-description">改密后其他设备上的登录会失效；当前浏览器会自动续用新会话，不用重新登录。</p><form onSubmit={submitPassword}><div className="form-grid"><TextInput label="原密码 *" type="password" autoComplete="current-password" required value={passwordForm.current} onChange={(event) => setPasswordForm({ ...passwordForm, current: event.target.value })} placeholder="请输入当前密码"/><TextInput label="新密码 *" type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={passwordForm.next} onChange={(event) => setPasswordForm({ ...passwordForm, next: event.target.value })} placeholder="至少 8 位"/><TextInput label="确认新密码 *" type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={passwordForm.confirm} onChange={(event) => setPasswordForm({ ...passwordForm, confirm: event.target.value })} placeholder="再次输入新密码"/></div>{passwordError && <p className="form-error" role="alert">{passwordError}</p>}<div className="modal-actions"><Button type="button" variant="secondary" disabled={passwordSaving} onClick={() => setPasswordModal(false)}>取消</Button><Button type="submit" disabled={passwordSaving}>{passwordSaving ? "提交中…" : "保存新密码"}</Button></div></form></div></div>}
    {leadModal && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setLeadModal(false); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="lead-modal-title"><div className="modal-header"><div><p className="eyebrow">NEW LEAD</p><h2 id="lead-modal-title">新增线索</h2></div><button className="icon-button" aria-label="关闭" onClick={() => setLeadModal(false)}><Icon name="close" size={19}/></button></div><p className="modal-description">填写咨询信息，提交后会出现在当前列表中。</p><form onSubmit={submitLead}><div className="form-grid"><TextInput label="联系人 *" required value={leadForm.contactName} onChange={(event) => setLeadForm({ ...leadForm, contactName: event.target.value })} placeholder="例如：张女士"/><TextInput label="联系电话" value={leadForm.phone} onChange={(event) => setLeadForm({ ...leadForm, phone: event.target.value })} placeholder="请输入联系电话"/><TextInput label="意向课程" value={leadForm.interest} onChange={(event) => setLeadForm({ ...leadForm, interest: event.target.value })} placeholder="例如：少儿英语"/><SelectInput label="线索来源" value={leadForm.source} onChange={(event) => setLeadForm({ ...leadForm, source: event.target.value })}><option>官网表单</option><option>公众号</option><option>自然搜索</option><option>活动页面</option><option>其他</option></SelectInput><TextInput label="自报 AI 产品" value={leadForm.reportedAiProduct} onChange={(event) => setLeadForm({ ...leadForm, reportedAiProduct: event.target.value })} placeholder="例如：豆包 / 元宝 / DeepSeek"/><SelectInput label="是否有效" value={leadForm.isValid ? "true" : "false"} onChange={(event) => setLeadForm({ ...leadForm, isValid: event.target.value === "true" })}><option value="true">有效线索</option><option value="false">无效 / 误留资</option></SelectInput></div><div className="modal-actions"><Button type="button" variant="secondary" onClick={() => setLeadModal(false)}>取消</Button><Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存线索"}</Button></div></form></div></div>}
    {taskDetail && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setTaskDetail(null); }}><div className="modal task-modal" role="dialog" aria-modal="true" aria-labelledby="task-modal-title"><div className="modal-header"><div><p className="eyebrow">MONITORING TASK</p><h2 id="task-modal-title">任务详情</h2></div><button className="icon-button" aria-label="关闭" onClick={() => setTaskDetail(null)}><Icon name="close" size={19}/></button></div><div className="task-details"><span>任务编号</span><strong>{taskDetail.id}</strong><span>监测问题</span><strong>{taskDetail.question}</strong><span>AI 引擎</span><strong>{taskDetail.engine}</strong><span>执行状态</span><Badge tone={statusTone(taskDetail.status)} dot>{taskDetail.status}</Badge></div><div className="modal-actions"><Button variant="secondary" onClick={() => setTaskDetail(null)}>关闭</Button></div></div></div>}
  </div>;
}

function Overview({ snapshot, projectName: nameOf, onNavigate, onTask }: { snapshot: WorkbenchSnapshot; projectName: (id: string) => string; onNavigate: (section: Section) => void; onTask: (task: MonitoringTask) => void }) {
  const demo = snapshot.source === "mock";
  const [weeks, setWeeks] = useState(12);
  const trendValues = snapshot.trend.slice(-weeks);
  const metrics = [
    { label: "在管项目", value: snapshot.projects.length.toString(), unit: "个", change: "+2", icon: "layers" as IconName, tone: "blue" },
    { label: demo ? "本周监测任务" : "监测任务", value: demo ? "48" : (snapshot.taskTotal ?? snapshot.tasks.length).toString(), unit: "项", change: "+12.8%", icon: "pulse" as IconName, tone: "cyan" },
    { label: "待处理审核", value: demo ? snapshot.reviews.filter((review) => review.status === "待审核").length.toString() : (snapshot.reviewTotal ?? snapshot.reviews.length).toString(), unit: "项", change: "需关注", icon: "check" as IconName, tone: "amber" },
    { label: "当前可见线索", value: snapshot.leadAccess === "allowed" ? snapshot.leads.length.toString() : "—", unit: snapshot.leadAccess === "allowed" ? "条" : "", change: "+18.6%", icon: "users" as IconName, tone: "violet" },
  ];
  return <><div className="welcome-strip"><div><span className="eyebrow">WORKSPACE OVERVIEW</span><h2>欢迎来到 GEO 工作台 <span>✳</span></h2><p>{demo ? `当前有 ${snapshot.reviews.filter((review) => review.status === "待审核").length} 项演示审核内容等待处理。` : "项目数据、监测任务和统计指标已接入后端。"}</p></div><div className="welcome-symbol"><span>G</span><i/></div></div>
    {snapshot.truncated && <p className="knowledge-footnote" role="status">数据量超过工作台单次加载上限：任务已加载 {snapshot.tasks.length} / 共 {snapshot.taskTotal ?? snapshot.tasks.length} 条，待审内容已加载 {snapshot.reviews.length} / 共 {snapshot.reviewTotal ?? snapshot.reviews.length} 条。上方计数按后端总数显示，明细请到对应页面分页查看。</p>}
    <div className="metrics-grid">{metrics.map((metric) => <Panel key={metric.label} className="metric-card"><div className="metric-top"><span>{metric.label}</span><span className={`metric-icon metric-${metric.tone}`}><Icon name={metric.icon} size={20}/></span></div><div className="metric-main"><strong>{metric.value}</strong><small>{metric.unit}</small></div><div className="metric-foot">{demo ? <><span className={metric.change === "需关注" ? "metric-attention" : "metric-growth"}>{metric.change !== "需关注" && <Icon name="arrowUp" size={12}/>} {metric.change}</span><span>较上周</span></> : <span>来自后端接口</span>}</div></Panel>)}</div>
    <div className="insights-grid"><Panel className="chart-panel"><div className="panel-heading"><div><h3>品牌提及趋势</h3><p>过去 {weeks} 周的监测表现</p></div><details className="range-select"><summary><span>近 {weeks} 周</span><Icon name="chevronDown" size={14}/></summary><div className="select-menu-list range-menu">{[12, 8, 4].map((value) => <button type="button" key={value} className={weeks === value ? "selected" : ""} onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); setWeeks(value); }}>近 {value} 周</button>)}</div></details></div><div className="chart-summary"><strong>{demo ? "76.8%" : snapshot.brandMentionRate === null || snapshot.brandMentionRate === undefined ? "—" : `${(snapshot.brandMentionRate * 100).toFixed(1)}%`}</strong><Badge tone="green">{demo ? "↑ 8.2%" : snapshot.trend.length ? "有效样本" : "暂无样本"}</Badge></div><TrendChart values={trendValues} weeks={Math.min(weeks, snapshot.trend.length || weeks)}/></Panel><Panel className="engine-panel"><div className="panel-heading"><div><h3>引擎覆盖分布</h3><p>不同 AI 引擎的任务占比</p></div><details className="more-menu"><summary aria-label="引擎分布更多操作"><Icon name="more" size={19}/></summary><div className="more-menu-list"><button type="button" onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); onNavigate("engines"); }}>查看引擎台账</button><button type="button" onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); onNavigate("statistics"); }}>查看统计看板</button><button type="button" onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); onNavigate("monitoring"); }}>查看监测任务</button></div></details></div>{snapshot.engines.length ? <><div className="engine-donut" aria-label="引擎任务占比" style={{ background: engineGradient(snapshot.engines) }}><div><strong>{snapshot.engines.length}</strong><span>个引擎</span></div></div><div className="engine-legend">{snapshot.engines.map((engine) => <div key={engine.name}><span><i style={{ backgroundColor: engine.color }}/>{engine.name}</span><strong>{engine.share}%</strong></div>)}</div></> : <div className="engine-empty">当前项目暂无任务分布</div>}</Panel></div>
    <div className="lower-grid"><Panel className="tasks-panel"><div className="panel-heading"><div><h3>近期监测任务</h3><p>需要持续跟进的任务进度</p></div><button className="text-link" onClick={() => onNavigate("monitoring")}>查看全部 <Icon name="arrowRight" size={15}/></button></div><div className="table-scroll"><table><thead><tr><th>任务 / 问题</th><th>项目</th><th>引擎</th><th>状态</th><th></th></tr></thead><tbody>{snapshot.tasks.slice(0, 3).map((task) => <tr key={task.id}><td><strong className="table-title">{task.question}</strong><small className="table-sub">{task.id}</small></td><td>{nameOf(task.projectId)}</td><td>{task.engine}</td><td><Badge tone={statusTone(task.status)} dot>{task.status}</Badge></td><td><button className="icon-button" aria-label={`查看 ${task.id}`} onClick={() => onTask(task)}><Icon name="chevronRight" size={17}/></button></td></tr>)}</tbody></table>{!snapshot.tasks.length && <EmptyTable message="当前项目暂无监测任务"/>}</div></Panel><Panel className="activity-panel"><div className="panel-heading"><div><h3>最近动态</h3><p>团队协作与系统操作</p></div><button className="text-link" onClick={() => onNavigate("activity")}>查看全部 <Icon name="arrowRight" size={15}/></button></div><div className="activity-list">{snapshot.activities.slice(0, 3).map((activity) => <div className="activity-row" key={activity.id}><span className={`activity-dot dot-${activity.tone}`}/><div><p><strong>{activity.actor}</strong> {activity.action}</p><span>{activity.target}</span><small>{activity.time}</small></div></div>)}{!snapshot.activities.length && <EmptyTable message={snapshot.permissions?.includes(PERMISSION.AUDIT_READ) ? "当前项目暂无操作记录" : "当前账号无审计查看权限"} />}</div></Panel></div>
  </>;
}

function TableToolbar({ search, onSearch, status, onStatus, statuses, extra }: { search: string; onSearch: (value: string) => void; status?: string; onStatus?: (value: string) => void; statuses?: string[]; extra?: React.ReactNode }) {
  return <div className="table-toolbar"><div className="toolbar-left"><div className="search-field"><Icon name="search" size={18}/><input aria-label="搜索列表" placeholder="搜索名称、编号或关键词" value={search} onChange={(event) => onSearch(event.target.value)}/></div>{statuses && onStatus && <div className="filter-select"><Icon name="filter" size={16}/><select aria-label="筛选状态" value={status} onChange={(event) => onStatus(event.target.value)}><option value="all">全部状态</option>{statuses.map((item) => <option key={item}>{item}</option>)}</select><Icon name="chevronDown" size={14}/></div>}</div>{extra && <div className="toolbar-extra">{extra}</div>}</div>;
}

function Projects({ projects, search, onSearch, canConfirm, onConfirm }: { projects: WorkbenchSnapshot["projects"]; search: string; onSearch: (value: string) => void; canConfirm: boolean; onConfirm: (project: WorkbenchSnapshot["projects"][number], priority: number) => void }) {
  const [priorities, setPriorities] = useState<Record<string, number>>({});
  return <Panel className="list-panel"><div className="panel-heading list-heading"><div><h3>全部项目 <span className="count-chip">{projects.length}</span></h3><p>项目数据按当前账号的授权范围展示；优先级由业务负责人确认</p></div><Badge tone="blue">项目视图</Badge></div><TableToolbar search={search} onSearch={onSearch}/><div className="table-scroll"><table><thead><tr><th>项目名称</th><th>项目编号</th><th>负责人</th><th>优先级</th><th>资料确认</th><th>渠道数</th><th>监测任务</th><th>状态</th><th>最近更新</th></tr></thead><tbody>{projects.map((project) => <tr key={project.id}><td><span className="project-cell"><span className="project-mini-icon"><Icon name="layers" size={18}/></span><strong>{project.name}</strong></span></td><td><code>{project.code}</code></td><td>{project.owner}</td><td>{canConfirm ? <select className="knowledge-filter" aria-label={`${project.name} 优先级`} value={priorities[project.id] ?? project.priority} onChange={(event) => setPriorities((current) => ({ ...current, [project.id]: Number(event.target.value) }))}>{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>P{value}</option>)}</select> : `P${project.priority}`}{canConfirm && priorities[project.id] !== undefined && priorities[project.id] !== project.priority && <Badge tone="amber">未保存</Badge>}</td><td>{project.businessConfirmedAt ? <Badge tone="green">已确认</Badge> : <Badge tone="amber">待确认</Badge>}{canConfirm && <Button variant="quiet" onClick={() => onConfirm(project, priorities[project.id] ?? project.priority)}>{priorities[project.id] !== undefined && priorities[project.id] !== project.priority ? "保存并确认" : project.businessConfirmedAt ? "重新确认" : "确认资料"}</Button>}</td><td>{project.channels}</td><td>{project.tasks}</td><td><Badge tone={statusTone(project.status)} dot>{project.status}</Badge></td><td>{project.updatedAt}</td></tr>)}</tbody></table>{!projects.length && <EmptyTable message="没有匹配的项目"/>}</div><div className="table-footer">显示 {projects.length} 个项目 <span>{canConfirm ? "优先级改完需点「保存并确认」才会落库" : "当前账号无确认权限"}</span></div></Panel>;
}

function Monitoring({ snapshot, tasks, search, status, onSearch, onStatus, onTask }: { snapshot: WorkbenchSnapshot; tasks: MonitoringTask[]; search: string; status: string; onSearch: (value: string) => void; onStatus: (value: string) => void; onTask: (task: MonitoringTask) => void }) {
  return <><div className="section-stat-row"><div><Icon name="pulse" size={20}/><span>任务总数</span><strong>{snapshot.taskTotal ?? tasks.length}</strong></div><div><Icon name="clock" size={20}/><span>待执行</span><strong>{tasks.filter((task) => task.status === "待执行").length}</strong></div><div><Icon name="check" size={20}/><span>已完成</span><strong>{tasks.filter((task) => task.status === "已完成").length}</strong></div></div><Panel className="list-panel"><div className="panel-heading list-heading"><div><h3>监测任务列表</h3><p>按问题、引擎和执行状态查看任务</p></div><Badge tone="slate">只读视图</Badge></div><TableToolbar search={search} onSearch={onSearch} status={status} onStatus={onStatus} statuses={["待执行", "进行中", "需复核", "已完成", "失败", "已取消", "待核实"]}/><div className="table-scroll monitor-table"><table><thead><tr><th>任务编号</th><th>监测问题</th><th>项目</th><th>AI 引擎</th><th>状态</th><th>更新时间</th><th></th></tr></thead><tbody>{tasks.map((task) => <tr key={task.id}><td><code>{task.id}</code></td><td><strong className="table-title">{task.question}</strong></td><td>{projectName(snapshot, task.projectId)}</td><td>{task.engine}</td><td><Badge tone={statusTone(task.status)} dot>{task.status}</Badge></td><td>{task.updatedAt}</td><td><button className="icon-button" aria-label={`查看 ${task.id}`} onClick={() => onTask(task)}><Icon name="eye" size={17}/></button></td></tr>)}</tbody></table>{!tasks.length && <EmptyTable message={snapshot.source === "live" ? "当前项目暂无可访问的监测任务" : "没有匹配的任务"}/>}</div><div className="table-footer"><span>共 {snapshot.taskTotal ?? tasks.length} 条任务{snapshot.truncated ? ` · 本页已加载 ${tasks.length} 条，上方「待执行 / 已完成」仅统计已加载部分` : " · 表格内滚动查看"}</span></div></Panel></>;
}

function Leads({ snapshot, leads, search, status, onSearch, onStatus, onExport, onUpdate, canExport, canWrite }: { snapshot: WorkbenchSnapshot; leads: Lead[]; search: string; status: string; onSearch: (value: string) => void; onStatus: (value: string) => void; onExport: () => void; onUpdate: (lead: Lead, status: Lead["status"]) => void; canExport: boolean; canWrite: boolean }) {
  if (snapshot.leadAccess !== "allowed") return <Panel className="lead-permission-panel"><Icon name="lock" size={25}/><h3>{snapshot.leadAccess === "forbidden" ? "当前账号无权查看线索" : "请先选择项目"}</h3><p>{snapshot.leadAccess === "forbidden" ? "后端拒绝了这个项目的线索请求。项目、监测等其他页面仍可使用；如需线索权限，请联系项目管理员。" : "选择项目后再查看该项目的线索。"}</p></Panel>;
  return <Panel className="list-panel"><div className="panel-heading list-heading"><div><h3>咨询线索 <span className="count-chip">{leads.length}</span></h3><p>统一管理来自不同渠道的咨询信息</p></div><Badge tone="blue">线索视图</Badge></div><TableToolbar search={search} onSearch={onSearch} status={status} onStatus={onStatus} statuses={["待跟进", "跟进中", "已转化"]} extra={<Button variant="secondary" icon="download" disabled={!canExport} onClick={onExport}>导出当前列表</Button>}/><div className="table-scroll"><table><thead><tr><th>线索编号</th><th>联系人</th><th>联系电话</th><th>意向内容</th><th>自报 AI 产品</th><th>有效性</th><th>来源</th><th>所属项目</th><th>负责人</th><th>状态</th><th>备注</th><th>创建时间</th></tr></thead><tbody>{leads.map((lead) => <tr key={lead.id}><td><code>{lead.id}</code></td><td><strong className="table-title">{lead.contactName}</strong></td><td>{lead.phone}</td><td>{lead.interest}</td><td>{lead.reportedAiProduct || "—"}</td><td>{lead.isValid === false ? <Badge tone="red">无效</Badge> : <Badge tone="green">有效</Badge>}</td><td>{lead.source}</td><td>{projectName(snapshot, lead.projectId)}</td><td>{lead.ownerName ?? "—"}</td><td><select className="knowledge-filter" aria-label="更新线索状态" value={lead.status} disabled={snapshot.source !== "live" || !canWrite} onChange={(event) => onUpdate(lead, event.target.value as Lead["status"])}><option value="待跟进">待跟进</option><option value="跟进中">跟进中</option><option value="已转化">已转化</option><option value="已流失">已流失</option></select></td><td>{lead.note ?? "—"}</td><td>{lead.createdAt}</td></tr>)}</tbody></table>{!leads.length && <EmptyTable message="没有匹配的线索"/>}</div><div className="table-footer">显示 {leads.length} 条线索 <span>正式导出需由后端授权并记录审计</span></div></Panel>;
}

function ActivityView({ snapshot }: { snapshot: WorkbenchSnapshot }) {
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
        actor: row.actor_name ?? "未知操作者",
        action: row.action,
        target: `${row.target_type ?? "资源"}${row.target_id ? ` · ${row.target_id.slice(0, 8)}` : ""}`,
        time: row.created_at,
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
  return <Panel className="list-panel"><div className="panel-heading list-heading"><div><h3>最近 {visible.length} 条操作记录</h3><p>关键动作的时间线与责任人</p></div><div className="activity-heading-actions"><Badge tone="slate">已加载 {items.length} / 共 {total} 条</Badge>{!expanded && items.length > 6 && <Button variant="secondary" onClick={() => setExpanded(true)}>展开已加载的 {items.length} 条</Button>}{expanded && hasMore && <Button variant="secondary" disabled={loading} onClick={() => void loadMore()}>{loading ? "加载中…" : "加载更多"}</Button>}{expanded && !hasMore && items.length > 6 && <Button variant="secondary" onClick={() => setExpanded(false)}>收起</Button>}</div></div>{error && <p className="knowledge-footnote">{error}</p>}<div className="timeline">{visible.map((activity) => <div className="timeline-item" key={activity.id}><span className={`timeline-marker dot-${activity.tone}`}/><div><div className="timeline-line"><strong>{activity.actor}</strong><span>{activity.action}</span><small>{activity.time}</small></div><p>{activity.target}</p></div></div>)}{!items.length && <EmptyTable message={snapshot.permissions?.includes(PERMISSION.AUDIT_READ) ? "当前项目暂无操作记录" : "当前账号无审计查看权限"}/>}</div></Panel>;
}

function ProfileView({ snapshot }: { snapshot: WorkbenchSnapshot }) {
  const live = snapshot.source === "live";
  const name = live ? snapshot.userName ?? "当前账号" : "演示账号";
  const loginName = live ? (snapshot.username ?? "—") : "demo";
  const role = snapshot.isSystemAdmin ? "系统管理员" : "项目成员";
  const sessionLabel = live ? "后端认证会话" : "前端演示会话";
  const permissions = snapshot.permissions ?? [];
  const groups = groupPermissions(permissions);
  const projects = snapshot.projects;
  const initial = name.trim().charAt(0).toUpperCase() || "U";
  return <div className="profile-grid">
    <Panel className="profile-hero" collapsible={false}>
      <div className="profile-hero-main">
        <span className="avatar profile-avatar">{initial}</span>
        <div className="profile-main">
          <div className="profile-title-row"><strong>{name}</strong><Badge tone={snapshot.isSystemAdmin ? "blue" : "slate"} dot>{role}</Badge></div>
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
                    <code className="profile-perm-code">{item.code}</code>
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
            <div className="profile-project-main"><strong>{project.name}</strong><small>{project.code}</small></div>
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
