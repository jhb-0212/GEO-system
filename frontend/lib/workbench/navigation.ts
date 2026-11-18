import type { IconName } from "../../components/ui";
import type { Section } from "./types";
import type { NavScope } from "./visibility";

export interface NavItemConfig {
  id: Section;
  label: string;
  subtitle: string;
  icon: IconName;
  group: "workspace" | "system";
  scope: NavScope;
  permissions?: string[];
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
  publishing: { label: "内容发布", subtitle: "登记账号、建任务、回填回执与核实" },
  channels: { label: "渠道台账", subtitle: "管理渠道、域名与归属" },
  quotes: { label: "媒体报价", subtitle: "维护渠道报价、预算与审批状态" },
  budget: { label: "预算审批", subtitle: "开发工时、内容制作、媒体投放、监测服务的统一申请与审批" },
  statistics: { label: "统计看板", subtitle: "查看有效回答与品牌呈现" },
  metrics: { label: "指标口径", subtitle: "维护指标代码、计算公式与版本" },
  reviews: { label: "内容审核", subtitle: "处理待审核内容与证据复核" },
  leads: { label: "线索管理", subtitle: "整理咨询线索与跟进进度" },
  faq: { label: "FAQ 编辑", subtitle: "整理常见问题、答案与展示状态" },
  materials: { label: "素材管理", subtitle: "整理品牌图片、文档与案例素材" },
  activity: { label: "操作日志", subtitle: "查看关键操作与协作记录" },
  engines: { label: "AI 平台入口", subtitle: "查看平台目录，维护入口并测试连接" },
  members: { label: "成员管理", subtitle: "添加成员、调整角色与停用权限" },
  components: { label: "组件规范", subtitle: "工作台基础组件的统一样式" },
  profile: { label: "个人中心", subtitle: "查看当前账号信息、身份与访问权限" },
} satisfies Record<Section, { label: string; subtitle: string }>;

function buildSectionInfo(): Record<Section, { title: string; subtitle: string }> {
  const result = {} as Record<Section, { title: string; subtitle: string }>;
  (Object.keys(SECTION_META) as Section[]).forEach((id) => {
    result[id] = { title: SECTION_META[id].label, subtitle: SECTION_META[id].subtitle };
  });
  return result;
}

/** 页面标题/副标题：由 SECTION_META 派生，文案只有一份。 */
export const sectionInfo = buildSectionInfo();

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
  monitoring: { icon: "pulse", group: "workspace", scope: "project", permissions: ["monitoring.read"] },
  competitors: { icon: "pulse", group: "workspace", scope: "project", permissions: ["monitoring.read"] },
  brand: { icon: "blocks", group: "workspace", scope: "project", permissions: ["monitoring.read"] },
  diagnostics: { icon: "pulse", group: "system", scope: "project", permissions: ["monitoring.execute", "project.member.manage"], match: "any" },
  questions: { icon: "blocks", group: "workspace", scope: "project", permissions: ["question.read"] },
  samples: { icon: "check", group: "workspace", scope: "project", permissions: ["monitoring.read"] },
  plans: { icon: "calendar", group: "workspace", scope: "project", permissions: ["content.read"] },
  publishing: { icon: "layers", group: "workspace", scope: "project", permissions: ["publish.read"] },
  channels: { icon: "folder", group: "workspace", scope: "project", permissions: ["channel.read"] },
  quotes: { icon: "folder", group: "workspace", scope: "project", permissions: ["content.read"] },
  budget: { icon: "folder", group: "workspace", scope: "project", permissions: ["budget.read"] },
  statistics: { icon: "grid", group: "workspace", scope: "project", permissions: ["stats.read"] },
  metrics: { icon: "grid", group: "workspace", scope: "project", permissions: ["stats.read"] },
  reviews: { icon: "check", group: "workspace", scope: "project", permissions: ["content.read"] },
  leads: { icon: "users", group: "workspace", scope: "project", permissions: ["lead.read"] },
  faq: { icon: "blocks", group: "workspace", scope: "project", permissions: ["content.read"] },
  materials: { icon: "folder", group: "workspace", scope: "project", permissions: ["content.read"] },
  activity: { icon: "history", group: "system", scope: "project", permissions: ["audit.read"] },
  engines: { icon: "blocks", group: "system", scope: "global", permissions: ["engine.verify"] },
  members: { icon: "users", group: "system", scope: "project", permissions: ["project.member.manage"] },
  components: { icon: "blocks", group: "system", scope: "public" },
  profile: { icon: "user", group: "system", scope: "public" },
};

/** 导航项：由 NAV_LAYOUT 的键生成，文案取自 SECTION_META，两处都受 `Section` 全集约束。 */
export const navigation: NavItemConfig[] = (Object.keys(NAV_LAYOUT) as Section[]).map((id) => ({
  id,
  ...SECTION_META[id],
  ...NAV_LAYOUT[id],
}));
