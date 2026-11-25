import { backendRequest } from "@/lib/workbench/backend";
import { getSessionToken } from "@/lib/workbench/server-session";
import type { SampleDetail, StatsOverview, StatsQuestion, StatsSource } from "@/lib/workbench/types";
import {
  demoObservatoryData,
  statusOf,
  type AnswerFlag,
  type ObservatoryAction,
  type ObservatoryData,
  type ObservatoryEngine,
  type ObservatoryMention,
  type ObservatoryQuestion,
  type ObservatoryRange,
  type ObservatorySource,
} from "./observatory-data";

interface BackendMe {
  display_name: string;
  is_system_admin: boolean;
  projects: { id: string; name: string; code: string; role_code?: string; permissions?: string[] }[];
}

interface BackendProject {
  id: string;
  name: string;
  code: string;
  status: string;
}

interface TaskRow {
  id: string;
  question_title: string;
  engine_name: string;
  question_code: string;
}

interface SampleRow {
  id: string;
  serial_no: number;
  task_id: string;
  sampled_at: string | null;
  status: string;
  brand_mentioned: boolean | null;
}

const statsQuery = "?question_type=general";

function fallbackData(): ObservatoryData {
  return structuredClone({ ...demoObservatoryData, mode: "fallback" as const });
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

function shortEngine(name: string): string {
  if (name.includes("文心") || name.includes("ERNIE")) return "文心";
  if (name.includes("元宝")) return "元宝";
  if (name.includes("豆包")) return "豆包";
  return name.replace(/^腾讯/, "");
}

function sourceLabel(domain: string): string {
  const map: Record<string, string> = {
    "mp.weixin.qq.com": "公众号",
    "weixin.qq.com": "公众号",
    "zhuanlan.zhihu.com": "知乎",
    "zhihu.com": "知乎",
    "blog.csdn.net": "CSDN",
    "baijiahao.baidu.com": "百家号",
    "gz.itheima.com": "黑马程序员",
    "iesdouyin.com": "抖音",
    "sohu.com": "搜狐",
    "m.sohu.com": "搜狐",
    "news.sohu.com": "搜狐",
    "toutiao.com": "今日头条",
    "rsj.gz.gov.cn": "广州人社局",
    "gz.gov.cn": "广州市政府",
    "baike.baidu.com": "百度百科",
    "qinxue365.com": "轻学365",
    "m.qinxue365.com": "轻学365",
    "bilibili.com": "哔哩哔哩",
  };
  if (map[domain]) return map[domain];
  const clean = domain.replace(/^(www\.|m\.)/, "");
  const first = clean.split(".")[0] ?? domain;
  return first.length > 10 ? `${first.slice(0, 10)}…` : first;
}

function mmdd(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${String(date.getMonth() + 1).padStart(2, "0")}.${String(date.getDate()).padStart(2, "0")}`;
}

function ymd(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${date.getFullYear()}.${String(date.getMonth() + 1).padStart(2, "0")}.${String(date.getDate()).padStart(2, "0")}`;
}

function hm(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

async function allTasks(token: string, projectId: string): Promise<TaskRow[]> {
  const base = `/api/v1/projects/${projectId}/monitoring/tasks` as const;
  const rows: TaskRow[] = [];
  for (let page = 1; page <= 3; page++) {
    const result = await backendRequest<TaskRow[]>(`${base}?page=${page}&page_size=100` as `/api/v1/${string}`, token);
    rows.push(...result.data);
    if (!result.meta || rows.length >= result.meta.total || result.data.length === 0) break;
  }
  return rows;
}

async function allSamples(token: string, projectId: string): Promise<SampleRow[]> {
  const base = `/api/v1/projects/${projectId}/monitoring/samples` as const;
  const rows: SampleRow[] = [];
  for (let page = 1; page <= 3; page++) {
    const result = await backendRequest<SampleRow[]>(`${base}?page=${page}&page_size=100` as `/api/v1/${string}`, token);
    rows.push(...result.data);
    if (!result.meta || rows.length >= result.meta.total || result.data.length === 0) break;
  }
  return rows;
}

async function sampleLinks(token: string, projectId: string, samples: SampleRow[]): Promise<Map<string, number>> {
  const result = new Map<string, number>();
  const eligible = samples.filter((sample) => sample.brand_mentioned).slice(0, 40);
  for (let index = 0; index < eligible.length; index += 5) {
    const batch = eligible.slice(index, index + 5);
    await Promise.all(batch.map(async (sample) => {
      try {
        const detail = (await backendRequest<SampleDetail>(
          `/api/v1/projects/${projectId}/monitoring/samples/${sample.id}` as `/api/v1/${string}`,
          token,
        )).data;
        const links = detail.citations.filter((citation) => citation.is_brand_related || citation.channel_id).length;
        result.set(sample.id, links);
      } catch {
        result.set(sample.id, 0);
      }
    }));
  }
  return result;
}

function buildRanges(samples: SampleRow[], linksBySample: Map<string, number>, titles: Map<string, string>, latest: string): ObservatoryRange[] {
  const end = new Date(latest).getTime();
  const valid = samples.filter((sample) => sample.sampled_at && !Number.isNaN(new Date(sample.sampled_at).getTime()));
  return [7, 30, 90].map((days) => {
    const bucketMs = (days * 24 * 60 * 60 * 1000) / 7;
    const mentions: number[] = [];
    const links: number[] = [];
    const dates: string[] = [];
    let peak = { value: -1, label: "—", source: "还没有提到你的回答" };
    for (let index = 0; index < 7; index++) {
      const from = end - (7 - index) * bucketMs;
      const to = end - (6 - index) * bucketMs;
      const bucket = valid.filter((sample) => {
        const at = new Date(sample.sampled_at!).getTime();
        return at >= from && (index === 6 ? at <= end + 1000 : at < to);
      });
      const mentioned = bucket.filter((sample) => sample.brand_mentioned);
      const mentionCount = mentioned.length;
      const linkCount = mentioned.reduce((total, sample) => total + (linksBySample.get(sample.id) ?? 0), 0);
      mentions.push(mentionCount);
      links.push(linkCount);
      dates.push(mmdd(new Date(to).toISOString()));
      if (mentionCount > 0 && mentionCount > peak.value) {
        const first = mentioned[0];
        peak = {
          value: mentionCount,
          label: first?.sampled_at ? mmdd(first.sampled_at) : mmdd(new Date(to).toISOString()),
          source: first ? titles.get(first.task_id) ?? "一条提到你的回答" : "还没有提到你的回答",
        };
      }
    }
    return {
      days,
      mentions,
      links,
      dates,
      label: `最近 ${days} 天 · 7 个时间点 · 截至 ${mmdd(latest)}`,
      peakLabel: peak.label,
      peakSource: peak.source,
    };
  });
}

function buildActions(input: {
  topSource: ObservatorySource | undefined;
  gapQuestions: ObservatoryQuestion[];
  pendingReview: number;
  competitorTogether: number;
  mentioned: number;
  cited: number;
  total: number;
}): ObservatoryAction[] {
  const actions: ObservatoryAction[] = [];
  if (input.topSource) {
    actions.push({
      no: "01",
      title: `补一页${input.topSource.name}上的介绍`,
      note: `${input.topSource.name}带来 ${input.topSource.share}% 的链接，先把这页写完整`,
      section: "内容出处",
    });
  }
  if (input.pendingReview > 0) {
    actions.push({
      no: "02",
      title: `确认 ${input.pendingReview} 条拿不准的回答`,
      note: "这些回答像提到了你，确认后才能算进比例",
      section: "回答明细",
    });
  } else if (input.gapQuestions.length > 0) {
    const attempts = input.gapQuestions.reduce((total, question) => total + question.attempts, 0);
    actions.push({
      no: "02",
      title: `补 ${input.gapQuestions.length} 个还没提到你的问题`,
      note: `这 ${input.gapQuestions.length} 个问题查了 ${attempts} 次，一次都没出现`,
      section: "监测问题",
    });
  } else {
    actions.push({ no: "02", title: "把带链接的回答整理成案例", note: `${input.cited} 条回答已经带链接，可以做成案例页`, section: "回答明细" });
  }
  actions.push(
    input.competitorTogether === 0
      ? { no: "03", title: "写一篇你和竞品的对比", note: `${input.total} 条里没有一条同时提到你和竞品`, section: "诊断报告" }
      : { no: "03", title: "看看竞品在哪些回答里出现", note: `${input.competitorTogether} 条回答同时提到你和竞品`, section: "诊断报告" },
  );
  return actions.slice(0, 3);
}

export async function loadObservatoryData(projectIdFromQuery?: string): Promise<ObservatoryData> {
  const token = await getSessionToken();
  if (!token) return demoObservatoryData;

  try {
    const [meEnvelope, projectsEnvelope] = await Promise.all([
      backendRequest<BackendMe>("/api/v1/auth/me", token),
      backendRequest<BackendProject[]>("/api/v1/projects?page=1&page_size=100", token),
    ]);
    const me = meEnvelope.data;
    const projects = projectsEnvelope.data;
    const requested = projectIdFromQuery && /^[0-9a-f-]{36}$/i.test(projectIdFromQuery) ? projectIdFromQuery : "";
    const selected = projects.find((project) => project.id === requested)
      ?? (requested ? undefined : projects.find((project) => project.name === "广州基地") ?? projects[0]);
    if (!selected) return fallbackData();
    const projectId = selected.id;
    const membership = me.projects.find((project) => project.id === projectId);
    const permissions = new Set(membership?.permissions ?? []);

    const [overviewEnvelope, brandOverviewEnvelope, questionEnvelope, sourceEnvelope, geoEnvelope, tasks, samples] = await Promise.all([
      backendRequest<StatsOverview>(`/api/v1/projects/${projectId}/stats/overview${statsQuery}` as `/api/v1/${string}`, token),
      backendRequest<StatsOverview>(`/api/v1/projects/${projectId}/stats/overview?question_type=brand` as `/api/v1/${string}`, token),
      backendRequest<StatsQuestion[]>(`/api/v1/projects/${projectId}/stats/by-question${statsQuery}` as `/api/v1/${string}`, token),
      backendRequest<StatsSource[]>(`/api/v1/projects/${projectId}/stats/sources?limit=50&question_type=general` as `/api/v1/${string}`, token),
      backendRequest<{ counts: Record<string, number>; by_competitor: { competitor: string; mentioned_samples: number }[] }>(
        `/api/v1/projects/${projectId}/stats/geo${statsQuery}` as `/api/v1/${string}`,
        token,
      ),
      allTasks(token, projectId),
      allSamples(token, projectId),
    ]);

    const overview = overviewEnvelope.data;
    const brandOverview = brandOverviewEnvelope.data;
    const questionStats = questionEnvelope.data;
    const sourceRows = sourceEnvelope.data;
    const geo = geoEnvelope.data;

    const taskMap = new Map(tasks.map((task) => [task.id, task]));
    const generalTitles = new Set(questionStats.map((question) => question.question_title));
    const validSamples = samples.filter((sample) => sample.status === "hit" || sample.status === "miss");
    const scopedSamples = validSamples.filter((sample) => generalTitles.has(taskMap.get(sample.task_id)?.question_title ?? ""));
    const scoped = scopedSamples.length ? scopedSamples : validSamples;

    const latest = scoped
      .map((sample) => sample.sampled_at)
      .filter((value): value is string => Boolean(value))
      .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0] ?? new Date().toISOString();

    const linksBySample = await sampleLinks(token, projectId, scoped);

    const engineCounts = new Map<string, number>();
    const titleEngines = new Map<string, Map<string, number>>();
    for (const sample of scoped) {
      const task = taskMap.get(sample.task_id);
      if (!task) continue;
      const engine = shortEngine(task.engine_name || "未知平台");
      engineCounts.set(engine, (engineCounts.get(engine) ?? 0) + 1);
      const byTitle = titleEngines.get(task.question_title) ?? new Map<string, number>();
      byTitle.set(engine, (byTitle.get(engine) ?? 0) + 1);
      titleEngines.set(task.question_title, byTitle);
    }
    const engines: ObservatoryEngine[] = Array.from(engineCounts.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 4);

    const questions: ObservatoryQuestion[] = questionStats.map((question) => {
      const mentions = question.brand_mentioned_answers;
      const links = question.citation_answers;
      const byTitle = titleEngines.get(question.question_title);
      const engine = byTitle ? Array.from(byTitle.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "全部平台" : "全部平台";
      return {
        id: question.question_code,
        question: question.question_title,
        scene: question.question_type === "brand" ? "搜品牌名" : "行业问题",
        engine,
        attempts: question.valid_answers,
        mentions,
        links,
        status: statusOf(mentions, links),
        flag: (links > 0 ? "ok" : mentions > 0 ? "review" : "gap") as AnswerFlag,
      };
    }).sort((a, b) => a.id.localeCompare(b.id));

    const totalCitations = sourceRows.reduce((total, row) => total + row.citations, 0);
    const grouped = new Map<string, number>();
    for (const row of sourceRows) {
      const label = sourceLabel(row.domain);
      grouped.set(label, (grouped.get(label) ?? 0) + row.citations);
    }
    const sorted = Array.from(grouped.entries()).sort((a, b) => b[1] - a[1]);
    const top = sorted.slice(0, 5);
    const sources: ObservatorySource[] = top.map(([name, citations]) => ({
      name,
      citations,
      share: totalCitations ? Math.round((citations / totalCitations) * 100) : 0,
    }));

    const mentionSamples = scoped
      .filter((sample) => sample.brand_mentioned)
      .sort((a, b) => new Date(b.sampled_at ?? 0).getTime() - new Date(a.sampled_at ?? 0).getTime());
    const mentions: ObservatoryMention[] = mentionSamples.slice(0, Math.max(1, overview.brand_mentioned_answers)).map((sample, index) => {
      const task = taskMap.get(sample.task_id);
      const links = linksBySample.get(sample.id) ?? 0;
      return {
        id: String(index + 1).padStart(2, "0"),
        question: task?.question_title ?? "一条提到你的回答",
        engine: shortEngine(task?.engine_name ?? "AI 平台"),
        status: statusOf(1, links),
        links,
        when: sample.sampled_at ? mmdd(sample.sampled_at) : undefined,
      };
    });

    const mentionRate = overview.brand_mention_rate != null ? round1(overview.brand_mention_rate * 100) : 0;
    const citeRate = overview.citation_rate != null ? round1(overview.citation_rate * 100) : 0;
    const excluded = overview.excluded;
    const qualityRate = overview.valid_answers + excluded.failed > 0
      ? round1((overview.valid_answers / (overview.valid_answers + excluded.failed)) * 100)
      : 0;
    const gapQuestions = questions.filter((question) => question.mentions === 0);
    const pendingReview = excluded.manual_review;
    const competitorTogether = geo.counts.competitor_mentioned_samples ?? 0;

    const actions = buildActions({
      topSource: sources[0],
      gapQuestions,
      pendingReview,
      competitorTogether,
      mentioned: overview.brand_mentioned_answers,
      cited: overview.brand_cited_answers ?? overview.citation_answers,
      total: overview.valid_answers,
    });

    const noticeTitle = pendingReview > 0
      ? `${pendingReview} 条回答要确认`
      : `${excluded.failed} 条回答没查成`;
    const noticeNote = pendingReview > 0
      ? " · 确认后才计入比例"
      : ` · ${gapQuestions.length} 个问题一次都没提到你`;

    return {
      mode: "live",
      projectName: selected.name,
      projectId,
      userName: me.display_name,
      canWriteQuestion: permissions.has("question.write"),
      canWriteContent: permissions.has("content.write"),
      updatedAt: `${mmdd(latest)} ${hm(latest)}`,
      dateLabel: ymd(latest),
      totalAnswers: overview.valid_answers,
      brandAnswers: brandOverview.valid_answers,
      mentionedAnswers: overview.brand_mentioned_answers,
      citedAnswers: overview.brand_cited_answers ?? overview.citation_answers,
      mentionRate,
      citeRate,
      competitorTogether,
      excludedFailed: excluded.failed,
      excludedReview: excluded.manual_review,
      excludedPending: excluded.pending_or_running,
      qualityRate,
      sourcesCount: sourceRows.length,
      citationTotal: totalCitations,
      returnedCitations: overview.brand_cited_answers ?? overview.citation_answers,
      sourceLabel: `${sourceRows.length} 个网站 · ${totalCitations} 次链接`,
      sources,
      engines,
      questions,
      mentions,
      ranges: buildRanges(scoped, linksBySample, new Map(tasks.map((task) => [task.id, task.question_title])), latest),
      actions,
      noticeTitle,
      noticeNote,
    };
  } catch {
    return fallbackData();
  }
}
