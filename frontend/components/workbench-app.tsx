"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Badge, Button, DetailModal, Icon, SelectInput, TextInput } from "./ui";
import { SECTION_VIEWS, type OverviewTodo, type SectionContext } from "./workbench/section-registry";
import { displayUserName, projectName, statusTone } from "./workbench/shared";
import { initialDemoRounds } from "./monitoring-rounds";
import { workbenchClient } from "@/lib/workbench/client";
import { readAccountHistory, recordAccount } from "@/lib/workbench/account-history";
import { formatDateTime } from "@/lib/workbench/format";
import { ADVANCED_NAV_GROUPS, ADVANCED_SECTIONS, CLIENT_NAV_GROUPS, CLIENT_NAV_ORDER, getClientSectionInfo, getSectionInfo, navigation, OPERATOR_NAV_GROUPS, OPERATOR_SECTION_IDS, type NavItemConfig } from "@/lib/workbench/navigation";
import { ClientOverview } from "./workbench/client-overview";
import { ClientStatistics } from "./workbench/client-statistics";
import { ClientAlerts, ClientCompetitors, ClientLeads, ClientMonthly, ClientSentiment } from "./workbench/client-pages";
import { PERMISSION } from "@/lib/workbench/permissions";
import { canSeeNavItem } from "@/lib/workbench/visibility";
import { useWorkbenchActions } from "@/lib/workbench/use-workbench-actions";
import type { MonitoringRound, MonitoringTask, Section, TodoCenter, TodoRange, WorkbenchSnapshot } from "@/lib/workbench/types";

type NavItem = NavItemConfig;

