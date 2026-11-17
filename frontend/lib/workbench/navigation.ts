import type { IconName } from "../../components/ui";
import type { Section } from "./types";
import type { NavScope } from "./visibility";

export interface NavItemConfig {
  id: Section;
  label: string;
  icon: IconName;
  group: "workspace" | "system";
  scope: NavScope;
  permissions?: string[];
  match?: "any" | "all";
}

export const navigation: NavItemConfig[] = [
  { id: "overview", label: "工作概览", icon: "grid", group: "workspace", scope: "public" },
  { id: "projects", label: "项目管理", icon: "layers", group: "workspace", scope: "public" },
  { id: "monitoring", label: "监测任务", icon: "pulse", group: "workspace", scope: "project", permissions: ["monitoring.read"] },
  { id: "competitors", label: "竞品台账", icon: "pulse", group: "workspace", scope: "project", permissions: ["monitoring.read"] },
  { id: "brand", label: "品牌口径", icon: "blocks", group: "workspace", scope: "project", permissions: ["monitoring.read"] },
  { id: "diagnostics", label: "内部排障", icon: "pulse", group: "system", scope: "project", permissions: ["monitoring.execute", "project.member.manage"], match: "any" },
  { id: "questions", label: "题库与目标词", icon: "blocks", group: "workspace", scope: "project", permissions: ["question.read"] },
  { id: "samples", label: "样本与引用", icon: "check", group: "workspace", scope: "project", permissions: ["monitoring.read"] },
  { id: "plans", label: "内容计划", icon: "calendar", group: "workspace", scope: "project", permissions: ["content.read"] },
  { id: "publishing", label: "内容发布", icon: "layers", group: "workspace", scope: "project", permissions: ["publish.read"] },
  { id: "channels", label: "渠道台账", icon: "folder", group: "workspace", scope: "project", permissions: ["channel.read"] },
  { id: "quotes", label: "媒体报价", icon: "folder", group: "workspace", scope: "project", permissions: ["content.read"] },
  { id: "budget", label: "预算审批", icon: "folder", group: "workspace", scope: "project", permissions: ["budget.read"] },
  { id: "statistics", label: "统计看板", icon: "grid", group: "workspace", scope: "project", permissions: ["stats.read"] },
  { id: "metrics", label: "指标口径", icon: "grid", group: "workspace", scope: "project", permissions: ["stats.read"] },
  { id: "reviews", label: "内容审核", icon: "check", group: "workspace", scope: "project", permissions: ["content.read"] },
  { id: "leads", label: "线索管理", icon: "users", group: "workspace", scope: "project", permissions: ["lead.read"] },
  { id: "faq", label: "FAQ 编辑", icon: "blocks", group: "workspace", scope: "project", permissions: ["content.read"] },
  { id: "materials", label: "素材管理", icon: "folder", group: "workspace", scope: "project", permissions: ["content.read"] },
  { id: "activity", label: "操作日志", icon: "history", group: "system", scope: "project", permissions: ["audit.read"] },
  { id: "engines", label: "AI 平台入口", icon: "blocks", group: "system", scope: "global", permissions: ["engine.verify"] },
  { id: "members", label: "成员管理", icon: "users", group: "system", scope: "project", permissions: ["project.member.manage"] },
  { id: "components", label: "组件规范", icon: "blocks", group: "system", scope: "public" },
];
