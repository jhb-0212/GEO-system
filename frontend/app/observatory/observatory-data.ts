export type AnswerStatus = "带链接" | "只提到" | "链接失效" | "没提到";
export type AnswerFlag = "ok" | "review" | "gap";

export interface ObservatoryQuestion {
  id: string;
  question: string;
  scene: string;
  engine: string;
  attempts: number;
  mentions: number;
  links: number;
  status: AnswerStatus;
  flag: AnswerFlag;
}

export interface ObservatoryMention {
  id: string;
  question: string;
  engine: string;
  status: AnswerStatus;
  links: number;
  when?: string;
}

export interface ObservatoryRange {
  days: number;
  dates: string[];
  mentions: number[];
  links: number[];
  label: string;
  peakLabel: string;
  peakSource: string;
}

export interface ObservatorySource {
  name: string;
  share: number;
  citations: number;
}

export interface ObservatoryEngine {
  name: string;
  count: number;
}

export interface ObservatoryAction {
  no: string;
  title: string;
  note: string;
  section: string;
}

export interface ObservatoryData {
  mode: "live" | "demo" | "fallback";
  projectName: string;
  projectId: string;
  userName: string;
  canWriteQuestion: boolean;
  canWriteContent: boolean;
  updatedAt: string;
  dateLabel: string;
  totalAnswers: number;
  brandAnswers: number;
  mentionedAnswers: number;
  citedAnswers: number;
  mentionRate: number;
  citeRate: number;
  competitorTogether: number;
  excludedFailed: number;
  excludedReview: number;
  excludedPending: number;
  qualityRate: number;
  sourcesCount: number;
  citationTotal: number;
  returnedCitations: number;
  sourceLabel: string;
  sources: ObservatorySource[];
  engines: ObservatoryEngine[];
  questions: ObservatoryQuestion[];
  mentions: ObservatoryMention[];
  ranges: ObservatoryRange[];
  actions: ObservatoryAction[];
  noticeTitle: string;
  noticeNote: string;
}

const demoQuestions: ObservatoryQuestion[] = [
  { id: "01", question: "广州 AI 培训哪家靠谱？", engine: "文心", status: "带链接", scene: "想选机构", attempts: 12, mentions: 3, links: 2, flag: "ok" },
  { id: "02", question: "广州 AI 培训机构排名", engine: "元宝", status: "带链接", scene: "在比机构", attempts: 12, mentions: 4, links: 1, flag: "ok" },
  { id: "03", question: "零基础能学 AI 吗", engine: "豆包", status: "只提到", scene: "刚了解", attempts: 12, mentions: 2, links: 0, flag: "review" },
  { id: "04", question: "AIGC 作品集怎么准备", engine: "文心", status: "只提到", scene: "在找工作", attempts: 9, mentions: 1, links: 1, flag: "ok" },
  { id: "05", question: "AI 培训就业前景", engine: "豆包", status: "链接失效", scene: "看行业", attempts: 8, mentions: 1, links: 0, flag: "review" },
  { id: "06", question: "AI 漫剧制作流程", engine: "DeepSeek", status: "只提到", scene: "找做法", attempts: 8, mentions: 0, links: 0, flag: "gap" },
];

export const demoObservatoryData: ObservatoryData = {
  mode: "demo",
  projectName: "广州基地",
  projectId: "154640d4-6356-4a1c-8bde-2d511cfb06cd",
  userName: "运营编辑",
  canWriteQuestion: false,
  canWriteContent: false,
  updatedAt: "12:40",
  dateLabel: "2026.11.25",
  totalAnswers: 97,
  brandAnswers: 0,
  mentionedAnswers: 5,
  citedAnswers: 2,
  mentionRate: 5.1,
  citeRate: 2.1,
  competitorTogether: 0,
  excludedFailed: 9,
  excludedReview: 0,
  excludedPending: 0,
  qualityRate: 91.5,
  sourcesCount: 50,
  citationTotal: 152,
  returnedCitations: 2,
  sourceLabel: "50 个网站 · 152 次链接",
  sources: [
    { name: "知乎", share: 34, citations: 52 },
    { name: "官网", share: 23, citations: 35 },
    { name: "公众号", share: 18, citations: 27 },
    { name: "行业媒体", share: 15, citations: 23 },
    { name: "其他", share: 10, citations: 15 },
  ],
  engines: [
    { name: "文心", count: 27 },
    { name: "豆包", count: 24 },
    { name: "DeepSeek", count: 25 },
    { name: "元宝", count: 21 },
  ],
  questions: demoQuestions,
  mentions: demoQuestions.filter((row) => row.mentions > 0).slice(0, 5).map((row) => ({
    id: row.id, question: row.question, engine: row.engine, status: row.status, links: row.links,
  })),
  ranges: [
    { days: 7, dates: ["11.19", "11.20", "11.21", "11.22", "11.23", "11.24", "11.25"], mentions: [1, 2, 1, 3, 2, 4, 5], links: [0, 0, 1, 1, 1, 2, 2], label: "最近 7 天 · 7 个时间点", peakLabel: "11.25", peakSource: "广州 AI 培训机构排名" },
    { days: 30, dates: ["10.27", "11.01", "11.05", "11.09", "11.13", "11.17", "11.25"], mentions: [3, 5, 4, 7, 6, 8, 9], links: [1, 1, 1, 2, 2, 2, 3], label: "最近 30 天 · 7 个时间点", peakLabel: "11.25", peakSource: "广州 AI 培训机构排名" },
    { days: 90, dates: ["09.01", "09.15", "10.01", "10.15", "11.01", "11.15", "11.25"], mentions: [8, 12, 10, 15, 14, 17, 20], links: [2, 3, 3, 4, 4, 5, 6], label: "最近 90 天 · 7 个时间点", peakLabel: "11.25", peakSource: "广州 AI 培训机构排名" },
  ],
  actions: [
    { no: "01", title: "补一页知乎上的介绍", note: "知乎带来 34% 的链接，先把这页写完整", section: "内容出处" },
    { no: "02", title: "确认 4 条拿不准的回答", note: "这 4 条像提到了你，确认后才能算进比例", section: "回答明细" },
    { no: "03", title: "写一篇你和竞品的对比", note: "97 条里没有一条同时提到你和竞品", section: "诊断报告" },
  ],
  noticeTitle: "2 条回答要处理",
  noticeNote: " · 1 条没提到你、1 条链接失效",
};

export function statusOf(mentions: number, links: number): AnswerStatus {
  if (links > 0) return "带链接";
  if (mentions > 0) return "只提到";
  return "没提到";
}
