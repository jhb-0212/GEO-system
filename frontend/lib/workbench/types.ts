export type Section =
  | "overview"
  | "projects"
  | "monitoring"
  | "reviews"
  | "leads"
  | "faq"
  | "materials"
  | "activity"
  | "components";

export type Tone = "blue" | "green" | "amber" | "red" | "slate";

export interface Project {
  id: string;
  code: string;
  name: string;
  owner: string;
  status: "运行中" | "筹备中";
  updatedAt: string;
  channels: number;
  tasks: number;
}

export interface MonitoringTask {
  id: string;
  question: string;
  engine: string;
  projectId: string;
  status: "进行中" | "待执行" | "已完成" | "需复核";
  progress: number;
  updatedAt: string;
}

export interface ReviewItem {
  id: string;
  title: string;
  type: string;
  projectId: string;
  author: string;
  submittedAt: string;
  status: "待审核" | "已通过" | "已驳回";
}

export interface Lead {
  id: string;
  contactName: string;
  phone: string;
  interest: string;
  source: string;
  projectId: string;
  status: "待跟进" | "跟进中" | "已转化";
  createdAt: string;
}

export interface FaqEntry {
  id: string;
  projectId: string;
  question: string;
  answer: string;
  status: "草稿" | "已上架" | "已下架";
  updatedAt: string;
}

export interface MaterialEntry {
  id: string;
  projectId: string;
  title: string;
  category: "图片" | "文档" | "案例";
  description: string;
  fileName: string;
  updatedAt: string;
}

export interface Activity {
  id: string;
  actor: string;
  action: string;
  target: string;
  time: string;
  tone: Tone;
}

export interface WorkbenchSnapshot {
  source: "mock" | "live";
  projects: Project[];
  tasks: MonitoringTask[];
  reviews: ReviewItem[];
  leads: Lead[];
  activities: Activity[];
  trend: number[];
  engines: { name: string; share: number; color: string }[];
}

export interface ApiEnvelope<T> {
  data: T;
  meta?: { page: number; page_size: number; total: number };
}

export interface ApiErrorEnvelope {
  error: { code: string; message: string };
}
