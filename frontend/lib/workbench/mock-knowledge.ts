import type { FaqEntry, MaterialEntry } from "./types";

// These records are only used by the browser-side workbench demonstration.
export const demoFaqs: FaqEntry[] = [
  { id: "FAQ-001", projectId: "p-demo", question: "少儿英语课程适合几岁的孩子？", answer: "演示答案：课程按年龄与基础分组，具体安排以正式发布内容为准。", status: "已上架", updatedAt: "今天 09:30" },
  { id: "FAQ-002", projectId: "p-demo", question: "示例项目可以预约试听吗？", answer: "演示答案：可通过咨询入口了解试听安排。", status: "草稿", updatedAt: "今天 08:45" },
  { id: "FAQ-003", projectId: "p-north", question: "职场英语课程支持线上学习吗？", answer: "演示答案：授课方式需以正式课程说明为准。", status: "已下架", updatedAt: "昨天 16:20" },
];

export const demoMaterials: MaterialEntry[] = [
  { id: "MAT-001", projectId: "p-demo", title: "品牌介绍封面", category: "图片", description: "用于课程介绍页的视觉素材（演示记录）", fileName: "brand-cover.png", updatedAt: "今天 10:05" },
  { id: "MAT-002", projectId: "p-demo", title: "课程常见问题整理", category: "文档", description: "客服与编辑共用的参考资料（演示记录）", fileName: "course-faq.pdf", updatedAt: "昨天 14:32" },
  { id: "MAT-003", projectId: "p-north", title: "职场英语案例摘要", category: "案例", description: "公开案例素材的待核对摘要（演示记录）", fileName: "case-summary.docx", updatedAt: "11 月 09 日" },
];
