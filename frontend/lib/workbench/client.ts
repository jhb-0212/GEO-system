import type { ApiEnvelope, AuditLogRecord, BatchGenerationResult, BrandProfileRecord, BudgetApproval, ChannelDetailRecord, ChannelRecord, CitationRecord, CompetitorRecord, ContentExportPackage, ContentReviewRecord, ContentVersionDetail, ContentVersionLinks, ContentVersionRecord, DiagnosticSample, EngineConnectionResult, EngineEntryRecord, EngineHealth, EngineRecord, EvidenceUploadResult, FactClaimRecord, FactRecord, FactTypeOption, FactVersionRecord, CorrectionTaskRecord, FaqRecord, GeoOverview, KeywordRecord, Lead, LeadFunnel, ManualSampleCreated, MaterialRecord, MemberRecord, MetricDefinitionRecord, MonitoringRound, MonitoringTaskRecord, MonthlyReport, OpportunityRecord, PageCheckResult, PageRecord, PlanRecord, Project, PublishAccountRecord, PublishTaskRecord, QuestionRecord, QuestionVersionRecord, QuoteRecord, RoundCompletionResult, SampleDetail, SampleRecord, SiteDiagnosticsSummary, SourceReviewRecord, StatSnapshotRecord, StatsAnswerKindOverview, StatsEngine, StatsOverview, StatsQuestion, StatsSource, StatsPublishVisibility, TraceChain, UnknownDomainRecord, UserCandidate, WorkbenchSnapshot } from "./types";

export class WorkbenchApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

const sessionCodes = new Set(["unauthorized", "token_expired", "token_invalid", "token_stale", "user_inactive"]);

export const WORKBENCH_PAGE_SIZE = 20;
export const MEMBERS_PAGE_SIZE = 100;

