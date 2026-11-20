import type { IconName } from "../../components/ui";
import { PERMISSION, type PermissionCode } from "./permissions";
import type { Section } from "./types";
import type { NavScope } from "./visibility";

export interface NavItemConfig {
  id: Section;
  label: string;
  subtitle: string;
  icon: IconName;
  group: "workspace" | "system";
  scope: NavScope;
  permissions?: readonly PermissionCode[];
  match?: "any" | "all";
}

/**
 * 面板元数据唯一事实源：导航文案、页面标题、副标题都在这里，工作台不再另维护一份。
 *
 * `satisfies Record<Section, ...>` 是这里唯一的完整性保障：`Section` 新增成员而本表漏写
 * 时，tsc 会直接报「缺少属性」。此前用 `Object.fromEntries(...) as Record<Section, ...>`
 * 做向下断言，编译器不校验键集合，漏项会静默变成空标题——那个写法已经去掉。
 */
const SECTION_META = {
  overview: { label: "工作概览", subtitle: "掌握项目进展与值得关注的变化" },
  projects: { label: "项目管理", subtitle: "统一查看在管项目与运行状态" },
  monitoring: { label: "监测任务", subtitle: "追踪各引擎采样任务的执行进度" },
  competitors: { label: "竞品台账", subtitle: "维护竞品名单，用于提及归因与竞品份额" },
  brand: { label: "品牌口径", subtitle: "正式名、别名、唯一标识与自有域名：决定品牌怎么被识别" },
  diagnostics: { label: "内部排障", subtitle: "集中查看失败样本、失败码、重试与 trace" },
  questions: { label: "题库与目标词", subtitle: "管理监测问题、版本与目标词" },
  samples: { label: "样本与引用", subtitle: "回看回答、复核样本和引用归属" },
  plans: { label: "内容计划", subtitle: "排期选题、生产与发布节奏" },
  opportunities: { label: "机会中心", subtitle: "把引用缺口与事实纠错变成可指派任务" },
  "site-diagnostics": { label: "官网诊断", subtitle: "检查官网可爬取性、AI 爬虫访问与引用缺口" },
  publishing: { label: "内容发布", subtitle: "登记账号、安排发布、记录结果" },
  channels: { label: "渠道台账", subtitle: "管理渠道、域名与归属" },
  quotes: { label: "媒体报价", subtitle: "维护渠道报价、预算与审批状态" },
  budget: { label: "预算审批", subtitle: "开发工时、内容制作、媒体投放、监测服务的统一申请与审批" },
  statistics: { label: "统计看板", subtitle: "查看有效回答与品牌呈现" },
  monthly: { label: "月度报告", subtitle: "按月汇总任务、回答与发布结案" },
  metrics: { label: "指标口径", subtitle: "维护指标代码、计算公式与版本" },
  facts: { label: "事实库与核验", subtitle: "维护 12 类权威事实、审批版本，并核验 AI 回答说对了没有" },
  reviews: { label: "内容审核", subtitle: "处理待审核内容与证据复核" },
  leads: { label: "线索管理", subtitle: "整理咨询线索与跟进进度" },
  funnel: { label: "线索漏斗", subtitle: "查看线索各阶段转化与来源归因" },
  faq: { label: "FAQ 编辑", subtitle: "整理常见问题、答案与展示状态" },
  materials: { label: "素材管理", subtitle: "整理品牌图片、文档与案例素材" },
  activity: { label: "操作日志", subtitle: "查看关键操作与协作记录" },
  engines: { label: "AI 平台入口", subtitle: "查看平台目录，维护入口并测试连接" },
  members: { label: "成员管理", subtitle: "添加成员、调整角色与停用权限" },
  profile: { label: "个人中心", subtitle: "查看当前账号信息、身份与访问权限" },
} satisfies Record<Section, { label: string; subtitle: string }>;

/**
 * 页面标题/副标题：按 id 直接从 SECTION_META 取，文案只有一份。
 *
 * 不做“先建空 Record 再逐项填”的构造，也不需要类型断言：SECTION_META 已被
 * `satisfies Record<Section, ...>` 钉死为全集，传入的 id 受 `Section` 约束。
 */
export function getSectionInfo(id: Section): { title: string; subtitle: string } {
  return { title: SECTION_META[id].label, subtitle: SECTION_META[id].subtitle };
}