/** 账号显示只保留业务名称，隐藏 seed、API 适配器等实现备注。 */
function Header({ title, subtitle, action }: { title: string; subtitle: string; action?: React.ReactNode }) {
  return <div className="section-header"><div><h1>{title}</h1><p>{subtitle}</p></div>{action && <div className="section-actions">{action}</div>}</div>;
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

/**
 * mock 只内置一份“服务端已经算好的窗口”样本，前端不得再按浏览器时区推导今天/本周。
 * 真实 API 由后端返回 business_timezone 与 window，页面只消费这两个字段。
 */
const MOCK_SERVER_TIME = "2026-11-26T05:00:00.000Z";
const MOCK_WINDOWS: Record<TodoRange, { start: string; end: string } | null> = {
  today: { start: "2026-11-25T16:00:00.000Z", end: "2026-11-26T16:00:00.000Z" },
  week: { start: "2026-11-22T16:00:00.000Z", end: "2026-11-29T16:00:00.000Z" },
  all: null,
};

function inServerWindow(at: string | null | undefined, range: TodoRange): boolean {
  if (range === "all") return true;
  if (!at) return false;
  const window = MOCK_WINDOWS[range];
  if (!window) return false;
  const timestamp = Date.parse(at);
  if (Number.isNaN(timestamp)) return false;
  return timestamp >= Date.parse(window.start) && timestamp < Date.parse(window.end);
}

/** 演示模式没有后端聚合接口，只从演示快照生成两类待办，时间字段与线上契约一致。 */
function mockTodoCenter(snapshot: WorkbenchSnapshot, projectId: string, range: TodoRange): TodoCenter {
  const allItems = [
    ...snapshot.tasks
      .filter((task) => task.status === "失败" || task.status === "需复核")
      .map((task) => ({
        key: `task-${task.id}`,
        group: "采集失败" as const,
        title: task.questionTitle ?? task.question,
        meta: `${task.engine} · 任务 #${task.serialNo ?? "—"} · ${task.status}`,
        section: "monitoring",
        tone: (task.status === "失败" ? "red" : "amber") as "red" | "amber",
        badge: task.status,
        at: task.enteredTodoAt ?? null,
      })),
    ...snapshot.reviews
      .filter((item) => item.status === "待审核")
      .map((item) => ({
        key: `review-${item.id}`,
        group: "内容审核" as const,
        title: item.title,
        meta: `${item.author} · ${item.type}`,
        section: "reviews",
        tone: "amber" as const,
        badge: "待审核",
        at: item.enteredTodoAt ?? null,
      })),
  ];

  const groups: TodoCenter["groups"] = (["采集失败", "内容审核"] as const).map((label) => {
    const groupItems = allItems.filter((item) => item.group === label);
    const counts = {
      today: groupItems.filter((item) => inServerWindow(item.at, "today")).length,
      week: groupItems.filter((item) => inServerWindow(item.at, "week")).length,
      all: groupItems.length,
    };
    return {
      key: label === "采集失败" ? "collect" : "reviews",
      label,
      section: label === "采集失败" ? "monitoring" : "reviews",
      counts,
      total: counts[range],
      items: groupItems.filter((item) => inServerWindow(item.at, range)),
    };
  });
  const counts = { today: 0, week: 0, all: 0 };
  for (const group of groups) {
    counts.today += group.counts.today;
    counts.week += group.counts.week;
    counts.all += group.counts.all;
  }
  return {
    project_id: projectId,
    range,
    business_timezone: "Asia/Shanghai",
    generated_at: MOCK_SERVER_TIME,
    window: MOCK_WINDOWS[range],
    counts,
    groups,
  };
}

const TASK_GROUP_COPY: Record<string, { description: string; cta: string; section: Section }> = {
  异常预警: { description: "影响主指标的异常先看；确认或解决后预警才退出待办。", cta: "去预警", section: "alerts" },
  采集失败: { description: "失败与需复核任务会直接影响有效回答分母，优先重试或人工补录。", cta: "去监测", section: "monitoring" },
  内容审核: { description: "待审核版本会阻塞发布，先处理。", cta: "去审核", section: "reviews" },
  发布队列: { description: "待发布和待复核任务；进入后按任务详情完成发布或复核。", cta: "去发布", section: "publishing" },
  事实审批: { description: "草稿、待审批和缺来源的事实；批准前不能进入内容引用。", cta: "去事实库", section: "facts" },
  知识解析: { description: "未解析文档和候选事实；解析完成后才能参与检索和证据引用。", cta: "去知识库", section: "knowledge" },
};

interface SearchEntry {
  id: string;
  group: string;
  title: string;
  meta: string;
  section: Section;
  keywords?: string;
  projectId?: string;
}

function searchScore(entry: SearchEntry, query: string): number {
  const title = entry.title.toLowerCase();
  if (title === query) return 0;
  if (title.startsWith(query)) return 1;
  if (title.includes(query)) return 2;
  if (entry.meta.toLowerCase().includes(query)) return 3;
  if (entry.keywords?.toLowerCase().includes(query)) return 4;
  return 99;
}

function GlobalSearchDialog({ query, setQuery, groups, primary, onGo, onClose }: {
  query: string;
  setQuery: (value: string) => void;
  groups: { label: string; items: SearchEntry[] }[];
  primary?: SearchEntry;
  onGo: (entry: SearchEntry) => void;
  onClose: () => void;
}) {
  const first = primary ?? groups.flatMap((group) => group.items)[0];
  return <DetailModal eyebrow="工作台搜索" title="搜索当前项目" subtitle="只搜索当前项目已加载的页面、任务和待处理事项；不跨项目，也不代表全库搜索。" onClose={onClose}>
    <div className="search-dialog">
      <div className="search-input-row">
        <Icon name="search" size={18}/>
        <input autoFocus className="search-input" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && first) { event.preventDefault(); onGo(first); } }} placeholder="搜索页面、任务问题、内容标题、事实关键词…" aria-label="搜索工作台"/>
        {query && <button type="button" className="search-clear" aria-label="清空搜索" onClick={() => setQuery("")}><Icon name="close" size={15}/></button>}
        <kbd>Esc</kbd>
      </div>
      <div className="search-results">
        {groups.map((group) => <section className="search-group" key={group.label}>
          <header><span>{group.label}</span><small>{group.items.length}</small></header>
          {group.items.map((entry) => <button type="button" key={entry.id} className="search-result" onClick={() => onGo(entry)}>
            <span className="search-result-copy"><strong>{entry.title}</strong><small>{entry.meta}</small></span>
            <Icon name="arrowRight" size={15}/>
          </button>)}
        </section>)}
        {!groups.length && <div className="search-empty"><Icon name="search" size={20}/><strong>没有匹配结果</strong><p>试试页面名、任务问题、内容标题、事实关键词或项目名称。</p></div>}
      </div>
      <p className="search-footnote">搜索只覆盖当前项目已加载的数据；跨项目请先切换左侧项目上下文。</p>    </div>
  </DetailModal>;
}

