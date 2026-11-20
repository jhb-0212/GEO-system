/**
 * 权限码契约与展示层目录。
 *
 * 与后端 `backend/app/core/permissions.py::PERMISSION_CATALOG` 对齐，分两部分：
 *
 * 1. `PERMISSION` 常量与 `PermissionCode` 类型：前后端共同契约。前端如果继续写裸字符串，
 *    拼错一个字母 tsc 不会报错，对应面板会对所有非系统管理员**静默消失**。这里把码收敛成
 *    字面量联合类型：`NavItemConfig.permissions` 只接受 `PermissionCode`，写错即编译失败。
 *    后端新增能力码时，本表同步补一行；后端 API 侧的裸码由
 *    `backend/tests/test_permission_codes.py` 做目录一致性校验。
 *
 * 2. 展示层映射：能力码 → 中文名 / 业务分组，仅供个人中心等页面把 code 翻成可读名称，
 *    不参与任何权限校验。
 */

export const PERMISSION = {
  PROJECT_CREATE: "project.create",
  ENGINE_MANAGE: "engine.manage",
  ENGINE_VERIFY: "engine.verify",
  PROJECT_MEMBER_MANAGE: "project.member.manage",
  PROJECT_CONFIRM: "project.confirm",
  PROJECT_READ: "project.read",
  QUESTION_READ: "question.read",
  QUESTION_WRITE: "question.write",
  MONITORING_READ: "monitoring.read",
  MONITORING_EXECUTE: "monitoring.execute",
  MONITORING_CANCEL: "monitoring.cancel",
  EVIDENCE_READ: "evidence.read",
  EVIDENCE_REVIEW: "evidence.review",
  CONTENT_READ: "content.read",
  CONTENT_WRITE: "content.write",
  CONTENT_REVIEW: "content.review",
  PUBLISH_READ: "publish.read",
  PUBLISH_EXECUTE: "publish.execute",
  PUBLISH_CANCEL: "publish.cancel",
  PUBLISH_ACCOUNT_DELETE: "publish.account_delete",
  CHANNEL_READ: "channel.read",
  CHANNEL_WRITE: "channel.write",
  CHANNEL_APPROVE: "channel.approve",
  COMPETITOR_WRITE: "competitor.write",
  BRAND_MANAGE: "brand.manage",
  LEAD_READ: "lead.read",
  LEAD_WRITE: "lead.write",
  STATS_READ: "stats.read",
  BUDGET_READ: "budget.read",
  BUDGET_WRITE: "budget.write",
  BUDGET_APPROVE: "budget.approve",
  METRIC_MANAGE: "metric.manage",
  EXPORT_DATA: "export.data",
  AUDIT_READ: "audit.read",
} as const;

export type PermissionCode = (typeof PERMISSION)[keyof typeof PERMISSION];

// ---- 展示层：能力码 → 中文名 / 业务分组（仅用于页面展示，不参与校验）----

export interface PermissionMeta {
  name: string;
  group: string;
}

/** 分组展示顺序；未收录的 code 落到「其他」。 */
export const PERMISSION_GROUPS = [
  "系统管理",
  "项目与成员",
  "题库与内容",
  "监测与证据",
  "渠道与竞品",
  "品牌与线索",
  "预算与指标",
  "数据与审计",
] as const;

const PERMISSION_META: Record<string, PermissionMeta> = {
  // 系统级
  "project.create": { name: "创建项目", group: "系统管理" },
  "engine.manage": { name: "维护引擎目录", group: "系统管理" },
  // 项目与成员
  "project.confirm": { name: "确认项目资料", group: "项目与成员" },
  "project.read": { name: "查看项目", group: "项目与成员" },
  "project.member.manage": { name: "管理项目成员", group: "项目与成员" },
  // 题库与内容
  "question.read": { name: "查看题库", group: "题库与内容" },
  "question.write": { name: "维护题库", group: "题库与内容" },
  "content.read": { name: "查看内容", group: "题库与内容" },
  "content.write": { name: "编辑内容正文", group: "题库与内容" },
  "content.review": { name: "审核签发", group: "题库与内容" },
  "publish.read": { name: "查看发布任务", group: "题库与内容" },
  "publish.execute": { name: "执行发布", group: "题库与内容" },
  "publish.cancel": { name: "取消发布任务", group: "题库与内容" },
  "publish.account_delete": { name: "删除发布账号", group: "题库与内容" },
  // 监测与证据
  "monitoring.read": { name: "查看监测数据", group: "监测与证据" },
  "monitoring.execute": { name: "触发采样执行", group: "监测与证据" },
  "monitoring.cancel": { name: "作废监测任务", group: "监测与证据" },
  "evidence.read": { name: "查看证据文件", group: "监测与证据" },
  "evidence.review": { name: "证据人工复核", group: "监测与证据" },
  "engine.verify": { name: "核验引擎入口", group: "监测与证据" },
  // 渠道与竞品
  "channel.read": { name: "查看渠道台账", group: "渠道与竞品" },
  "channel.write": { name: "维护渠道台账", group: "渠道与竞品" },
  "channel.approve": { name: "审批渠道准入", group: "渠道与竞品" },
  "competitor.write": { name: "维护竞品台账", group: "渠道与竞品" },
  // 品牌与线索
  "brand.manage": { name: "维护品牌口径", group: "品牌与线索" },
  "lead.read": { name: "查看线索", group: "品牌与线索" },
  "lead.write": { name: "维护线索", group: "品牌与线索" },
  // 预算与指标
  "stats.read": { name: "查看统计看板", group: "预算与指标" },
  "budget.read": { name: "查看预算审批", group: "预算与指标" },
  "budget.write": { name: "提交预算申请", group: "预算与指标" },
  "budget.approve": { name: "审批预算", group: "预算与指标" },
  "metric.manage": { name: "维护指标口径", group: "预算与指标" },
  // 数据与审计
  "export.data": { name: "导出数据", group: "数据与审计" },
  "audit.read": { name: "查看审计日志", group: "数据与审计" },
};

/** 未在目录内的能力码兜底显示原码，避免页面出现空白。 */
export function describePermission(code: string): PermissionMeta {
  return PERMISSION_META[code] ?? { name: code, group: "其他" };
}

export interface PermissionGroup {
  group: string;
  items: { code: string; name: string }[];
}

/** 把能力码按业务域聚合成有序分组，空分组不输出。 */
export function groupPermissions(codes: string[]): PermissionGroup[] {
  const order = [...PERMISSION_GROUPS, "其他"];
  const buckets = new Map<string, { code: string; name: string }[]>();
  for (const code of codes) {
    const meta = describePermission(code);
    const list = buckets.get(meta.group) ?? [];
    list.push({ code, name: meta.name });
    buckets.set(meta.group, list);
  }
  return order
    .filter((group) => buckets.has(group))
    .map((group) => ({ group, items: buckets.get(group) ?? [] }));
}

/** 项目角色码 → 中文名，与后端 `RoleCode` 对齐。 */
export const ROLE_LABELS: Record<string, string> = {
  sys_admin: "系统管理员",
  project_admin: "项目管理员",
  editor: "运营编辑",
  reviewer: "审核",
  viewer: "只读",
  lead_ops: "招生客服",
};

export function describeRole(roleCode: string | undefined, isSystemAdmin: boolean): string {
  if (isSystemAdmin) return "系统管理员";
  return (roleCode && ROLE_LABELS[roleCode]) || "普通成员";
}