/**
 * 导航布局：只放「id 之外」的结构配置（图标、分组、可见范围、权限），文案仍取自 SECTION_META。
 *
 * 这里必须是 `Record<Section, ...>` 而不是数组：数组的长度不受 `Section` 约束，
 * 新增面板时漏加一项，tsc 不会报错——运行结果就是「URL 能进、侧边栏没有这一项」。
 * 实测确认过这个静默缺口，所以改成键集合被编译器钉死的写法；对象键顺序决定导航顺序。
 */
const NAV_LAYOUT: Record<Section, Omit<NavItemConfig, "id" | "label" | "subtitle">> = {
  overview: { icon: "grid", group: "workspace", scope: "public" },
  projects: { icon: "layers", group: "workspace", scope: "public" },
  monitoring: { icon: "pulse", group: "workspace", scope: "project", permissions: [PERMISSION.MONITORING_READ] },
  competitors: { icon: "pulse", group: "workspace", scope: "project", permissions: [PERMISSION.MONITORING_READ] },
  brand: { icon: "blocks", group: "workspace", scope: "project", permissions: [PERMISSION.MONITORING_READ] },
  diagnostics: { icon: "pulse", group: "system", scope: "project", permissions: [PERMISSION.MONITORING_EXECUTE, PERMISSION.PROJECT_MEMBER_MANAGE], match: "any" },
  questions: { icon: "blocks", group: "workspace", scope: "project", permissions: [PERMISSION.QUESTION_READ] },
  samples: { icon: "check", group: "workspace", scope: "project", permissions: [PERMISSION.MONITORING_READ] },
  plans: { icon: "calendar", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  opportunities: { icon: "spark", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  "site-diagnostics": { icon: "search", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  publishing: { icon: "layers", group: "workspace", scope: "project", permissions: [PERMISSION.PUBLISH_READ] },
  channels: { icon: "folder", group: "workspace", scope: "project", permissions: [PERMISSION.CHANNEL_READ] },
  quotes: { icon: "folder", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  budget: { icon: "folder", group: "workspace", scope: "project", permissions: [PERMISSION.BUDGET_READ] },
  statistics: { icon: "grid", group: "workspace", scope: "project", permissions: [PERMISSION.STATS_READ] },
  monthly: { icon: "history", group: "workspace", scope: "project", permissions: [PERMISSION.STATS_READ] },
  metrics: { icon: "grid", group: "workspace", scope: "project", permissions: [PERMISSION.STATS_READ] },
  facts: { icon: "check", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  reviews: { icon: "check", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  leads: { icon: "users", group: "workspace", scope: "project", permissions: [PERMISSION.LEAD_READ] },
  funnel: { icon: "filter", group: "workspace", scope: "project", permissions: [PERMISSION.LEAD_READ] },
  faq: { icon: "blocks", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  materials: { icon: "folder", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  activity: { icon: "history", group: "system", scope: "project", permissions: [PERMISSION.AUDIT_READ] },
  engines: { icon: "blocks", group: "system", scope: "global", permissions: [PERMISSION.ENGINE_VERIFY] },
  members: { icon: "users", group: "system", scope: "project", permissions: [PERMISSION.PROJECT_MEMBER_MANAGE] },
  profile: { icon: "user", group: "system", scope: "public" },
};

/** 配置、专业分析与管理员页面：收进“配置与管理”，不混在运营人员的日常导航里。 */
export const ADVANCED_SECTIONS: readonly Section[] = [
  "projects",
  "brand",
  "questions",
  "samples",
  "opportunities",
  "site-diagnostics",
  "metrics",
  "facts",
  "diagnostics",
  "monthly",
  "funnel",
  "faq",
  "materials",
  "budget",
  "quotes",
  "activity",
  "engines",
  "members",
  "profile",
];

/** 运营人员日常导航的顺序：先审核与发布，再监测和数据；低频配置进「配置与管理」。 */
export const CORE_NAV_ORDER: readonly Section[] = [
  "overview",
  "reviews",
  "publishing",
  "monitoring",
  "channels",
  "plans",
  "competitors",
  "statistics",
  "leads",
];

/** 导航项：由 NAV_LAYOUT 的键生成，文案取自 SECTION_META，两处都受 `Section` 全集约束。 */
export const navigation: NavItemConfig[] = (Object.keys(NAV_LAYOUT) as Section[]).map((id) => ({
  id,
  ...SECTION_META[id],
  ...NAV_LAYOUT[id],
}));
