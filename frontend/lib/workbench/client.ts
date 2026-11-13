import type { ApiEnvelope, BatchGenerationResult, ChannelRecord, KeywordRecord, Lead, MonitoringRound, QuestionRecord, QuestionVersionRecord, ReviewItem, StatsEngine, StatsOverview, StatsQuestion, WorkbenchSnapshot } from "./types";

export class WorkbenchApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

const sessionCodes = new Set(["unauthorized", "token_expired", "token_invalid", "token_stale", "user_inactive"]);

function errorMessage(status: number, code: string, fallback?: string): string {
  if (status === 401 || sessionCodes.has(code)) return "登录已失效，请重新登录";
  if (code === "project_forbidden") return "你没有访问该项目的权限";
  if (code === "insufficient_role") return "当前角色没有执行此操作的权限";
  if (code === "system_admin_only") return "此操作仅限系统管理员";
  if (status === 403) return "没有执行此操作的权限";
  return fallback || "请求失败，请稍后再试";
}

async function readResponse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const code = typeof payload?.error?.code === "string" ? payload.error.code : "upstream_error";
    if (response.status === 401 || sessionCodes.has(code)) {
      try { await fetch("/internal/session", { method: "DELETE" }); } catch { /* Continue to login. */ }
      window.location.replace("/login");
    }
    throw new WorkbenchApiError(response.status, code, errorMessage(response.status, code, payload?.error?.message));
  }
  return payload.data as T;
}

async function readPage<T>(response: Response): Promise<ApiEnvelope<T>> {
  const copy = response.clone();
  const data = await readResponse<T>(response);
  const payload = await copy.json().catch(() => null);
  return { data, meta: payload?.meta };
}

function dataUrl(kind: string, projectId: string, options: Record<string, string | number | undefined> = {}) {
  const query = new URLSearchParams({ kind, project_id: projectId });
  for (const [key, value] of Object.entries(options)) if (value !== undefined && value !== "") query.set(key, String(value));
  return `/internal/workbench/data?${query}`;
}

export const workbenchClient = {
  async snapshot(projectId?: string): Promise<WorkbenchSnapshot> {
    const query = projectId && projectId !== "all" ? `?project_id=${encodeURIComponent(projectId)}` : "";
    return readResponse<WorkbenchSnapshot>(await fetch(`/internal/workbench${query}`, { cache: "no-store" }));
  },
  async createLead(input: Pick<Lead, "contactName" | "phone" | "interest" | "source" | "projectId">): Promise<Lead> {
    return readResponse<Lead>(await fetch("/internal/workbench/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }));
  },
  async review(id: string, status: "已通过" | "已驳回"): Promise<ReviewItem> {
    return readResponse<ReviewItem>(await fetch(`/internal/workbench/reviews/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }));
  },
  async rounds(projectId: string, page = 1): Promise<ApiEnvelope<MonitoringRound[]>> {
    return readPage<MonitoringRound[]>(await fetch(dataUrl("rounds", projectId, { page, page_size: 20 }), { cache: "no-store" }));
  },
  async createRound(projectId: string, input: { name: string; is_baseline: boolean }): Promise<MonitoringRound> {
    return readResponse<MonitoringRound>(await fetch(dataUrl("rounds", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async generateTasks(projectId: string, roundId: string): Promise<BatchGenerationResult> {
    return readResponse<BatchGenerationResult>(await fetch(dataUrl("batch", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ round_id: roundId }),
    }));
  },
  async channels(projectId: string, page = 1): Promise<ApiEnvelope<ChannelRecord[]>> {
    return readPage<ChannelRecord[]>(await fetch(dataUrl("channels", projectId, { page, page_size: 20 }), { cache: "no-store" }));
  },
  async channel(projectId: string, id: string): Promise<ChannelRecord> {
    return readResponse<ChannelRecord>(await fetch(dataUrl("channel", projectId, { id }), { cache: "no-store" }));
  },
  async saveChannel(projectId: string, input: Record<string, unknown>, id?: string): Promise<ChannelRecord> {
    return readResponse<ChannelRecord>(await fetch(dataUrl(id ? "channel" : "channels", projectId, { id }), {
      method: id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async questions(projectId: string, page = 1): Promise<ApiEnvelope<QuestionRecord[]>> {
    return readPage<QuestionRecord[]>(await fetch(dataUrl("questions", projectId, { page, page_size: 20 }), { cache: "no-store" }));
  },
  async saveQuestion(projectId: string, input: Record<string, unknown>, id?: string): Promise<QuestionRecord> {
    return readResponse<QuestionRecord>(await fetch(dataUrl(id ? "question" : "questions", projectId, { id }), {
      method: id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async questionVersions(projectId: string, id: string): Promise<ApiEnvelope<QuestionVersionRecord[]>> {
    return readPage<QuestionVersionRecord[]>(await fetch(dataUrl("question-versions", projectId, { id }), { cache: "no-store" }));
  },
  async addQuestionVersion(projectId: string, id: string, text: string, changeNote: string): Promise<QuestionVersionRecord> {
    return readResponse<QuestionVersionRecord>(await fetch(dataUrl("question-version", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, change_note: changeNote || null }),
    }));
  },
  async keywords(projectId: string, page = 1): Promise<ApiEnvelope<KeywordRecord[]>> {
    return readPage<KeywordRecord[]>(await fetch(dataUrl("keywords", projectId, { page, page_size: 20 }), { cache: "no-store" }));
  },
  async createKeyword(projectId: string, input: Record<string, unknown>): Promise<KeywordRecord> {
    return readResponse<KeywordRecord>(await fetch(dataUrl("keywords", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async statsOverview(projectId: string): Promise<StatsOverview> {
    return readResponse<StatsOverview>(await fetch(dataUrl("stats-overview", projectId), { cache: "no-store" }));
  },
  async statsByEngine(projectId: string): Promise<StatsEngine[]> {
    return readResponse<StatsEngine[]>(await fetch(dataUrl("stats-by-engine", projectId), { cache: "no-store" }));
  },
  async statsByQuestion(projectId: string): Promise<StatsQuestion[]> {
    return readResponse<StatsQuestion[]>(await fetch(dataUrl("stats-by-question", projectId), { cache: "no-store" }));
  },
  async downloadStats(projectId: string): Promise<void> {
    const response = await fetch(dataUrl("stats-export", projectId), { cache: "no-store" });
    if (!response.ok) { await readResponse(response); return; }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)/)?.[1] ?? "stats.csv";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  async logout(): Promise<void> {
    await fetch("/internal/session", { method: "DELETE" });
  },
};
