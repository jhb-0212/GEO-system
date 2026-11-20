/** 工作台通用的时间展示：后端给 ISO 串，页面统一成本地时间，固定 YYYY-MM-DD HH:mm。 */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 只保留日期部分；统一 YYYY-MM-DD。 */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** 统一成 YYYY-MM-DD，供趋势横轴等需要稳定格式的位置使用。 */
export function formatIsoDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** 业务序号统一三位起：1 → 001，1000 → 1000。 */
export function formatSerialNo(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value < 1) return "—";
  return String(Math.floor(value)).padStart(3, "0");
}

/** 审计对象只展示业务类型，不把 UUID 直接露给运营。 */
const AUDIT_TARGET_LABELS: Record<string, string> = {
  budget_approval: "预算申请",
  channel: "渠道",
  channels: "渠道导出",
  citation: "引用",
  citations: "引用导出",
  competitor: "竞品",
  content_item: "内容",
  content_version: "内容版本",
  engine: "AI 平台",
  fact: "事实",
  faq: "FAQ",
  keyword: "目标词",
  lead: "线索",
  material: "素材",
  member: "成员",
  metric: "指标",
  monitoring_task: "监测任务",
  oauth_connection: "平台授权",
  permission: "权限",
  project: "项目",
  publish_account: "发布账号",
  publish_task: "发布任务",
  question: "题目",
  quote: "报价",
  sample: "样本",
  site_page: "站点页面",
  user: "成员",
};

export function formatAuditTarget(targetType: string | null | undefined): string {
  if (!targetType) return "系统";
  return AUDIT_TARGET_LABELS[targetType] ?? targetType;
}

/** 审计动作统一成“动词 + 业务对象”，不把 competitor.delete 这类内部编码露给运营。 */
const AUDIT_VERB_LABELS: Record<string, string> = {
  approve: "通过", archive: "归档", create: "新增", delete: "删除", disable: "停用",
  download: "下载", enable: "启用", login: "登录", publish: "发布", reject: "驳回",
  restore: "恢复", review: "审核", submit: "提交", test: "测试", update: "修改",
  upload: "上传", verify: "核验",
};

export function formatAuditAction(action: string | null | undefined): string {
  if (!action) return "操作记录";
  const [objectType, verb] = action.split(".");
  const objectLabel = AUDIT_TARGET_LABELS[objectType];
  const verbLabel = AUDIT_VERB_LABELS[verb];
  if (objectLabel && verbLabel) return `${verbLabel}${objectLabel}`;
  if (verbLabel) return verbLabel;
  return "操作记录";
}

/** 人员名称只保留业务称呼，隐藏 seed、API 适配器等实现备注。 */
export function formatPersonName(value: string | null | undefined): string {
  return (value ?? "").replace(/\s*[（(][^（）()]*(?:seed|API|人工发布)[^（）()]*[）)]/gi, "").trim();
}
