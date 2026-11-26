import type { Lead, ReviewItem, WorkbenchSnapshot } from "./types";

const projects: WorkbenchSnapshot["projects"] = [
  { id: "p-demo", code: "demo-project", name: "示例项目 GEO", owner: "林策", priority: 1, businessConfirmedAt: "2026-11-10", businessConfirmedBy: "林策", status: "运行中", updatedAt: "今天 09:24", channels: 39, tasks: 24 },
  { id: "p-north", code: "north-star", name: "北辰教育品牌", owner: "周欣", priority: 2, businessConfirmedAt: "2026-11-08", businessConfirmedBy: "周欣", status: "运行中", updatedAt: "昨天 17:40", channels: 18, tasks: 16 },
  { id: "p-harbor", code: "harbor", name: "海港新媒体计划", owner: "陈舟", priority: 3, businessConfirmedAt: null, businessConfirmedBy: null, status: "筹备中", updatedAt: "11 月 08 日", channels: 12, tasks: 8 },
];

const tasks: WorkbenchSnapshot["tasks"] = [
  { id: "MON-2411", serialNo: "2411", question: "广州少儿英语培训机构推荐", engine: "豆包", projectId: "p-demo", status: "进行中", progress: 68, updatedAt: "5 分钟前" },
  { id: "MON-2410", serialNo: "2410", question: "广州雅思培训怎么选", engine: "DeepSeek", projectId: "p-demo", status: "需复核", progress: 100, updatedAt: "18 分钟前", enteredTodoAt: "2026-11-26T04:42:00.000Z" },
  { id: "MON-2409", serialNo: "2409", question: "适合职场人的英语课程", engine: "通义千问", projectId: "p-north", status: "已完成", progress: 100, updatedAt: "45 分钟前" },
  { id: "MON-2408", serialNo: "2408", question: "广州英语培训费用对比", engine: "文心一言", projectId: "p-demo", status: "待执行", progress: 0, updatedAt: "今天 08:52" },
  { id: "MON-2407", serialNo: "2407", question: "职业技能课程报名渠道", engine: "豆包", projectId: "p-harbor", status: "已完成", progress: 100, updatedAt: "昨天 16:32" },
];

let reviews: ReviewItem[] = [
  { id: "REV-028", title: "示例项目品牌介绍 · 2026 秋季版", type: "内容版本", projectId: "p-demo", author: "王语", submittedAt: "今天 09:16", enteredTodoAt: "2026-11-26T01:16:00.000Z", status: "待审核" },
  { id: "REV-027", title: "少儿英语课程常见问题", type: "内容版本", projectId: "p-demo", author: "周欣", submittedAt: "今天 08:48", enteredTodoAt: "2026-11-26T00:48:00.000Z", status: "待审核" },
  { id: "REV-026", title: "品牌来源识别复核", type: "监测证据", projectId: "p-north", author: "陈舟", submittedAt: "昨天 17:31", enteredTodoAt: "2026-11-25T09:31:00.000Z", status: "待审核" },
  { id: "REV-025", title: "年度课程白皮书摘要", type: "内容版本", projectId: "p-demo", author: "王语", submittedAt: "昨天 15:08", status: "已通过" },
];

let leads: Lead[] = [
  { id: "LD-1042", serialNo: "1042", contactName: "张女士", phone: "138****2041", interest: "少儿英语", source: "官网表单", projectId: "p-demo", status: "待跟进", createdAt: "今天 10:12" },
  { id: "LD-1041", serialNo: "1041", contactName: "李先生", phone: "139****7683", interest: "雅思培训", source: "公众号", projectId: "p-demo", status: "跟进中", createdAt: "今天 09:48" },
  { id: "LD-1040", serialNo: "1040", contactName: "陈女士", phone: "136****9512", interest: "职场英语", source: "自然搜索", projectId: "p-north", status: "已转化", createdAt: "昨天 16:20" },
  { id: "LD-1039", serialNo: "1039", contactName: "王先生", phone: "137****3308", interest: "少儿英语", source: "官网表单", projectId: "p-demo", status: "待跟进", createdAt: "昨天 14:35" },
  { id: "LD-1038", serialNo: "1038", contactName: "林女士", phone: "135****6842", interest: "职业技能", source: "活动页面", projectId: "p-harbor", status: "跟进中", createdAt: "11 月 09 日" },
];

const activities: WorkbenchSnapshot["activities"] = [
  { id: "a1", actor: "王语", action: "提交内容审核", target: "示例项目品牌介绍", time: "09:16", tone: "blue" },
  { id: "a2", actor: "系统", action: "完成监测任务", target: "MON-2409", time: "08:42", tone: "green" },
  { id: "a3", actor: "林策", action: "导出渠道数据", target: "示例项目 GEO", time: "昨天 17:20", tone: "amber" },
  { id: "a4", actor: "陈舟", action: "更新项目成员", target: "北辰教育品牌", time: "昨天 15:04", tone: "slate" },
];

export function getMockSnapshot(): WorkbenchSnapshot {
  return {
    source: "mock",
    leadAccess: "allowed",
    projects,
    tasks,
    reviews,
    leads,
    activities,
    trend: [44, 51, 48, 62, 58, 66, 71, 69, 77, 74, 83, 86],
    engines: [
      { name: "豆包", share: 38, color: "#326af4" },
      { name: "DeepSeek", share: 27, color: "#55a7e8" },
      { name: "通义千问", share: 21, color: "#71c5bb" },
      { name: "文心一言", share: 14, color: "#e2b36e" },
    ],
  };
}

export function addMockLead(input: Pick<Lead, "contactName" | "phone" | "interest" | "source" | "projectId" | "reportedAiProduct" | "isValid">): Lead {
  const lead: Lead = {
    ...input,
    id: `LD-${1043 + Math.max(0, leads.length - 5)}`,
    status: "待跟进",
    createdAt: "刚刚",
  };
  leads = [lead, ...leads];
  return lead;
}

export function updateMockReview(id: string, status: "已通过" | "已驳回"): ReviewItem | null {
  const review = reviews.find((item) => item.id === id);
  if (!review) return null;
  reviews = reviews.map((item) => item.id === id ? { ...item, status } : item);
  return { ...review, status };
}