function errorMessage(status: number, code: string, fallback?: string): string {
  if (status === 401 || sessionCodes.has(code)) return "登录已失效，请重新登录";
  if (code === "project_forbidden") return "你没有访问该项目的权限";
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

type AnswerKindParam = "answer" | "search_result";
type QuestionTypeParam = "brand" | "general" | "all";

function dataUrl(kind: string, projectId: string, options: Record<string, string | number | undefined> = {}) {
  const query = new URLSearchParams({ kind, project_id: projectId });
  for (const [key, value] of Object.entries(options)) if (value !== undefined && value !== "") query.set(key, String(value));
  return `/internal/workbench/data?${query}`;
}

function engineUrl(kind: string, options: Record<string, string | number | undefined> = {}) {
  const query = new URLSearchParams({ kind });
  for (const [key, value] of Object.entries(options)) if (value !== undefined && value !== "") query.set(key, String(value));
  return `/internal/workbench/engines?${query}`;
}

export const workbenchClient = {
  async snapshot(projectId?: string): Promise<WorkbenchSnapshot> {
    const query = projectId && projectId !== "all" ? `?project_id=${encodeURIComponent(projectId)}` : "";
    return readResponse<WorkbenchSnapshot>(await fetch(`/internal/workbench${query}`, { cache: "no-store" }));
  },
  async createLead(input: Pick<Lead, "contactName" | "phone" | "interest" | "source" | "projectId" | "reportedAiProduct" | "isValid">): Promise<Lead> {
    return readResponse<Lead>(await fetch("/internal/workbench/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }));
  },
  async confirmProject(projectId: string, priority: number, note?: string): Promise<Project> {
    return readResponse<Project>(await fetch(dataUrl("project-confirm", projectId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ priority, note: note || null }),
    }));
  },
  async updateLead(projectId: string, id: string, input: Record<string, unknown>): Promise<Lead> {
    return readResponse<Lead>(await fetch(dataUrl("lead", projectId, { id }), {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async downloadLeads(projectId: string): Promise<void> {
    const response = await fetch(dataUrl("leads-export", projectId), { cache: "no-store" });
    if (!response.ok) { await readResponse(response); return; }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)/)?.[1] ?? "leads.csv";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  async faqs(projectId: string, options: { status?: string; category?: string; q?: string; page?: number; pageSize?: number; deleted?: boolean } = {}): Promise<ApiEnvelope<FaqRecord[]>> {
    return readPage<FaqRecord[]>(await fetch(dataUrl("faqs", projectId, {
      status: options.status,
      category: options.category,
      q: options.q?.trim() || undefined,
      page: options.page ?? 1,
      page_size: options.pageSize ?? 50,
      deleted: options.deleted ? "true" : undefined,
    }), { cache: "no-store" }));
  },
  async faqCategories(projectId: string): Promise<string[]> {
    return readResponse<string[]>(await fetch(dataUrl("faq-categories", projectId), { cache: "no-store" }));
  },
  async createFaq(projectId: string, input: Record<string, unknown>): Promise<{ id: string }> {
    return readResponse<{ id: string }>(await fetch(dataUrl("faq", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async updateFaq(projectId: string, id: string, input: Record<string, unknown>): Promise<FaqRecord> {
    return readResponse<FaqRecord>(await fetch(dataUrl("faq", projectId, { id }), {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async deleteFaq(projectId: string, id: string): Promise<FaqRecord> {
    return readResponse<FaqRecord>(await fetch(dataUrl("faq", projectId, { id }), {
      method: "DELETE",
    }));
  },
  async restoreFaq(projectId: string, id: string): Promise<FaqRecord> {
    return readResponse<FaqRecord>(await fetch(dataUrl("faq-restore", projectId, { id }), {
      method: "POST",
      // BFF 的 data 路由在解析路径前就要求 body 是对象；恢复动作本身没有字段，
      // 发空对象即可，之前不带 body 一律 400，被误判成后端不支持。
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }));
  },
  async auditLogs(projectId: string, page = 1, pageSize = 20): Promise<ApiEnvelope<AuditLogRecord[]>> {
    return readPage<AuditLogRecord[]>(await fetch(dataUrl("audit-logs", projectId, { page, page_size: pageSize }), { cache: "no-store" }));
  },
  async materials(projectId: string, category?: string, page = 1): Promise<ApiEnvelope<MaterialRecord[]>> {
    return readPage<MaterialRecord[]>(await fetch(dataUrl("materials", projectId, { category, page, page_size: 50 }), { cache: "no-store" }));
  },
  async uploadMaterial(projectId: string, form: FormData): Promise<MaterialRecord> {
    return readResponse<MaterialRecord>(await fetch(`/internal/workbench/materials?project_id=${encodeURIComponent(projectId)}`, {
      method: "POST", body: form,
    }));
  },
  async updateMaterial(projectId: string, id: string, input: Record<string, unknown>): Promise<MaterialRecord> {
    return readResponse<MaterialRecord>(await fetch(dataUrl("material", projectId, { id }), {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async downloadMaterial(projectId: string, id: string): Promise<void> {
    const response = await fetch(`/internal/workbench/materials/${encodeURIComponent(id)}/download?project_id=${encodeURIComponent(projectId)}`, { cache: "no-store" });
    if (!response.ok) { await readResponse(response); return; }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)/)?.[1] ?? "material";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  async review(projectId: string, id: string, status: "已通过" | "已驳回"): Promise<{ review_id: string; decision: string }> {
    return readResponse<{ review_id: string; decision: string }>(await fetch(`/internal/workbench/reviews/${encodeURIComponent(id)}?project_id=${encodeURIComponent(projectId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }));
  },
  async rounds(projectId: string, page = 1, pageSize = 20): Promise<ApiEnvelope<MonitoringRound[]>> {
    return readPage<MonitoringRound[]>(await fetch(dataUrl("rounds", projectId, { page, page_size: pageSize }), { cache: "no-store" }));
  },
  async createRound(projectId: string, input: { name: string; is_baseline: boolean }): Promise<MonitoringRound> {
    return readResponse<MonitoringRound>(await fetch(dataUrl("rounds", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async startRound(projectId: string, roundId: string): Promise<MonitoringRound> {
    return readResponse<MonitoringRound>(await fetch(dataUrl("round-start", projectId, { id: roundId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async completeRound(projectId: string, roundId: string): Promise<RoundCompletionResult> {
    return readResponse<RoundCompletionResult>(await fetch(dataUrl("round-complete", projectId, { id: roundId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async generateTasks(projectId: string, roundId: string): Promise<BatchGenerationResult> {
    return readResponse<BatchGenerationResult>(await fetch(dataUrl("batch", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ round_id: roundId }),
    }));
  },
  async channels(projectId: string, page = 1, pageSize = 20): Promise<ApiEnvelope<ChannelRecord[]>> {
    return readPage<ChannelRecord[]>(await fetch(dataUrl("channels", projectId, { page, page_size: pageSize }), { cache: "no-store" }));
  },
  async channel(projectId: string, id: string): Promise<ChannelDetailRecord> {
    return readResponse<ChannelDetailRecord>(await fetch(dataUrl("channel", projectId, { id }), { cache: "no-store" }));
  },
  async downloadChannels(projectId: string): Promise<void> {
    const response = await fetch(dataUrl("channels-export", projectId), { cache: "no-store" });
    if (!response.ok) { await readResponse(response); return; }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)/)?.[1] ?? "channels.csv";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  async engines(page = 1): Promise<ApiEnvelope<EngineRecord[]>> {
    return readPage<EngineRecord[]>(await fetch(engineUrl("engines", { page, page_size: 20 }), { cache: "no-store" }));
  },
  async engineEntries(engineId: string, page = 1): Promise<ApiEnvelope<EngineEntryRecord[]>> {
    return readPage<EngineEntryRecord[]>(await fetch(engineUrl("entries", { engine_id: engineId, page, page_size: 20 }), { cache: "no-store" }));
  },
  async createEngine(input: Record<string, unknown>): Promise<EngineRecord> {
    return readResponse<EngineRecord>(await fetch(engineUrl("engine"), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async saveEngineEntry(engineId: string, input: Record<string, unknown>, entryId?: string): Promise<EngineEntryRecord> {
    return readResponse<EngineEntryRecord>(await fetch(engineUrl("entry", { engine_id: engineId, entry_id: entryId }), {
      method: entryId ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async deleteEngineEntry(engineId: string, entryId: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(engineUrl("entry", { engine_id: engineId, entry_id: entryId }), { method: "DELETE" }));
  },
  async testEngineEntry(engineId: string, entryId: string): Promise<EngineConnectionResult> {
    return readResponse<EngineConnectionResult>(await fetch(engineUrl("test", { engine_id: engineId, entry_id: entryId }), { method: "POST" }));
  },
  async verifyEngineEntry(engineId: string, entryId: string, note?: string): Promise<EngineEntryRecord> {
    return readResponse<EngineEntryRecord>(await fetch(engineUrl("verify", { engine_id: engineId, entry_id: entryId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(note ? { note } : {}),
    }));
  },
  async saveChannel(projectId: string, input: Record<string, unknown>, id?: string): Promise<ChannelRecord> {
    return readResponse<ChannelRecord>(await fetch(dataUrl(id ? "channel" : "channels", projectId, { id }), {
      method: id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async questions(projectId: string, page = 1, status?: string, questionType?: string): Promise<ApiEnvelope<QuestionRecord[]>> {
    return readPage<QuestionRecord[]>(await fetch(dataUrl("questions", projectId, { page, page_size: 20, status, question_type: questionType }), { cache: "no-store" }));
  },
  async saveQuestion(projectId: string, input: Record<string, unknown>, id?: string): Promise<QuestionRecord> {
    return readResponse<QuestionRecord>(await fetch(dataUrl(id ? "question" : "questions", projectId, { id }), {
      method: id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async questionVersions(projectId: string, id: string, page = 1): Promise<ApiEnvelope<QuestionVersionRecord[]>> {
    return readPage<QuestionVersionRecord[]>(await fetch(dataUrl("question-versions", projectId, { id, page, page_size: 20 }), { cache: "no-store" }));
  },
  async addQuestionVersion(projectId: string, id: string, text: string, changeNote: string): Promise<QuestionVersionRecord> {
    return readResponse<QuestionVersionRecord>(await fetch(dataUrl("question-version", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, change_note: changeNote || null }),
    }));
  },
  async keywords(projectId: string, page = 1, category?: string, isActive?: boolean): Promise<ApiEnvelope<KeywordRecord[]>> {
    return readPage<KeywordRecord[]>(await fetch(dataUrl("keywords", projectId, { page, page_size: 20, category, is_active: isActive === undefined ? undefined : String(isActive) }), { cache: "no-store" }));
  },
  async keywordCategories(projectId: string): Promise<string[]> {
    return readResponse<string[]>(await fetch(dataUrl("keyword-categories", projectId), { cache: "no-store" }));
  },
  async contentVersionOptions(projectId: string): Promise<ApiEnvelope<ContentVersionRecord[]>> {
    return readPage<ContentVersionRecord[]>(await fetch(dataUrl("content-versions", projectId, { page: 1, page_size: 100 }), { cache: "no-store" }));
  },
  async createKeyword(projectId: string, input: Record<string, unknown>): Promise<KeywordRecord> {
    return readResponse<KeywordRecord>(await fetch(dataUrl("keywords", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async updateKeyword(projectId: string, id: string, input: Record<string, unknown>): Promise<KeywordRecord> {
    return readResponse<KeywordRecord>(await fetch(dataUrl("keyword", projectId, { id }), {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async deactivateKeyword(projectId: string, id: string): Promise<KeywordRecord> {
    return readResponse<KeywordRecord>(await fetch(dataUrl("keyword", projectId, { id }), { method: "DELETE" }));
  },
  async samples(projectId: string, page = 1, status?: string): Promise<ApiEnvelope<SampleRecord[]>> {
    return readPage<SampleRecord[]>(await fetch(dataUrl("samples", projectId, { page, page_size: 20, status }), { cache: "no-store" }));
  },
  async tasks(projectId: string, page = 1, roundId?: string, status?: string): Promise<ApiEnvelope<MonitoringTaskRecord[]>> {
    return readPage<MonitoringTaskRecord[]>(await fetch(dataUrl("tasks", projectId, { page, page_size: WORKBENCH_PAGE_SIZE, round_id: roundId, status }), { cache: "no-store" }));
  },
  async createSample(projectId: string, taskId: string, input: Record<string, unknown>): Promise<ManualSampleCreated> {
    return readResponse<ManualSampleCreated>(await fetch(dataUrl("sample-create", projectId, { id: taskId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async uploadEvidence(projectId: string, sampleId: string, file: File, fileType: string): Promise<EvidenceUploadResult> {
    const form = new FormData();
    form.set("sample_id", sampleId);
    form.set("file_type", fileType);
    form.set("file", file);
    return readResponse<EvidenceUploadResult>(await fetch(`/internal/workbench/evidence/upload?project_id=${encodeURIComponent(projectId)}`, {
      method: "POST", body: form,
    }));
  },
  async diagnostics(projectId: string, page = 1, failureCode?: string): Promise<ApiEnvelope<DiagnosticSample[]>> {
    return readPage<DiagnosticSample[]>(await fetch(dataUrl("diagnostics", projectId, { page, page_size: WORKBENCH_PAGE_SIZE, failure_code: failureCode }), { cache: "no-store" }));
  },
  async traceChain(projectId: string, traceId: string): Promise<TraceChain> {
    return readResponse<TraceChain>(await fetch(dataUrl("trace", projectId, { trace_id: traceId }), { cache: "no-store" }));
  },
  async sample(projectId: string, id: string): Promise<SampleDetail> {
    return readResponse<SampleDetail>(await fetch(dataUrl("sample", projectId, { id }), { cache: "no-store" }));
  },
  async downloadEvidence(projectId: string, evidenceId: string): Promise<void> {
    const response = await fetch(`/internal/workbench/evidence/${encodeURIComponent(evidenceId)}?project_id=${encodeURIComponent(projectId)}`, { cache: "no-store" });
    if (!response.ok) { await readResponse(response); return; }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const name = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)/)?.[1] ?? `evidence-${evidenceId}`;
    const link = document.createElement("a");
    link.href = url; link.download = name; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  async reviewSample(projectId: string, id: string, result: "hit" | "miss", note: string): Promise<{ sample_id: string; status: string }> {
    return readResponse<{ sample_id: string; status: string }>(await fetch(dataUrl("sample-review", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ review_result: result, review_note: note || null }),
    }));
  },
  async resampleSample(projectId: string, id: string): Promise<{ task_id: string; round_id: string; sampling_no: number; status: string; source_sample_id: string }> {
    return readResponse<{ task_id: string; round_id: string; sampling_no: number; status: string; source_sample_id: string }>(await fetch(dataUrl("sample-resample", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async reanalyzeSample(projectId: string, id: string): Promise<{ sample_id: string; status: string; brand_mentioned: boolean; brand_identified: boolean; citation_count: number; analysis_version?: string | null }> {
    return readResponse<{ sample_id: string; status: string; brand_mentioned: boolean; brand_identified: boolean; citation_count: number; analysis_version?: string | null }>(await fetch(dataUrl("sample-reanalyze", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async citations(projectId: string, page = 1, status?: string): Promise<ApiEnvelope<CitationRecord[]>> {
    return readPage<CitationRecord[]>(await fetch(dataUrl("citations", projectId, { page, page_size: 20, status }), { cache: "no-store" }));
  },
  async unknownDomains(projectId: string, page = 1): Promise<ApiEnvelope<UnknownDomainRecord[]>> {
    return readPage<UnknownDomainRecord[]>(await fetch(dataUrl("unknown-domains", projectId, { page, page_size: 20 }), { cache: "no-store" }));
  },
  async sourceReviews(projectId: string, status?: string, page = 1): Promise<ApiEnvelope<SourceReviewRecord[]>> {
    return readPage<SourceReviewRecord[]>(await fetch(dataUrl("source-reviews", projectId, { status, page, page_size: 20 }), { cache: "no-store" }));
  },
  async classifySourceReview(projectId: string, reviewId: string, sourceCategory: string, note?: string): Promise<SourceReviewRecord> {
    return readResponse<SourceReviewRecord>(await fetch(dataUrl("source-review-classify", projectId, { id: reviewId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_category: sourceCategory, review_note: note || null }),
    }));
  },
  async factTypes(projectId: string): Promise<FactTypeOption[]> {
    return readResponse<FactTypeOption[]>(await fetch(dataUrl("fact-types", projectId), { cache: "no-store" }));
  },
  async facts(projectId: string, factType?: string, approvalStatus?: string, page = 1): Promise<ApiEnvelope<FactRecord[]>> {
    return readPage<FactRecord[]>(await fetch(dataUrl("facts", projectId, { fact_type: factType, approval_status: approvalStatus, page, page_size: 100 }), { cache: "no-store" }));
  },
  async factVersions(projectId: string, factId: string): Promise<ApiEnvelope<FactVersionRecord[]>> {
    return readPage<FactVersionRecord[]>(await fetch(dataUrl("fact-versions", projectId, { id: factId, page_size: 100 }), { cache: "no-store" }));
  },
  async createFact(projectId: string, input: Record<string, unknown>): Promise<FactRecord> {
    return readResponse<FactRecord>(await fetch(dataUrl("fact", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async updateFact(projectId: string, id: string, input: Record<string, unknown>): Promise<FactRecord> {
    return readResponse<FactRecord>(await fetch(dataUrl("fact", projectId, { id }), {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async submitFact(projectId: string, id: string): Promise<FactRecord> {
    return readResponse<FactRecord>(await fetch(dataUrl("fact-submit", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async reviewFact(projectId: string, id: string, input: Record<string, unknown>): Promise<FactRecord> {
    return readResponse<FactRecord>(await fetch(dataUrl("fact-review", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async expireFact(projectId: string, id: string): Promise<FactRecord> {
    return readResponse<FactRecord>(await fetch(dataUrl("fact-expire", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async factClaims(projectId: string, sampleId?: string, verdict?: string, page = 1): Promise<ApiEnvelope<FactClaimRecord[]>> {
    return readPage<FactClaimRecord[]>(await fetch(dataUrl("fact-claims", projectId, { sample_id: sampleId, verdict, page, page_size: 100 }), { cache: "no-store" }));
  },
  async createFactClaim(projectId: string, sampleId: string, input: Record<string, unknown>): Promise<FactClaimRecord> {
    return readResponse<FactClaimRecord>(await fetch(dataUrl("fact-claim", projectId, { sample_id: sampleId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async reviewFactClaim(projectId: string, id: string, input: Record<string, unknown>): Promise<FactClaimRecord> {
    return readResponse<FactClaimRecord>(await fetch(dataUrl("fact-claim", projectId, { id }), {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async correctionTasks(projectId: string): Promise<ApiEnvelope<CorrectionTaskRecord[]>> {
    return readPage<CorrectionTaskRecord[]>(await fetch(dataUrl("correction-tasks", projectId, { page_size: 100 }), { cache: "no-store" }));
  },
  async reviewCitation(projectId: string, id: string, input: Record<string, unknown>): Promise<CitationRecord> {
    return readResponse<CitationRecord>(await fetch(dataUrl("citation", projectId, { id }), {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async overrideCitationPageType(projectId: string, id: string, pageType: string): Promise<CitationRecord> {
    return readResponse<CitationRecord>(await fetch(dataUrl("citation-page-type", projectId, { id }), {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ page_type: pageType }),
    }));
  },
  async publishTasks(projectId: string, page = 1): Promise<ApiEnvelope<PublishTaskRecord[]>> {
    return readPage<PublishTaskRecord[]>(await fetch(dataUrl("publish-tasks", projectId, { page, page_size: 20 }), { cache: "no-store" }));
  },
  async publishAccounts(projectId: string): Promise<ApiEnvelope<PublishAccountRecord[]>> {
    return readPage<PublishAccountRecord[]>(await fetch(dataUrl("publish-accounts", projectId, { page_size: 100 }), { cache: "no-store" }));
  },
  async createPublishAccount(projectId: string, input: Record<string, unknown>): Promise<PublishAccountRecord> {
    return readResponse<PublishAccountRecord>(await fetch(dataUrl("publish-account", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async approvedVersions(projectId: string): Promise<ApiEnvelope<ContentVersionRecord[]>> {
    return readPage<ContentVersionRecord[]>(await fetch(dataUrl("content-versions", projectId, { status: "approved", page_size: 100 }), { cache: "no-store" }));
  },
  async contentVersions(projectId: string, status?: string, page = 1): Promise<ApiEnvelope<ContentVersionRecord[]>> {
    return readPage<ContentVersionRecord[]>(await fetch(dataUrl("content-versions", projectId, { status, page, page_size: 20 }), { cache: "no-store" }));
  },
  async contentVersion(projectId: string, id: string): Promise<ContentVersionDetail> {
    return readResponse<ContentVersionDetail>(await fetch(dataUrl("content-version", projectId, { id }), { cache: "no-store" }));
  },
  async contentExport(projectId: string, id: string): Promise<ContentExportPackage> {
    return readResponse<ContentExportPackage>(await fetch(dataUrl("content-export", projectId, { id }), { cache: "no-store" }));
  },
  async contentReviews(projectId: string, id: string): Promise<ApiEnvelope<ContentReviewRecord[]>> {
    return readPage<ContentReviewRecord[]>(await fetch(dataUrl("content-reviews", projectId, { id }), { cache: "no-store" }));
  },
  async contentLinks(projectId: string, id: string): Promise<ContentVersionLinks> {
    return readResponse<ContentVersionLinks>(await fetch(dataUrl("content-links", projectId, { id }), { cache: "no-store" }));
  },
  async updateContentLinks(projectId: string, id: string, input: Record<string, unknown>): Promise<ContentVersionLinks> {
    return readResponse<ContentVersionLinks>(await fetch(dataUrl("content-links", projectId, { id }), {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async changeContentStatus(projectId: string, id: string, status: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(dataUrl("content-status", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }),
    }));
  },
  async contentAction(projectId: string, kind: "content-item" | "content-version-create" | "content-submit" | "content-review", input: Record<string, unknown>, id?: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(dataUrl(kind, projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async publishAction(projectId: string, kind: "publish-task" | "publish-attempt" | "publish-receipt" | "publish-verify", input: Record<string, unknown>, id?: string): Promise<unknown> {
    return readResponse<unknown>(await fetch(dataUrl(kind, projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async freezeSnapshot(projectId: string, roundId: string): Promise<StatSnapshotRecord> {
    return readResponse<StatSnapshotRecord>(await fetch(dataUrl("stat-snapshot", projectId, { round_id: roundId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async statsOverview(projectId: string, answerKind?: AnswerKindParam, roundId?: string, questionType?: QuestionTypeParam): Promise<StatsOverview> {
    return readResponse<StatsOverview>(await fetch(dataUrl("stats-overview", projectId, { answer_kind: answerKind, round_id: roundId, question_type: questionType }), { cache: "no-store" }));
  },
  async statsOverviewByAnswerKind(projectId: string, roundId?: string, questionType?: QuestionTypeParam): Promise<StatsAnswerKindOverview[]> {
    return readResponse<StatsAnswerKindOverview[]>(await fetch(dataUrl("stats-overview-by-answer-kind", projectId, { round_id: roundId, question_type: questionType }), { cache: "no-store" }));
  },
  async statsByEngine(projectId: string, answerKind?: AnswerKindParam, roundId?: string, questionType?: QuestionTypeParam): Promise<StatsEngine[]> {
    return readResponse<StatsEngine[]>(await fetch(dataUrl("stats-by-engine", projectId, { answer_kind: answerKind, round_id: roundId, question_type: questionType }), { cache: "no-store" }));
  },
  async statsByQuestion(projectId: string, answerKind?: AnswerKindParam, roundId?: string, questionType?: QuestionTypeParam): Promise<StatsQuestion[]> {
    return readResponse<StatsQuestion[]>(await fetch(dataUrl("stats-by-question", projectId, { answer_kind: answerKind, round_id: roundId, question_type: questionType }), { cache: "no-store" }));
  },
  async statsEngineHealth(projectId: string, roundId?: string): Promise<EngineHealth[]> {
    return readResponse<EngineHealth[]>(await fetch(dataUrl("stats-engine-health", projectId, { round_id: roundId }), { cache: "no-store" }));
  },
  async statsGeo(projectId: string, answerKind?: AnswerKindParam, roundId?: string, questionType?: QuestionTypeParam): Promise<GeoOverview> {
    return readResponse<GeoOverview>(await fetch(dataUrl("stats-geo", projectId, { answer_kind: answerKind, round_id: roundId, question_type: questionType }), { cache: "no-store" }));
  },
  async statsSources(projectId: string, limit = 50, roundId?: string, questionType?: QuestionTypeParam): Promise<StatsSource[]> {
    return readResponse<StatsSource[]>(await fetch(dataUrl("stats-sources", projectId, { limit, round_id: roundId, question_type: questionType }), { cache: "no-store" }));
  },
  async statsMonthly(projectId: string, month?: string): Promise<MonthlyReport> {
    return readResponse<MonthlyReport>(await fetch(dataUrl("stats-monthly", projectId, { month }), { cache: "no-store" }));
  },
  async leadFunnel(projectId: string, startDate?: string, endDate?: string): Promise<LeadFunnel> {
    return readResponse<LeadFunnel>(await fetch(dataUrl("lead-funnel", projectId, { start_date: startDate, end_date: endDate }), { cache: "no-store" }));
  },
  async statsPublishVisibility(projectId: string, limit = 50): Promise<StatsPublishVisibility[]> {
    return readResponse<StatsPublishVisibility[]>(await fetch(dataUrl("stats-publish-visibility", projectId, { limit }), { cache: "no-store" }));
  },
  async runPublishVisibilityCheck(projectId: string, limit = 20): Promise<{ checked: number; matched: number; unmatched: number; failed: number }> {
    return readResponse(await fetch(dataUrl("publish-visibility-check", projectId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit }),
    }));
  },
  async downloadStats(projectId: string, answerKind?: AnswerKindParam, roundId?: string, questionType?: QuestionTypeParam): Promise<void> {
    const response = await fetch(dataUrl("stats-export", projectId, { answer_kind: answerKind, round_id: roundId, question_type: questionType }), { cache: "no-store" });
    if (!response.ok) { await readResponse(response); return; }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)/)?.[1] ?? "stats.csv";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  async competitors(projectId: string, page = 1): Promise<ApiEnvelope<CompetitorRecord[]>> {
    return readPage<CompetitorRecord[]>(await fetch(dataUrl("competitors", projectId, { page, page_size: 50 }), { cache: "no-store" }));
  },
  async saveCompetitor(projectId: string, input: Record<string, unknown>, id?: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(dataUrl(id ? "competitor" : "competitors", projectId, { id }), {
      method: id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async brandProfile(projectId: string): Promise<BrandProfileRecord> {
    return readResponse<BrandProfileRecord>(await fetch(dataUrl("brand-profile", projectId), { cache: "no-store" }));
  },
  async saveBrandProfile(projectId: string, input: Record<string, unknown>): Promise<BrandProfileRecord> {
    return readResponse<BrandProfileRecord>(await fetch(dataUrl("brand-profile", projectId), {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async metricDefinitions(projectId: string, page = 1): Promise<ApiEnvelope<MetricDefinitionRecord[]>> {
    return readPage<MetricDefinitionRecord[]>(await fetch(dataUrl("metric-definitions", projectId, { page, page_size: 100 }), { cache: "no-store" }));
  },
  async saveMetric(projectId: string, input: Record<string, unknown>, id?: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(dataUrl(id ? "metric-definition" : "metric-definitions", projectId, { id }), {
      method: id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async members(projectId: string, page = 1): Promise<ApiEnvelope<MemberRecord[]>> {
    return readPage<MemberRecord[]>(await fetch(dataUrl("members", projectId, { page, page_size: MEMBERS_PAGE_SIZE }), { cache: "no-store" }));
  },
  async memberCandidates(projectId: string, q = ""): Promise<UserCandidate[]> {
    return readResponse<UserCandidate[]>(await fetch(dataUrl("member-candidates", projectId, { q }), { cache: "no-store" }));
  },
  async addMember(projectId: string, userId: string, roleCode: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(dataUrl("members", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: userId, role_code: roleCode }),
    }));
  },
  async changeMemberRole(projectId: string, memberId: string, roleCode: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(dataUrl("member", projectId, { id: memberId }), {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role_code: roleCode }),
    }));
  },
  async removeMember(projectId: string, memberId: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(dataUrl("member", projectId, { id: memberId }), { method: "DELETE" }));
  },
  async plans(projectId: string, page = 1): Promise<ApiEnvelope<PlanRecord[]>> {
    return readPage<PlanRecord[]>(await fetch(dataUrl("plans", projectId, { page, page_size: 50 }), { cache: "no-store" }));
  },
  async savePlan(projectId: string, input: Record<string, unknown>, id?: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(dataUrl(id ? "plan" : "plans", projectId, { id }), {
      method: id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async opportunities(projectId: string, page = 1, filters: { status?: string; gap_type?: string } = {}): Promise<ApiEnvelope<OpportunityRecord[]>> {
    return readPage<OpportunityRecord[]>(await fetch(dataUrl("opportunities", projectId, { page, page_size: 20, status: filters.status, gap_type: filters.gap_type }), { cache: "no-store" }));
  },
  async saveOpportunity(projectId: string, input: Record<string, unknown>, id?: string): Promise<OpportunityRecord> {
    return readResponse<OpportunityRecord>(await fetch(dataUrl(id ? "opportunity" : "opportunities", projectId, { id }), {
      method: id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async pages(projectId: string): Promise<ApiEnvelope<PageRecord[]>> {
    return readPage<PageRecord[]>(await fetch(dataUrl("pages", projectId, { page: 1, page_size: 100 }), { cache: "no-store" }));
  },
  async siteDiagnostics(projectId: string): Promise<SiteDiagnosticsSummary> {
    return readResponse<SiteDiagnosticsSummary>(await fetch(dataUrl("site-diagnostics", projectId), { cache: "no-store" }));
  },
  async checkPage(projectId: string, pageId: string): Promise<PageCheckResult> {
    return readResponse<PageCheckResult>(await fetch(dataUrl("page-check", projectId, { id: pageId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async quotes(projectId: string, page = 1): Promise<ApiEnvelope<QuoteRecord[]>> {
    return readPage<QuoteRecord[]>(await fetch(dataUrl("quotes", projectId, { page, page_size: 50 }), { cache: "no-store" }));
  },
  async saveQuote(projectId: string, input: Record<string, unknown>, id?: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(dataUrl(id ? "quote" : "quotes", projectId, { id }), {
      method: id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async reviewQuote(projectId: string, id: string, decision: "approved" | "rejected", note?: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(dataUrl("quote-review", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, note: note || null }),
    }));
  },
  async budgetApprovals(projectId: string, page = 1, filters: { status?: string; category?: string } = {}): Promise<ApiEnvelope<BudgetApproval[]>> {
    return readPage<BudgetApproval[]>(await fetch(dataUrl("budget-approvals", projectId, { page, page_size: 20, status: filters.status, category: filters.category }), { cache: "no-store" }));
  },
  async createBudgetApproval(projectId: string, input: Record<string, unknown>): Promise<BudgetApproval> {
    return readResponse<BudgetApproval>(await fetch(dataUrl("budget-approvals", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async reviewBudgetApproval(projectId: string, id: string, decision: "approved" | "rejected", note?: string): Promise<BudgetApproval> {
    return readResponse<BudgetApproval>(await fetch(dataUrl("budget-review", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, note: note || null }),
    }));
  },
  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    const response = await fetch("/internal/session/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const code = typeof payload?.error?.code === "string" ? payload.error.code : "upstream_error";
      throw new WorkbenchApiError(response.status, code, payload?.error?.message || errorMessage(response.status, code));
    }
  },
  async resetUserPassword(userId: string, newPassword: string): Promise<void> {
    await readResponse<{ ok: boolean }>(await fetch(`/internal/workbench/system?kind=reset-password&user_id=${encodeURIComponent(userId)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ new_password: newPassword }),
    }));
  },
  async resetLoginThrottle(username: string, clientIp?: string): Promise<void> {
    await readResponse<{ ok: boolean }>(await fetch("/internal/workbench/system?kind=throttle-reset", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, client_ip: clientIp || null }),
    }));
  },
  async logout(): Promise<void> {
    await fetch("/internal/session", { method: "DELETE" });
  },
};