function writeLocation(section: Section, projectId: string, mode: "push" | "replace" = "push") {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  // 总览是工作台默认页，URL 不写 section，避免进入工作台时先跳一次地址。
  if (section === "overview") url.searchParams.delete("section");
  else url.searchParams.set("section", section);
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
      <div className="guide-step"><span>01</span><div><strong>先确认项目和数据</strong><p>看右上角项目是否选对；「监测总览」会显示 AI 回答里提到你、带链接和回答缺口。数据为空时，先建监测任务或补渠道。</p></div></div>
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
  const [taskCenterOpen, setTaskCenterOpen] = useState(false);
  const [taskRange, setTaskRange] = useState<TodoRange>("all");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  // 待办只保留一份“属于哪个项目”的状态；项目切换时渲染层先比对 projectId，旧项目数据不会上屏。
  const [todoState, setTodoState] = useState<{ projectId: string; data: TodoCenter | null; loading: boolean; error: string }>({ projectId: "", data: null, loading: false, error: "" });
  const [todoRefresh, setTodoRefresh] = useState(0);
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
  // 客户视图按成员角色判断，不按“是否缺写权限”判断；项目管理员同样没有 content.write，但仍是内部视图。
  const isClientView = snapshot?.source === "live" && snapshot.projectRoleCode === "viewer";

  // 六类待办由后端按项目聚合：计数是全量，预览有上限；时间范围也由后端按本地时区切窗。
  const snapshotSource = snapshot?.source;
  useEffect(() => {
    if (!snapshotSource || snapshotSource !== "live" || isClientView || !projectId || projectId === "all") {
      return;
    }
    const controller = new AbortController();
    Promise.resolve().then(() => {
      if (!controller.signal.aborted) setTodoState({ projectId, data: null, loading: true, error: "" });
    });
    workbenchClient.todos(projectId, taskRange, 20, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setTodoState({ projectId, data: result, loading: false, error: "" });
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setTodoState({ projectId, data: null, loading: false, error: cause instanceof Error ? cause.message : "待办加载失败" });
      });
    return () => controller.abort();
  }, [projectId, snapshotSource, isClientView, taskRange, todoRefresh]);

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchQuery("");
        setSearchOpen((open) => !open);
      }
    }
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, []);

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
    const visible = navigation.filter((item) => canSeeNavItem(item, snapshot) && (!isClientView || CLIENT_NAV_ORDER.includes(item.id)));
    // URL 里可能带着无权限的旧 section；保留在同一套工作台里回落到监测总览，不再跳到独立页面。
    if (!visible.some((item) => item.id === requestedSection)) {
      writeLocation("overview", projectId, "replace");
    }
  }, [snapshot, requestedSection, projectId, isClientView]);

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

  const pendingReviewItems = snapshot?.reviews.filter((item) => item.status === "待审核") ?? [];
  const pendingReviews = pendingReviewItems.length;
  const todoData = todoState.projectId === projectId
    ? todoState.data
    : snapshot?.source === "mock"
      ? mockTodoCenter(snapshot, projectId, taskRange)
      : null;
  const taskCenterLoading = snapshot?.source === "live" && todoState.loading && todoState.projectId === projectId;
  const todoError = todoState.projectId === projectId ? todoState.error : "";
  const todoGroups = (todoData?.groups ?? []).map((group) => group.items);
  const todoCount = todoData?.counts[taskRange] ?? 0;
  const allTodoCount = todoData?.counts.all ?? 0;
  const todoRangeCounts = todoData?.counts ?? { today: 0, week: 0, all: 0 };
  const todoGroupCount = (label: string) => todoData?.groups.find((group) => group.label === label)?.total ?? 0;
  // 三个来源轮流取第一条，让右栏真正跨模块，而不是被最多的一类占满。
  const todoPreview: OverviewTodo[] = [];
  for (let round = 0; todoPreview.length < 3 && round < Math.max(...todoGroups.map((group) => group.length)); round += 1) {
    for (const group of todoGroups) {
      const item = group[round];
      if (item && todoPreview.length < 3) {
        todoPreview.push({
          key: item.key,
          group: item.group,
          title: item.title,
          meta: item.meta,
          section: item.section as Section,
          tone: item.tone,
          at: item.at,
        });
      }
    }
  }
  const openTaskCenter = () => {
    setTaskCenterOpen(true);
    setTodoRefresh((value) => value + 1);
  };
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
  const visibleNavigation = navigation.filter(canSee).filter((item) => !isClientView || CLIENT_NAV_ORDER.includes(item.id));
  const clientNavigation = CLIENT_NAV_ORDER
    .map((id) => visibleNavigation.find((item) => item.id === id))
    .filter((item): item is NavItemConfig => Boolean(item))
    .map((item) => {
      const meta = getClientSectionInfo(item.id);
      return { ...item, label: meta.title, subtitle: meta.subtitle };
    });
  const operatorNavGroups = isClientView
    ? []
    : OPERATOR_NAV_GROUPS
      .map((group) => ({
        ...group,
        items: group.sections
          .map((id) => visibleNavigation.find((item) => item.id === id))
          .filter((item): item is NavItemConfig => Boolean(item)),
      }))
      .filter((group) => group.items.length > 0);
  const clientNavGroups = CLIENT_NAV_GROUPS
    .map((group) => ({ ...group, items: group.sections.map((id) => clientNavigation.find((item) => item.id === id)).filter((item): item is NavItemConfig => Boolean(item)) }))
    .filter((group) => group.items.length > 0);
  const advancedNavigation = isClientView
    ? []
    : visibleNavigation.filter((item) => ADVANCED_SECTIONS.includes(item.id) && !OPERATOR_SECTION_IDS.includes(item.id));
  const advancedGroups = isClientView
    ? []
    : ADVANCED_NAV_GROUPS
      .map((group) => ({ ...group, items: advancedNavigation.filter((item) => group.sections.includes(item.id)).map((item) => ({ ...item, label: navLabel(item) })) }))
      .filter((group) => group.items.length > 0);

  // 全局搜索只查当前项目已加载的数据，不额外发请求；跨项目先切换左侧项目。
  const searchEntries: SearchEntry[] = [];
  visibleNavigation.forEach((item) => searchEntries.push({ id: `page-${item.id}`, group: "页面", title: navLabel(item), meta: item.subtitle, section: item.id, keywords: item.label }));
  if (snapshot) {
    snapshot.projects.forEach((project) => searchEntries.push({ id: `project-${project.id}`, group: "项目", title: projectName(snapshot, project.id), meta: `项目 ${project.code ?? "—"} · ${project.status ?? ""}`, section: "overview", projectId: project.id, keywords: project.code }));
    snapshot.tasks.forEach((task) => searchEntries.push({ id: `task-${task.id}`, group: "监测任务", title: `#${task.serialNo ?? "—"} · ${task.questionTitle ?? task.question}`, meta: `${task.engine} · ${task.status}`, section: "monitoring", keywords: `${task.question} ${task.engine}` }));
    snapshot.reviews.forEach((item) => searchEntries.push({ id: `review-${item.id}`, group: "内容版本", title: item.title, meta: `${item.author} · ${item.status} · ${formatDateTime(item.submittedAt)}`, section: "reviews", keywords: item.type }));
    if (snapshot.leadAccess === "allowed") snapshot.leads.forEach((lead) => searchEntries.push({ id: `lead-${lead.id}`, group: "线索", title: `${lead.contactName} · ${lead.interest}`, meta: `${lead.phone} · ${lead.status} · ${lead.source}`, section: "leads", keywords: lead.phone }));
  }
  todoData?.groups.flatMap((group) => group.items).forEach((item) => searchEntries.push({ id: `todo-${item.key}`, group: item.group, title: item.title, meta: item.meta, section: item.section as Section, keywords: `${item.title} ${item.meta}` }));

  const normalizedSearch = searchQuery.trim().toLowerCase();
  let searchGroups: { label: string; items: SearchEntry[] }[] = [];
  let searchPrimary: SearchEntry | undefined;
  if (!normalizedSearch) {
    const quickIds: Section[] = ["overview", "report", "statistics", "reviews", "publishing", "knowledge", "facts", "company"];
    const quickPages = quickIds.map((id) => searchEntries.find((entry) => entry.id === `page-${id}`)).filter((entry): entry is SearchEntry => Boolean(entry));
    const pending = (todoData?.groups.flatMap((group) => group.items) ?? []).slice(0, 4).map((todo) => ({
      id: `todo-${todo.key}`,
      group: "待处理",
      title: todo.title,
      meta: todo.meta,
      section: todo.section as Section,
    } satisfies SearchEntry));
    searchGroups = [{ label: "待处理", items: pending }, { label: "快速前往", items: quickPages }].filter((group) => group.items.length > 0);
    searchPrimary = pending[0] ?? quickPages[0];
  } else {
    const matched = searchEntries
      .map((entry) => ({ entry, score: searchScore(entry, normalizedSearch) }))
      .filter((item) => item.score < 99)
      .sort((a, b) => a.score - b.score || a.entry.title.localeCompare(b.entry.title, "zh-CN"))
      .map((item) => item.entry);
    // Enter 打开全局相关度最高的结果；分组只是展示，不改变排名。
    searchPrimary = matched[0];
    const order = ["待处理", "页面", "项目", "监测任务", "内容版本", "发布队列", "事实审批", "知识解析", "线索", "异常预警"];
    searchGroups = order
      .map((label) => ({ label, items: matched.filter((entry) => entry.group === label).slice(0, 4) }))
      .filter((group) => group.items.length > 0);
  }
  // URL 里可能带着无权限或不属于客户视图的旧 section；渲染时回落到概览。
  const section = visibleNavigation.some((item) => item.id === requestedSection) ? requestedSection : "overview";
  const activeOperatorGroup = operatorNavGroups.find((group) => group.items.some((item) => item.id === section));
  const info = isClientView ? getClientSectionInfo(section) : getSectionInfo(section);
  const displayInfo = !isClientView && (section === "faq" || section === "materials") && snapshot?.source === "live" && !canEditContent
    ? {
        // 素材页标题固定为「素材管理」，只读身份通过副标题体现，避免导航与页头两个名字。
        title: section === "faq" ? (canReviewContent ? "FAQ 审核" : "FAQ 查看") : info.title,
        subtitle: section === "faq" ? (canReviewContent ? "审核常见问题与答案，不修改正文" : "查看常见问题与答案（只读）") : "查看品牌素材（只读，无上传与删除权限）",
      }
    : info;

  const clientSection = isClientView && snapshot
    ? section === "overview"
      ? <ClientOverview snapshot={snapshot} projectId={projectId} navigate={navigate}/>
      : section === "statistics"
        ? <ClientStatistics snapshot={snapshot} projectId={projectId} navigate={navigate}/>
        : section === "sentiment"
          ? <ClientSentiment projectId={projectId} navigate={navigate}/>
          : section === "competitors"
            ? <ClientCompetitors projectId={projectId} navigate={() => navigate("statistics")}/>
            : section === "alerts"
              ? <ClientAlerts projectId={projectId} navigate={navigate}/>
              : section === "monthly"
                ? <ClientMonthly projectId={projectId} canDownload={!!snapshot.permissions?.includes(PERMISSION.EXPORT_DATA)}/>
                : section === "leads"
                  ? <ClientLeads leads={filteredLeads} navigate={navigate}/>
                  : null
    : null;


  const sectionContext: SectionContext | null = snapshot
    ? {
        projectId,
        snapshot,
        can: (p) => snapshot.source !== "live" || !!snapshot.permissions?.includes(p),
        liveCan: (p) => snapshot.source === "live" && !!snapshot.permissions?.includes(p),
        isSystemAdmin: snapshot.source === "live" && snapshot.isSystemAdmin === true,
        clientMode: isClientView,
        navigate,
        notify: setToast,
        openTask,
        openManualTask,
        todos: todoPreview,
        todoCount,
        todoLoading: taskCenterLoading,
        openTodoCenter: openTaskCenter,
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

  if (isClientView) {
    const activeClientGroup = clientNavGroups.find((group) => group.items.some((item) => item.id === section));
    const pageGroupTitle = activeClientGroup?.title ?? (section === "profile" ? "账户" : "总览");
    const clientUserName = snapshot?.source === "live" ? displayUserName(snapshot.userName) : "演示账号";
    return <div className="client-app-shell">
      <header className="client-app-header">
        <div className="client-app-brand">
          <span className="client-app-mark">G</span>
          <div><strong>GEO</strong><small>AI 品牌看板</small></div>
        </div>
        <nav className="client-app-nav" aria-label="品牌导航">
          {clientNavGroups.map((group) => <button key={group.title} type="button" className={activeClientGroup?.title === group.title ? "active" : ""} onClick={() => navigate(group.items[0].id)}>{group.title}</button>)}
        </nav>
        <div className="client-app-tools">
          <details className="project-select client-project-select" ref={projectSelectRef}>
            <summary className="project-select-wrap"><span>{snapshot ? (projectId === "all" ? "全部项目" : projectName(snapshot, projectId)) : "选择品牌"}</span><Icon name="chevronDown" size={14}/></summary>
            <div className="select-menu-list">{snapshot?.projects.map((project) => <button type="button" key={project.id} className={project.id === projectId ? "selected" : ""} onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); chooseProject(project.id); }}>{project.name}</button>)}</div>
          </details>
          <div className="topbar-account client-app-account" ref={accountRef}>
            <button type="button" className="client-account-trigger" aria-haspopup="menu" aria-expanded={accountMenu} onClick={() => { refreshAccountHistory(); setAccountMenu((open) => !open); }}><span className="avatar small">GE</span><span>{clientUserName}</span><Icon name="chevronDown" size={14}/></button>
            {accountMenu && <div className="account-menu client-account-menu" role="menu"><p>当前登录：{currentLogin}</p><button type="button" role="menuitem" onClick={openProfile}>个人中心</button>{otherAccounts.length > 0 && <><p className="account-menu-group">其他账号</p>{otherAccounts.map((item) => <button key={item.username} type="button" role="menuitem" onClick={() => void switchToAccount(item.username)}>{item.username}</button>)}</>}<button type="button" role="menuitem" onClick={() => void logout()}>退出登录</button></div>}
          </div>
        </div>
      </header>

      <main className="client-app-main">
        <div className="client-app-inner">
          <div className="client-page-head">
            {section !== "overview" && <p className="client-page-group">{pageGroupTitle}</p>}
            <div className="client-page-title-row">
              <div><h1>{displayInfo.title}</h1><p>{displayInfo.subtitle}</p></div>
              {section === "overview" && <Button onClick={() => navigate("monthly")}>生成本月报告 <Icon name="arrowRight" size={15}/></Button>}
            </div>
          </div>

          {activeClientGroup && activeClientGroup.items.length > 1 && <nav className="client-subnav" aria-label={`${pageGroupTitle}子导航`}>
            {activeClientGroup.items.map((item) => <button type="button" key={item.id} className={section === item.id ? "active" : ""} onClick={() => navigate(item.id)}>{item.label}</button>)}
          </nav>}

          {snapshot?.source !== "live" && <div className="demo-banner"><Icon name="info" size={17}/><span>{snapshot ? "当前为演示数据，仅用于页面预览。" : "正在加载…"}</span></div>}
          {error && <div className="load-error" role="alert"><Icon name="info" size={18}/>{error}<Button variant="secondary" onClick={() => void load(projectId)}>重试</Button></div>}
          {loading && !snapshot ? <div className="loading-panel">正在加载…</div> : snapshot && <>
            {/* eslint-disable-next-line react-hooks/refs -- 注册表只是把 context 分发给页面组件，渲染期不读任何 ref；ref 只在事件回调里用 */}
            {clientSection ?? (sectionContext && SECTION_VIEWS[section](sectionContext))}
          </>}
        </div>
      </main>

      {toast && <div className="toast" role="status"><Icon name="check" size={17}/>{toast}</div>}
    </div>;
  }

  return <div className="app-shell">
    {mobileNav && <button className="mobile-scrim" aria-label="关闭菜单" onClick={() => setMobileNav(false)} />}
    <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
      <div className="sidebar-brand"><span className="brand-mark" aria-hidden="true"><i/><i/><i/></span><span className="sidebar-brand-text">GEO 观察台<small>SEARCH VISIBILITY</small></span></div>
      <button type="button" className="sidebar-context" onClick={() => navigate("overview")}><span className="context-icon"><Icon name="spark" size={18}/></span><div><strong>{snapshot ? (projectId === "all" ? "全部项目" : projectName(snapshot, projectId)) : "选择项目"}</strong><small>主项目 · 运营视图</small></div><Icon name="chevronDown" size={13}/></button>
      <nav aria-label="工作台导航">
        {isClientView
          ? clientNavGroups.map((group) => <div className="nav-group" key={group.title}>
              <p className="nav-caption">{group.title}</p>
              {group.items.map((item) => <button key={item.id} className={`nav-item ${section === item.id ? "active" : ""}`} onClick={() => navigate(item.id)}><Icon name={item.icon} size={19}/><span>{navLabel(item)}</span></button>)}
            </div>)
          : <>
              {operatorNavGroups.map((group) => {
                const primary = group.items[0];
                const active = group.items.some((item) => item.id === section);
                const pendingReviewCount = group.items.some((item) => item.id === "reviews") ? pendingReviews : 0;
                return <button key={group.title} type="button" className={`nav-item ${active ? "active" : ""}`} onClick={() => navigate(primary.id)}>
                  <Icon name={group.icon} size={19}/><span>{group.title}</span>
                  {pendingReviewCount > 0 && <em>{pendingReviewCount}</em>}
                </button>;
              })}
              {!!advancedNavigation.length && <button type="button" className={`nav-more-trigger ${advancedNavigation.some((item) => item.id === section) ? "active" : ""}`} aria-haspopup="dialog" onClick={() => setAdvancedNavModal(true)}><Icon name="grid" size={15}/><span>配置</span><small>{advancedNavigation.length}</small><Icon name="chevronRight" size={14}/></button>}
            </>}
      </nav>
      <div className="sidebar-bottom"><div className="sidebar-profile"><button type="button" className="sidebar-profile-main" onClick={openProfile}><span className="avatar">GE</span><span><strong>{snapshot?.source === "live" ? displayUserName(snapshot.userName) : "演示账号"}</strong><small>{snapshot?.source === "live" ? "当前登录" : "演示登录"}</small></span></button><button type="button" className="sidebar-profile-logout" aria-label="退出登录" onClick={(event) => { event.stopPropagation(); void logout(); }}><Icon name="logout" size={17}/></button></div></div>
    </aside>

    <div className="app-main"><header className="topbar"><button className="mobile-menu" aria-label="打开菜单" onClick={() => setMobileNav(true)}><Icon name="menu"/></button><div className="topbar-location"><span className="topbar-product">GEO 观察台</span><span className={`view-mode-pill${isClientView ? " is-client" : ""}`}>{isClientView ? "客户视图" : "运营视图"}</span></div><div className="topbar-right"><button type="button" className="topbar-search" aria-label="打开全局搜索" onClick={() => { setSearchQuery(""); setSearchOpen(true); }}><Icon name="search" size={16}/><span>搜索</span><kbd>Ctrl K</kbd></button><span className="environment-pill"><i/> {snapshot ? (snapshot.source === "live" ? "数据已接通" : "演示数据") : "加载中"}</span>{!isClientView && <button type="button" className="topbar-guide" aria-label="打开使用指南" onClick={() => setHelpModal(true)}><Icon name="info" size={16}/><span>使用指南</span></button>}<button type="button" className="topbar-guide" aria-label="打印当前页面" onClick={() => { if (typeof window !== "undefined") window.print(); }}><Icon name="printer" size={16}/><span>导出</span></button>{!isClientView && <button className="top-icon-button top-task-button" aria-label={`待办 ${todoCount} 项`} onClick={openTaskCenter}><Icon name="check" size={18}/><span>待办</span>{todoCount > 0 && <b>{todoCount > 99 ? "99+" : todoCount}</b>}</button>}<div className="topbar-account" ref={accountRef}><button type="button" className="topbar-user" aria-haspopup="menu" aria-expanded={accountMenu} onClick={() => { refreshAccountHistory(); setAccountMenu((open) => !open); }}><span className="avatar small">GE</span><strong>{snapshot?.source === "live" ? displayUserName(snapshot.userName) : "演示账号"}</strong><Icon name="chevronDown" size={15}/></button>{accountMenu && <div className="account-menu" role="menu"><p>当前登录：{currentLogin}</p><button type="button" role="menuitem" onClick={openProfile}>个人中心</button>{otherAccounts.length > 0 && <><p className="account-menu-group">其他账号</p>{otherAccounts.map((item) => <button key={item.username} type="button" role="menuitem" onClick={() => void switchToAccount(item.username)}>{item.username}</button>)}</>}<button type="button" role="menuitem" onClick={() => void addAccount()}>添加账号</button><button type="button" role="menuitem" onClick={openPasswordModal}>修改密码</button><button type="button" role="menuitem" onClick={() => void logout()}>退出登录</button></div>}</div></div></header>
      <main className="content-area"><div className="content-inner">
        {snapshot?.source !== "live" && <div className="demo-banner"><Icon name="info" size={17}/><span>{snapshot ? "当前为演示数据，仅用于页面预览；正式数据以账号实际权限为准。" : "正在加载工作台…"}</span></div>}
        <Header title={displayInfo.title} subtitle={displayInfo.subtitle} action={section === "leads" && snapshot?.leadAccess === "allowed" && (snapshot.source === "mock" || snapshot.permissions?.includes(PERMISSION.LEAD_WRITE)) && !loading
          ? <Button icon="plus" onClick={() => setLeadModal(true)}>新增线索</Button>
          : section === "monitoring" ? <Button variant="secondary" icon="refresh" onClick={() => void load(projectId)}>刷新任务</Button> : undefined}/>
        {activeOperatorGroup && activeOperatorGroup.items.length > 1 && <nav className="client-subnav" aria-label={`${activeOperatorGroup.title}子导航`}>
          {activeOperatorGroup.items.map((item) => <button type="button" key={item.id} className={section === item.id ? "active" : ""} onClick={() => navigate(item.id)}>{navLabel(item)}</button>)}
        </nav>}
        {error && <div className="load-error" role="alert"><Icon name="info" size={18}/>{error}<Button variant="secondary" onClick={() => void load(projectId)}>重试</Button></div>}
        {loading && !snapshot ? <div className="loading-panel">正在加载工作台…</div> : snapshot && <>
          {/* eslint-disable-next-line react-hooks/refs -- 注册表只是把 context 分发给页面组件，渲染期不读任何 ref；ref 只在事件回调里用 */}
          {clientSection ?? (sectionContext && SECTION_VIEWS[section](sectionContext))}
        </>}
        <footer className="page-footer"><span>{isClientView ? "GEO 观察台 · 客户视图" : "GEO 观察台"}</span><span>当前项目：{currentProject}　·　2026</span></footer>
      </div></main>
    </div>

    {toast && <div className="toast" role="status"><Icon name="check" size={17}/>{toast}</div>}
    {advancedNavModal && <AdvancedNavDialog groups={advancedGroups} active={section} onClose={() => setAdvancedNavModal(false)} onGo={(id) => { setAdvancedNavModal(false); navigate(id); }}/>}
    {searchOpen && <GlobalSearchDialog query={searchQuery} setQuery={setSearchQuery} groups={searchGroups} primary={searchPrimary} onClose={() => setSearchOpen(false)} onGo={(entry) => { setSearchOpen(false); setSearchQuery(""); if (entry.projectId) { setRequestedSection("overview"); setProjectId(entry.projectId); writeLocation("overview", entry.projectId); if (snapshot?.source === "live") void load(entry.projectId); } else navigate(entry.section); }}/>}
    {taskCenterOpen && <DetailModal eyebrow="跨模块待办" title="待办中心" subtitle={`${todoCount} 项需要人工处理${taskRange === "all" ? "" : `（全部 ${allTodoCount} 项）`}；按进入待处理状态的时间排序，完成一项后回到原模块处理`} onClose={() => setTaskCenterOpen(false)}>
      <div className="task-center">
        <div className="task-center-range" role="group" aria-label="待办时间范围">
          {([["today", "今天"], ["week", "本周"], ["all", "全部"]] as const).map(([value, label]) => <button type="button" key={value} className={taskRange === value ? "active" : ""} aria-pressed={taskRange === value} onClick={() => setTaskRange(value)}>{label}<span>{todoRangeCounts[value]}</span></button>)}
        </div>
        <div className="task-center-summary task-center-summary-six">
          <div><span>内容审核</span><strong>{taskCenterLoading ? "…" : todoGroupCount("内容审核")}</strong></div>
          <div><span>发布 / 待复核</span><strong>{taskCenterLoading ? "…" : todoGroupCount("发布队列")}</strong></div>
          <div><span>采集失败</span><strong>{taskCenterLoading ? "…" : todoGroupCount("采集失败")}</strong></div>
          <div><span>事实草稿 / 缺来源</span><strong>{taskCenterLoading ? "…" : todoGroupCount("事实审批")}</strong></div>
          <div><span>知识待解析</span><strong>{taskCenterLoading ? "…" : todoGroupCount("知识解析")}</strong></div>
          <div><span>未处理预警</span><strong>{taskCenterLoading ? "…" : todoGroupCount("异常预警")}</strong></div>
        </div>

        {(["异常预警", "采集失败", "内容审核", "发布队列", "事实审批", "知识解析"] as const).map((label) => {
          const group = todoData?.groups.find((item) => item.label === label);
          const copy = TASK_GROUP_COPY[label];
          if (!group || group.total === 0) return null;
          return <section className="task-center-group" key={label}>
            <header><div><h3>{label}</h3><p>{copy.description}</p></div><Button variant="quiet" onClick={() => { setTaskCenterOpen(false); navigate(copy.section); }}>{copy.cta} <Icon name="arrowRight" size={14}/></Button></header>
            {group.items.slice(0, 4).map((item) => <button className="task-center-row" type="button" key={item.key} onClick={() => { setTaskCenterOpen(false); navigate(item.section as Section); }}>
              <span><strong>{item.title}</strong><small>{item.meta}</small></span><Badge tone={item.tone}>{item.badge}</Badge>
            </button>)}
            {group.total > 4 && <p className="task-center-hint">本范围共 {group.total} 项，这里显示最近 {Math.min(4, group.items.length)} 项；进入模块处理全部。</p>}
          </section>;
        })}
        {todoCount === 0 && <div className="task-center-empty">{todoError ? `待办加载失败：${todoError}。请关闭后重试。` : taskCenterLoading ? "正在按当前项目汇总待办…" : allTodoCount > 0 ? `当前范围没有待办；切到“全部”可查看其余 ${allTodoCount} 项。` : "当前没有需要人工处理的待办；监测、审核、发布、事实与知识库都已清空。"}</div>}
      </div>
    </DetailModal>}
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
