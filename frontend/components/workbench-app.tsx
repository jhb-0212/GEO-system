"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Badge, Button, DetailModal, Icon, SelectInput, TextInput } from "./ui";
import { SECTION_VIEWS, type SectionContext } from "./workbench/section-registry";
import { displayUserName, projectName, statusTone } from "./workbench/shared";
import { initialDemoRounds } from "./monitoring-rounds";
import { workbenchClient } from "@/lib/workbench/client";
import { readAccountHistory, recordAccount } from "@/lib/workbench/account-history";
import { ADVANCED_NAV_GROUPS, ADVANCED_SECTIONS, CORE_NAV_ORDER, getSectionInfo, navigation, type NavItemConfig } from "@/lib/workbench/navigation";
import { PERMISSION } from "@/lib/workbench/permissions";
import { canSeeNavItem } from "@/lib/workbench/visibility";
import { useWorkbenchActions } from "@/lib/workbench/use-workbench-actions";
import type { MonitoringRound, MonitoringTask, Section, WorkbenchSnapshot } from "@/lib/workbench/types";

type NavItem = NavItemConfig;

/** 账号显示只保留业务名称，隐藏 seed、API 适配器等实现备注。 */
function Header({ title, subtitle, action, onHome }: { title: string; subtitle: string; action?: React.ReactNode; onHome: () => void }) {
  return <div className="section-header"><div><div className="breadcrumb"><button type="button" className="breadcrumb-home" onClick={onHome}>GEO 工作台</button> <Icon name="chevronRight" size={14} /> {title}</div><h1>{title}</h1><p>{subtitle}</p></div>{action && <div className="section-actions">{action}</div>}</div>;
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

function UsageGuide({ onClose, onGo }: { onClose: () => void; onGo: (section: Section) => void }) {
  return <DetailModal eyebrow="新手引导" title="GEO 工作台使用指南" subtitle="第一次使用，按这 5 步走；日常操作基本都在左侧导航。" onClose={onClose}>
    <div className="guide-steps">
      <div className="guide-step"><span>01</span><div><strong>先确认项目和数据</strong><p>看右上角项目是否选对；「工作概览」会显示监测任务、待审核和最近动态。数据为空时，先建监测任务或补渠道。</p></div></div>
      <div className="guide-step"><span>02</span><div><strong>建监测任务</strong><p>进入「监测任务」，展开「监测轮次与批量生成」：新建轮次，再按题目 × AI 平台生成任务。任务生成不等于已经拿到回答，跑完后到「样本与引用」看结果。</p></div></div>
      <div className="guide-step"><span>03</span><div><strong>审核内容</strong><p>进入「内容审核」处理待审稿。通过后的内容才能进入发布流程；需要改稿时直接在审核页操作，不要绕过审核去发布。</p></div></div>
      <div className="guide-step"><span>04</span><div><strong>发布并回填链接</strong><p>进入「内容发布」→「新建发布」，按提示执行；发布完成后把真实文章链接粘回去。院校类渠道、招生页和招聘页，要先在「页面审批」登记并通过，才能保存发布结果。</p></div></div>
      <div className="guide-step"><span>05</span><div><strong>看效果</strong><p>到「统计看板」看品牌提及率、引用率和渠道表现；「月度报告」看阶段汇总。数字异常时，再到「配置与管理 → 问题排查」查失败样本。</p></div></div>
    </div>
    <div className="guide-glossary">
      <h3>几个常用词</h3>
      <dl>
        <div><dt>监测任务</dt><dd>让某个 AI 平台回答一道题，并记录它的回答和引用。</dd></div>
        <div><dt>样本</dt><dd>一次实际拿到的 AI 回答；不是任务数量，只有真正返回的回答才算样本。</dd></div>
        <div><dt>引用</dt><dd>AI 回答里提到的网页链接，用来判断它参考了谁。</dd></div>
        <div><dt>发布结果</dt><dd>内容发布完成后回填的真实链接记录，用来核对发布是否落地。</dd></div>
        <div><dt>页面审批</dt><dd>针对具体页面链接的发布确认；院校、招生、招聘页面必须先通过。</dd></div>
      </dl>
    </div>
    <div className="guide-note"><Icon name="info" size={16}/><p>左侧只放日常高频功能；配置、排障、成员管理、指标说明等低频功能收在「配置与管理」里，已按“监测与项目、内容与事实、预算与统计、账号与协作”分好组。</p></div>
    <div className="modal-actions guide-actions"><Button onClick={() => onGo("monitoring")}>去监测任务</Button><Button variant="secondary" onClick={() => onGo("reviews")}>去内容审核</Button><Button variant="secondary" onClick={() => onGo("publishing")}>去内容发布</Button><Button variant="secondary" onClick={() => onGo("statistics")}>去统计看板</Button><Button variant="secondary" onClick={onClose}>知道了</Button></div>
  </DetailModal>;
}

function AdvancedNavDialog({ groups, active, onGo, onClose }: {
  groups: { label: string; items: NavItemConfig[] }[];
  active: Section;
  onGo: (section: Section) => void;
  onClose: () => void;
}) {
  return <DetailModal eyebrow="低频功能" title="配置与管理" subtitle="按用途分成 4 组，点任意一项进入；日常高频操作仍放在左侧主导航。" onClose={onClose}>
    <div className="advanced-nav-grid">
      {groups.map((group) => <section className="advanced-nav-group" key={group.label}>
        <div className="advanced-nav-group-head"><h3>{group.label}</h3><span>{group.items.length} 项</span></div>
        <div className="advanced-nav-list">{group.items.map((item) => <button key={item.id} type="button" className={`advanced-nav-item ${active === item.id ? "active" : ""}`} onClick={() => onGo(item.id)}>
          <span className="advanced-nav-icon"><Icon name={item.icon} size={17}/></span>
          <span className="advanced-nav-copy"><strong>{item.label}</strong><small>{item.subtitle}</small></span>
          <Icon name="chevronRight" size={15}/>
        </button>)}</div>
      </section>)}
    </div>
  </DetailModal>;
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
  const [taskCancelConfirm, setTaskCancelConfirm] = useState(false);
  const [taskCancelling, setTaskCancelling] = useState(false);
  const [taskCancelError, setTaskCancelError] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const [saving, setSaving] = useState(false);
  const [accountMenu, setAccountMenu] = useState(false);
  const [helpModal, setHelpModal] = useState(false);
  const [accountHistory, setAccountHistory] = useState(readAccountHistory);
  const [passwordModal, setPasswordModal] = useState(false);
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [passwordForm, setPasswordForm] = useState({ current: "", next: "", confirm: "" });
  const [leadForm, setLeadForm] = useState({ contactName: "", phone: "", interest: "", source: "官网表单", reportedAiProduct: "", isValid: true });
  const [demoRounds, setDemoRounds] = useState<MonitoringRound[]>(() => readDemoRounds().rounds);
  const [advancedNavModal, setAdvancedNavModal] = useState(false);
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

  function goFromGuide(section: Section) {
    setHelpModal(false);
    navigate(section);
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
  const filteredTasks = useMemo(() => snapshot?.tasks.filter((task) => (projectId === "all" || task.projectId === projectId) && (statusFilter === "all" || task.status === statusFilter) && `${task.serialNo ?? ""} ${task.question} ${task.engine}`.toLowerCase().includes(search.toLowerCase())) ?? [], [snapshot, projectId, search, statusFilter]);
  const filteredLeads = useMemo(() => snapshot?.leads.filter((lead) => (projectId === "all" || lead.projectId === projectId) && (statusFilter === "all" || lead.status === statusFilter) && `${lead.serialNo ?? ""} ${lead.contactName} ${lead.interest} ${lead.source}`.toLowerCase().includes(search.toLowerCase())) ?? [], [snapshot, projectId, search, statusFilter]);
  const canCancelTask = snapshot?.source === "live" && (!!snapshot.permissions?.includes(PERMISSION.MONITORING_CANCEL) || !!snapshot.permissions?.includes(PERMISSION.MONITORING_EXECUTE));

  function openTask(task: MonitoringTask) {
    setTaskDetail(task);
    setTaskCancelConfirm(false);
    setTaskCancelError("");
  }

  function openManualTask(task: MonitoringTask) {
    const url = new URL(window.location.href);
    url.searchParams.set("section", "samples");
    url.searchParams.set("project_id", task.projectId);
    url.searchParams.set("task_id", task.id);
    window.history.pushState({ section: "samples", projectId: task.projectId }, "", url);
    setRequestedSection("samples");
    setProjectId(task.projectId);
    setSearch("");
    setStatusFilter("all");
    setMobileNav(false);
  }

  function closeTaskDetail() {
    setTaskDetail(null);
    setTaskCancelConfirm(false);
    setTaskCancelError("");
  }

  async function cancelTask() {
    if (!taskDetail || taskCancelling) return;
    const target = taskDetail;
    setTaskCancelling(true);
    setTaskCancelError("");
    try {
      await workbenchClient.cancelMonitoringTask(target.projectId, target.id);
      closeTaskDetail();
      setToast(`已作废任务 #${target.serialNo || "—"}；执行记录仍保留，可在状态筛选中查看`);
      await load(projectId);
    } catch (cause) {
      setTaskCancelError(cause instanceof Error ? cause.message : "作废任务失败");
    } finally { setTaskCancelling(false); }
  }

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
  const canReviewContent = snapshot?.source !== "live" || snapshot.permissions?.includes(PERMISSION.CONTENT_REVIEW) === true;
  const navLabel = (item: (typeof navigation)[number]) => {
    if ((item.id === "faq" || item.id === "materials") && snapshot?.source === "live" && !canEditContent) {
      if (item.id === "faq" && canReviewContent) return "FAQ 审核";
      return item.id === "faq" ? "FAQ 查看" : item.label;
    }
    return item.label;
  };
  const visibleNavigation = navigation.filter(canSee);
  const coreNavigation = visibleNavigation
    .filter((item) => !ADVANCED_SECTIONS.includes(item.id))
    .sort((a, b) => {
      const ai = CORE_NAV_ORDER.indexOf(a.id);
      const bi = CORE_NAV_ORDER.indexOf(b.id);
      return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi);
    });
  const advancedNavigation = visibleNavigation.filter((item) => ADVANCED_SECTIONS.includes(item.id));
  const advancedGroups = ADVANCED_NAV_GROUPS
    .map((group) => ({ ...group, items: advancedNavigation.filter((item) => group.sections.includes(item.id)).map((item) => ({ ...item, label: navLabel(item) })) }))
    .filter((group) => group.items.length > 0);
  // URL 里可能带着无权限的旧 section；渲染时回落到概览，不把隐藏页面重新画出来。
  const section = visibleNavigation.some((item) => item.id === requestedSection) ? requestedSection : "overview";
  const info = getSectionInfo(section);
  const displayInfo = (section === "faq" || section === "materials") && snapshot?.source === "live" && !canEditContent
    ? {
        // 素材页标题固定为「素材管理」，只读身份通过副标题体现，避免导航与页头两个名字。
        title: section === "faq" ? (canReviewContent ? "FAQ 审核" : "FAQ 查看") : info.title,
        subtitle: section === "faq" ? (canReviewContent ? "审核常见问题与答案，不修改正文" : "查看常见问题与答案（只读）") : "查看品牌素材（只读，无上传与删除权限）",
      }
    : info;

  // 页面注册表只认这一个 context；新增模块不用再改这里的 if 链。
  const sectionContext: SectionContext | null = snapshot
    ? {
        projectId,
        snapshot,
        can: (p) => snapshot.source !== "live" || !!snapshot.permissions?.includes(p),
        liveCan: (p) => snapshot.source === "live" && !!snapshot.permissions?.includes(p),
        isSystemAdmin: snapshot.source === "live" && snapshot.isSystemAdmin === true,
        navigate,
        notify: setToast,
        openTask,
        openManualTask,
        search,
        setSearch,
        status: statusFilter,
        setStatus: setStatusFilter,
        filteredProjects,
        filteredTasks,
        filteredLeads,
        actions,
        demoRounds,
        setDemoRounds,
        generatedRoundKeys,
        setGeneratedRoundKeys,
        reload: load,
      }
    : null;

  return <div className="app-shell">
    {mobileNav && <button className="mobile-scrim" aria-label="关闭菜单" onClick={() => setMobileNav(false)} />}
    <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
      <div className="sidebar-brand"><span className="brand-mark">G</span><span className="sidebar-brand-text">GEO<span className="brand-dot">.</span><small>WORKSPACE</small></span></div>
      <button type="button" className="sidebar-context" onClick={() => navigate("overview")}><span className="context-icon"><Icon name="spark" size={18}/></span><div><strong>品牌运营中心</strong><small>内容运营</small></div></button>
      <nav aria-label="工作台导航">
        <p className="nav-caption">运营工作台</p>
        {coreNavigation.map((item) => <button key={item.id} className={`nav-item ${section === item.id ? "active" : ""}`} onClick={() => navigate(item.id)}><Icon name={item.icon} size={19}/><span>{navLabel(item)}</span>{item.id === "reviews" && pendingReviews > 0 && <em>{pendingReviews}</em>}</button>)}
        {!!advancedNavigation.length && <button type="button" className={`nav-more-trigger ${advancedNavigation.some((item) => item.id === section) ? "active" : ""}`} aria-haspopup="dialog" onClick={() => setAdvancedNavModal(true)}><Icon name="grid" size={15}/><span>配置与管理</span><small>{advancedNavigation.length}</small><Icon name="chevronRight" size={14}/></button>}
      </nav>
      <div className="sidebar-bottom"><div className="sidebar-profile"><button type="button" className="sidebar-profile-main" onClick={openProfile}><span className="avatar">GE</span><span><strong>{snapshot?.source === "live" ? displayUserName(snapshot.userName) : "演示账号"}</strong><small>{snapshot?.source === "live" ? "当前登录" : "演示登录"}</small></span></button><button type="button" className="sidebar-profile-logout" aria-label="退出登录" onClick={(event) => { event.stopPropagation(); void logout(); }}><Icon name="logout" size={17}/></button></div></div>
    </aside>

    <div className="app-main"><header className="topbar"><button className="mobile-menu" aria-label="打开菜单" onClick={() => setMobileNav(true)}><Icon name="menu"/></button><div className="topbar-location"><span className="topbar-product">GEO 品牌工作台</span><span className="topbar-divider">/</span><strong>{displayInfo.title}</strong></div><div className="topbar-right"><span className="environment-pill"><i/> {snapshot ? (snapshot.source === "live" ? "数据已同步" : "演示数据") : "加载中"}</span><button type="button" className="topbar-guide" aria-label="打开使用指南" onClick={() => setHelpModal(true)}><Icon name="info" size={16}/><span>使用指南</span></button><button className="top-icon-button" aria-label="查看待审核" onClick={() => navigate("reviews")}><Icon name="bell" size={20}/>{pendingReviews > 0 && <i/>}</button><div className="topbar-account" ref={accountRef}><button type="button" className="topbar-user" aria-haspopup="menu" aria-expanded={accountMenu} onClick={() => { refreshAccountHistory(); setAccountMenu((open) => !open); }}><span className="avatar small">GE</span><strong>{snapshot?.source === "live" ? displayUserName(snapshot.userName) : "演示账号"}</strong><Icon name="chevronDown" size={15}/></button>{accountMenu && <div className="account-menu" role="menu"><p>当前登录：{currentLogin}</p><button type="button" role="menuitem" onClick={openProfile}>个人中心</button>{otherAccounts.length > 0 && <><p className="account-menu-group">其他账号</p>{otherAccounts.map((item) => <button key={item.username} type="button" role="menuitem" onClick={() => void switchToAccount(item.username)}>{item.username}</button>)}</>}<button type="button" role="menuitem" onClick={() => void addAccount()}>添加账号</button><button type="button" role="menuitem" onClick={openPasswordModal}>修改密码</button><button type="button" role="menuitem" onClick={() => void logout()}>退出登录</button></div>}</div></div></header>
      <main className="content-area"><div className="content-inner">
        {snapshot?.source !== "live" && <div className="demo-banner"><Icon name="info" size={17}/><span>{snapshot ? "当前为演示数据，仅用于页面预览；正式数据以账号实际权限为准。" : "正在加载工作台…"}</span></div>}
        <Header title={displayInfo.title} subtitle={displayInfo.subtitle} onHome={() => navigate("overview")} action={<><details className="project-select" ref={projectSelectRef}><summary className="project-select-wrap"><Icon name="folder" size={17}/><span>{snapshot ? (projectId === "all" ? "全部项目" : projectName(snapshot, projectId)) : "选择项目"}</span><Icon name="chevronDown" size={15}/></summary><div className="select-menu-list">{snapshot?.source !== "live" && <button type="button" className={projectId === "all" ? "selected" : ""} onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); chooseProject("all"); }}>全部项目</button>}{snapshot?.projects.map((project) => <button type="button" key={project.id} className={project.id === projectId ? "selected" : ""} onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); chooseProject(project.id); }}>{project.name}</button>)}</div></details>{section === "leads" && snapshot?.leadAccess === "allowed" && (snapshot.source === "mock" || snapshot.permissions?.includes(PERMISSION.LEAD_WRITE)) && !loading && <Button icon="plus" onClick={() => setLeadModal(true)}>新增线索</Button>}{section === "monitoring" && <Button variant="secondary" icon="refresh" onClick={() => void load(projectId)}>刷新任务</Button>}</>}/>
        {error && <div className="load-error" role="alert"><Icon name="info" size={18}/>{error}<Button variant="secondary" onClick={() => void load(projectId)}>重试</Button></div>}
        {loading && !snapshot ? <div className="loading-panel">正在加载工作台…</div> : snapshot && <>
          {/* eslint-disable-next-line react-hooks/refs -- 注册表只是把 context 分发给页面组件，渲染期不读任何 ref；ref 只在事件回调里用 */}
          {sectionContext && SECTION_VIEWS[section](sectionContext)}
        </>}
        <footer className="page-footer"><span>GEO 品牌工作台</span><span>当前项目：{currentProject}　·　2026</span></footer>
      </div></main>
    </div>

    {toast && <div className="toast" role="status"><Icon name="check" size={17}/>{toast}</div>}
    {advancedNavModal && <AdvancedNavDialog groups={advancedGroups} active={section} onClose={() => setAdvancedNavModal(false)} onGo={(id) => { setAdvancedNavModal(false); navigate(id); }}/>}
    {helpModal && <UsageGuide onClose={() => setHelpModal(false)} onGo={goFromGuide}/>}
    {passwordModal && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !passwordSaving) setPasswordModal(false); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="password-modal-title"><div className="modal-header"><div><p className="eyebrow">账号设置</p><h2 id="password-modal-title">修改密码</h2></div><button className="icon-button" aria-label="关闭" disabled={passwordSaving} onClick={() => setPasswordModal(false)}><Icon name="close" size={19}/></button></div><p className="modal-description">改密后其他设备上的登录会失效；当前浏览器会自动续用新会话，不用重新登录。</p><form onSubmit={submitPassword}><div className="form-grid"><TextInput label="原密码 *" type="password" autoComplete="current-password" required value={passwordForm.current} onChange={(event) => setPasswordForm({ ...passwordForm, current: event.target.value })} placeholder="请输入当前密码"/><TextInput label="新密码 *" type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={passwordForm.next} onChange={(event) => setPasswordForm({ ...passwordForm, next: event.target.value })} placeholder="至少 8 位"/><TextInput label="确认新密码 *" type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={passwordForm.confirm} onChange={(event) => setPasswordForm({ ...passwordForm, confirm: event.target.value })} placeholder="再次输入新密码"/></div>{passwordError && <p className="form-error" role="alert">{passwordError}</p>}<div className="modal-actions"><Button type="button" variant="secondary" disabled={passwordSaving} onClick={() => setPasswordModal(false)}>取消</Button><Button type="submit" disabled={passwordSaving}>{passwordSaving ? "提交中…" : "保存新密码"}</Button></div></form></div></div>}
    {leadModal && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setLeadModal(false); }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="lead-modal-title"><div className="modal-header"><div><p className="eyebrow">新增线索</p><h2 id="lead-modal-title">新增线索</h2></div><button className="icon-button" aria-label="关闭" onClick={() => setLeadModal(false)}><Icon name="close" size={19}/></button></div><p className="modal-description">填写咨询信息，提交后会出现在当前列表中。</p><form onSubmit={submitLead}><div className="form-grid"><TextInput label="联系人 *" required value={leadForm.contactName} onChange={(event) => setLeadForm({ ...leadForm, contactName: event.target.value })} placeholder="例如：张女士"/><TextInput label="联系电话" value={leadForm.phone} onChange={(event) => setLeadForm({ ...leadForm, phone: event.target.value })} placeholder="请输入联系电话"/><TextInput label="意向课程" value={leadForm.interest} onChange={(event) => setLeadForm({ ...leadForm, interest: event.target.value })} placeholder="例如：少儿英语"/><SelectInput label="线索来源" value={leadForm.source} onChange={(event) => setLeadForm({ ...leadForm, source: event.target.value })}><option>官网表单</option><option>公众号</option><option>自然搜索</option><option>活动页面</option><option>其他</option></SelectInput><TextInput label="自报 AI 产品" value={leadForm.reportedAiProduct} onChange={(event) => setLeadForm({ ...leadForm, reportedAiProduct: event.target.value })} placeholder="例如：豆包 / 元宝 / DeepSeek"/><SelectInput label="是否有效" value={leadForm.isValid ? "true" : "false"} onChange={(event) => setLeadForm({ ...leadForm, isValid: event.target.value === "true" })}><option value="true">有效线索</option><option value="false">无效 / 误留资</option></SelectInput></div><div className="modal-actions"><Button type="button" variant="secondary" onClick={() => setLeadModal(false)}>取消</Button><Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存线索"}</Button></div></form></div></div>}
    {taskDetail && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closeTaskDetail(); }}>
      <div className="modal task-modal" role="dialog" aria-modal="true" aria-labelledby="task-modal-title">
        <div className="modal-header"><div><p className="eyebrow">监测任务</p><h2 id="task-modal-title">任务详情</h2></div><button className="icon-button" aria-label="关闭" onClick={closeTaskDetail}><Icon name="close" size={19}/></button></div>
        <div className="task-details"><span>任务编号</span><strong>#{taskDetail.serialNo || "—"}</strong><span>监测问题</span><strong>{taskDetail.question}</strong><span>AI 引擎</span><strong>{taskDetail.engine}</strong><span>执行状态</span><Badge tone={statusTone(taskDetail.status)} dot>{taskDetail.status}</Badge></div>
        {canCancelTask && taskDetail.status === "待执行" && <p className="field-hint">{taskCancelConfirm ? "确认作废后任务不会再执行；任务和样本记录仍保留，可在状态筛选中查看。" : "任务尚未执行。作废只停止排队，不删除任务记录。"}</p>}
        {taskCancelError && <p className="form-error" role="alert">{taskCancelError}</p>}
        <div className="modal-actions">
          {canCancelTask && taskDetail.status === "待执行" && (taskCancelConfirm ? <>
            <Button variant="danger" disabled={taskCancelling} onClick={() => void cancelTask()}>{taskCancelling ? "作废中…" : "确认作废"}</Button>
            <Button variant="secondary" disabled={taskCancelling} onClick={() => setTaskCancelConfirm(false)}>返回</Button>
          </> : <Button variant="danger" onClick={() => setTaskCancelConfirm(true)}>作废任务</Button>)}
          <Button variant="secondary" onClick={closeTaskDetail}>关闭</Button>
        </div>
      </div>
    </div>}
  </div>;
}
