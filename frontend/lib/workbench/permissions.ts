/**
 * 权限码常量：与后端 `backend/app/core/permissions.py::PERMISSION_CATALOG` 对齐。
 *
 * 权限码是前后端共同契约。前端如果继续写裸字符串，拼错一个字母 tsc 不会报错，
 * 对应面板会对所有非系统管理员**静默消失**，线上也没有任何信号。这里把码收敛成
 * 字面量联合类型：`NavItemConfig.permissions` 只接受 `PermissionCode`，写错即编译失败。
 *
 * 后端新增能力码时，本表同步补一行；后端 API 侧的裸码由
 * `backend/tests/test_permission_codes.py` 做目录一致性校验。
 */
export const PERMISSION = {
  PROJECT_CREATE: "project.create",
  ENGINE_MANAGE: "engine.manage",
  ENGINE_VERIFY: "engine.verify",
  PROJECT_MEMBER_MANAGE: "project.member.manage",
  PROJECT_READ: "project.read",
  QUESTION_READ: "question.read",
  QUESTION_WRITE: "question.write",
  MONITORING_READ: "monitoring.read",
  MONITORING_EXECUTE: "monitoring.execute",
  EVIDENCE_READ: "evidence.read",
  EVIDENCE_REVIEW: "evidence.review",
  CONTENT_READ: "content.read",
  CONTENT_WRITE: "content.write",
  CONTENT_REVIEW: "content.review",
  PUBLISH_READ: "publish.read",
  PUBLISH_EXECUTE: "publish.execute",
  CHANNEL_READ: "channel.read",
  CHANNEL_WRITE: "channel.write",
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
