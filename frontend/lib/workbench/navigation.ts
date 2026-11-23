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
  brand: { label: "品牌设置", subtitle: "维护品牌正式名、别名和官网域名，决定系统如何识别品牌" },
  diagnostics: { label: "问题排查", subtitle: "查看失败记录和原因，重试任务并定位问题" },
  questions: { label: "监测问题与关键词", subtitle: "管理监测问题、问题版本和目标关键词" },
  samples: { label: "样本与引用", subtitle: "回看回答、复核样本和引用归属" },
  plans: { label: "内容计划", subtitle: "排期选题、生产与发布节奏" },
  opportunities: { label: "机会中心", subtitle: "把引用缺口与事实纠错变成可指派任务" },
  "site-diagnostics": { label: "官网检查", subtitle: "检查官网能否被抓取、AI 能否访问，以及引用缺口" },
  publishing: { label: "内容发布", subtitle: "登记账号、安排发布、记录结果" },
  channels: { label: "渠道台账", subtitle: "管理渠道、域名与归属" },
  quotes: { label: "媒体报价", subtitle: "维护渠道报价、预算与审批状态" },
  budget: { label: "预算审批", subtitle: "开发工时、内容制作、媒体投放、监测服务的统一申请与审批" },
  statistics: { label: "统计看板", subtitle: "查看有效回答与品牌呈现" },
  monthly: { label: "月度报告", subtitle: "按月汇总任务、回答与发布结案" },
  metrics: { label: "指标定义", subtitle: "维护指标名称、算法说明和版本" },
  facts: { label: "事实库与核验", subtitle: "维护权威事实和审批版本，核验 AI 回答是否正确" },
  reviews: { label: "内容审核", subtitle: "处理待审核内容与证据复核" },
  leads: { label: "线索管理", subtitle: "整理咨询线索与跟进进度" },
  funnel: { label: "线索漏斗", subtitle: "查看线索各阶段转化与来源归因" },
  faq: { label: "FAQ 编辑", subtitle: "整理常见问题、答案与展示状态" },
  materials: { label: "素材管理", subtitle: "整理品牌图片、文档与案例素材" },
  activity: { label: "操作日志", subtitle: "查看关键操作与协作记录" },
  engines: { label: "AI 平台入口", subtitle: "查看平台目录，维护入口并测试连接" },
  members: { label: "成员管理", subtitle: "添加成员、调整角色与停用权限" },
  profile: { label: "个人中心", subtitle: "查看当前账号信息、身份与访问权限" },
  company: { label: "企业档案", subtitle: "公司主体、业务与对外口径的唯一结构化来源" },
  "basic-info": { label: "基础信息", subtitle: "对外联系人资料与项目资质，含到期提醒" },
  "feed-access": { label: "投喂与授权", subtitle: "核对投喂材料是否齐备，查看平台授权与授权案例" },
  report: { label: "诊断报告", subtitle: "五个分项的分子与分母，只给数字不给评级" },
  sentiment: { label: "情绪原文", subtitle: "正/中/负三档计数与按可信度排序的原文" },
  board: { label: "发布回链", subtitle: "回执链接 → 能否被检索到 → 是否已被 AI 引用" },
  closure: { label: "发布闭环", subtitle: "以任务为轴，看链路断在回执、收录还是引用" },
  distribution: { label: "投喂批次", subtitle: "把一批已审核内容指向平台，先过五项预检" },
  factory: { label: "内容工厂", subtitle: "按渠道与题型沉淀骨架模板，只填槽位就能出草稿" },
  adaptation: { label: "渠道改编", subtitle: "母稿派生渠道稿，按渠道约束检查并追踪是否跟版" },
  site: { label: "微站", subtitle: "六个内容模块的对外小站，发布后走 /s/{slug}" },
  dash: { label: "双轨大屏", subtitle: "投放侧与测量侧分开看，不合成总分" },
  health: { label: "体检", subtitle: "12 项逐项达成率，只看哪一项没做，不给总分" },
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
  company: { icon: "blocks", group: "workspace", scope: "project", permissions: [PERMISSION.MONITORING_READ] },
  "basic-info": { icon: "check", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  "feed-access": { icon: "upload", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  report: { icon: "grid", group: "workspace", scope: "project", permissions: [PERMISSION.STATS_READ] },
  sentiment: { icon: "spark", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  board: { icon: "external", group: "workspace", scope: "project", permissions: [PERMISSION.PUBLISH_READ] },
  closure: { icon: "history", group: "workspace", scope: "project", permissions: [PERMISSION.PUBLISH_READ] },
  distribution: { icon: "upload", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  factory: { icon: "spark", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  adaptation: { icon: "layers", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  site: { icon: "blocks", group: "workspace", scope: "project", permissions: [PERMISSION.CONTENT_READ] },
  dash: { icon: "pulse", group: "workspace", scope: "project", permissions: [PERMISSION.STATS_READ] },
  health: { icon: "check", group: "workspace", scope: "project", permissions: [PERMISSION.STATS_READ] },
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

export interface AdvancedNavGroup {
  label: string;
  sections: readonly Section[];
}

/**
 * 低频功能按“用户来做什么”分组，而不是把 19 项平铺成一长列。
 * 这里列出的 sections 合起来必须覆盖所有需要收进「配置与管理」的页面。
 */
export const ADVANCED_NAV_GROUPS: readonly AdvancedNavGroup[] = [
  {
    label: "监测与项目设置",
    sections: ["projects", "brand", "questions", "samples", "diagnostics", "engines"],
  },
  {
    label: "内容与事实核验",
    sections: ["opportunities", "site-diagnostics", "facts", "faq", "materials"],
  },
  {
    label: "预算与统计",
    sections: ["quotes", "budget", "metrics", "monthly", "funnel"],
  },
  {
    label: "账号与协作",
    sections: ["activity", "members", "profile"],
  },
];

/** 配置、专业分析与管理员页面：收进“配置与管理”，不混在运营人员的日常导航里。 */
export const ADVANCED_SECTIONS: readonly Section[] = ADVANCED_NAV_GROUPS.flatMap((group) => group.sections);

/** 运营人员日常导航的顺序：先审核与发布，再监测和数据；低频配置进「配置与管理」。 */
export const CORE_NAV_ORDER: readonly Section[] = [
  "overview",
  "reviews",
  "publishing",
  "monitoring",
  "company",
  "basic-info",
  "feed-access",
  "report",
  "sentiment",
  "board",
  "closure",
  "distribution",
  "factory",
  "adaptation",
  "site",
  "dash",
  "health",
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
