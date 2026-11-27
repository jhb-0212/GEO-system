import type { AlertEventRecord, AlertRuleRecord, ApiEnvelope, AuditLogRecord, BatchGenerationResult, BrandGovernanceRecord, BrandProfileRecord, BudgetApproval, ChannelAnomalyList, ChannelDetailRecord, ChannelRecord, CitationAnswerOption, CitationRecord, CompanyProfileRecord, CompanyProfileDraftRecord, CompanyDraftModelRecord, CompanyDraftModelTestRecord, CompetitorRecord, AdaptationReport, BrandSearchReport, CompetitorSourceReport, ContentExportPackage, ContentFormatReport, ContentReviewRecord, ContentVersionDetail, ContentVersionLinks, ContentVersionRecord, CorrectionTaskRecord, CrawlerEventImportResult, DiagnosticSample, EngineConnectionResult, EngineEntryRecord, EngineHealth, EngineRecord, EvidenceUploadResult, FactClaimRecord, FactPushRecord, FactRecord, FactTypeOption, FactVersionRecord, FaqRecord, GeoOverview, GenerationBatchRecord, GenerationBatchSummary, GenerationGateAction, GenerationGateRecord, HealthCheckRun, HealthCheckRunSummary, KeywordRecord, Lead, LeadFunnel, LeadVisitorReport, ManualFailureCreated, ManualSampleCreated, MaterialRecord, MemberRecord, MetricDefinitionRecord, MonitoringRound, MonitoringTaskRecord, MonthlyReport, MonthlyReportSnapshot, MonthlyReportSnapshotSummary, OAuthAuthorizeResult, OAuthConnectionRecord, OAuthProviderRecord, OpportunityRecord, OpportunitySuggestionRecord, PageApprovalRecord, PageCheckBatchResult, PageCheckResult, DashboardTracks, GeoBoard, PageRecord, PlanRecord, SiteRecord, Project, PublishAccountRecord, PublishReceiptRecord, PublishTaskRecord, QuestionRecord, QuestionVersionRecord, QuoteRecord, SellingPointRecord, SellingPointSummary, RoundCompletionResult, SampleDetail, SampleRecord, SiteDiagnosticsSummary, SourceReviewRecord, StatSnapshotRecord, StatsAnswerKindOverview, StatsEngine, StatsEntry, StatsOverview, StatsQuestion, StatsSource, StatsPublishVisibility, TraceChain, TrafficEventImportResult, TrafficSummary, UnknownDomainRecord, UserCandidate, UserAccountRecord, WorkbenchSnapshot } from "./types";
import type { RetestPlanRecord, RetestPlanRunResult } from "./types";
import type {
  KnowledgeCandidateFactRecord,
  KnowledgeChunkRecord,
  KnowledgeDocumentRecord,
  KnowledgeSearchResult,
} from "./types";
import type {
  QuestionCandidateAcceptResult,
  QuestionCandidateImportResult,
  QuestionCandidateMineResult,
  QuestionCandidateRecord,
} from "./types";
import type { ConsumptionSummary, ConsumptionEvent } from "./types";
import type { TodoCenter, TodoRange } from "./types";
import type { ReportShareCreateResult, ReportShareRecord } from "./types";
import type {
  IndustryStatus, IndustryPresetOption, OnboardingPreview, OnboardingApplyResult,
  OrganizationSettings, OrganizationUsageTrend, OrganizationSummary, OrganizationOverviewResult, OrganizationMember,
} from "./types";
import type {
  CertificationRecord,
  ChannelDerivationRecord,
  ContentQualityReport,
  ContentGeoScoreRecord,
  ContentTemplateRecord,
  DiagnosisReportRecord,
  DistributionBatchRecord,
  EncyclopediaEntryRecord,
  EncyclopediaReference,
  MasterDerivationList,
  MyProfileRecord,
  ProjectContactRecord,
  PublishBoardBatchesRecord,
  PublishBoardRecord,
  PublishClosureRecord,
  LeadAutoreplyRecord,
  SentimentItemRecord,
  SentimentSummaryRecord,
  SourceCoverage,
  SourceTiers,
  AnswerSnapshotSummary,
  PageTypeReclassifyResult,
  PageTitleBackfillResult,
  ContentFreshness,
  ContentConsistencyReport,
  AcceptanceContract,
  BrandRelatedPreview,
  SentimentSampling,
  SentimentConsensus,
  SourceDomainsOverview,
  PageVisibilityReport,
  DistributionCandidates,
  AnswerSnapshotDetail,
  SourceMatrix,
  StartupMaterialsRecord,
  TemplateGenerationRecord,
} from "./types";

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

function onboardingUrl(kind: string, projectId: string) {
  const query = new URLSearchParams({ kind, project_id: projectId });
  return `/internal/workbench/onboarding?${query}`;
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
  async todos(projectId: string, range: TodoRange = "all", limit = 20, signal?: AbortSignal): Promise<TodoCenter> {
    const query = new URLSearchParams({
      project_id: projectId,
      range,
      limit: String(limit),
    });
    return readResponse<TodoCenter>(
      await fetch(`/internal/workbench/todos?${query}`, { cache: "no-store", signal }),
    );
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
  async faqReviewQueue(projectId: string, options: { category?: string; q?: string; page?: number; pageSize?: number } = {}): Promise<ApiEnvelope<FaqRecord[]>> {
    return readPage<FaqRecord[]>(await fetch(dataUrl("faq-review-queue", projectId, {
      category: options.category,
      q: options.q?.trim() || undefined,
      page: options.page ?? 1,
      page_size: options.pageSize ?? 20,
    }), { cache: "no-store" }));
  },
  async submitFaqReview(projectId: string, id: string): Promise<FaqRecord> {
    return readResponse<FaqRecord>(await fetch(dataUrl("faq-submit-review", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }));
  },
  async reviewFaq(projectId: string, id: string, action: "approve" | "reject", comment?: string | null): Promise<FaqRecord> {
    return readResponse<FaqRecord>(await fetch(dataUrl("faq-review", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, comment: comment || null }),
    }));
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
  async materials(projectId: string, category?: string, page = 1, groupName?: string): Promise<ApiEnvelope<MaterialRecord[]>> {
    return readPage<MaterialRecord[]>(await fetch(dataUrl("materials", projectId, { category, page, page_size: 100, group_name: groupName }), { cache: "no-store" }));
  },
  async uploadMaterial(projectId: string, form: FormData): Promise<MaterialRecord> {
    return readResponse<MaterialRecord>(await fetch(`/internal/workbench/materials?project_id=${encodeURIComponent(projectId)}`, {
      method: "POST", body: form,
    }));
  },
  async knowledgeDocuments(projectId: string, page = 1): Promise<ApiEnvelope<KnowledgeDocumentRecord[]>> {
    return readPage<KnowledgeDocumentRecord[]>(await fetch(dataUrl("knowledge-documents", projectId, { page, page_size: 100 }), { cache: "no-store" }));
  },
  async knowledgeChunks(projectId: string, documentId: string): Promise<ApiEnvelope<KnowledgeChunkRecord[]>> {
    return readPage<KnowledgeChunkRecord[]>(await fetch(dataUrl("knowledge-document-chunks", projectId, { id: documentId, page: 1, page_size: 100 }), { cache: "no-store" }));
  },
  async knowledgeCandidates(projectId: string, status?: string, documentId?: string): Promise<ApiEnvelope<KnowledgeCandidateFactRecord[]>> {
    return readPage<KnowledgeCandidateFactRecord[]>(await fetch(dataUrl("knowledge-candidates", projectId, { status, id: documentId, page: 1, page_size: 100 }), { cache: "no-store" }));
  },
  async knowledgeSearch(projectId: string, query: string, topK = 8): Promise<KnowledgeSearchResult> {
    return readResponse<KnowledgeSearchResult>(await fetch(dataUrl("knowledge-search", projectId, { q: query, top_k: topK }), { cache: "no-store" }));
  },
  async parseKnowledgeMaterial(projectId: string, materialId: string): Promise<KnowledgeDocumentRecord> {
    return readResponse<KnowledgeDocumentRecord>(await fetch("/internal/workbench/knowledge", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, action: "parse", material_id: materialId }),
    }));
  },
  async acceptKnowledgeCandidate(projectId: string, id: string, input: Record<string, unknown> = {}): Promise<{ candidate: KnowledgeCandidateFactRecord; fact_id: string; fact_status: string }> {
    return readResponse<{ candidate: KnowledgeCandidateFactRecord; fact_id: string; fact_status: string }>(await fetch("/internal/workbench/knowledge", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, action: "accept", candidate_id: id, ...input }),
    }));
  },
  async rejectKnowledgeCandidate(projectId: string, id: string, note?: string): Promise<KnowledgeCandidateFactRecord> {
    return readResponse<KnowledgeCandidateFactRecord>(await fetch("/internal/workbench/knowledge", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, action: "reject", candidate_id: id, note }),
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
  async myProfile(): Promise<MyProfileRecord> {
    return readResponse<MyProfileRecord>(await fetch("/internal/workbench/profile", { cache: "no-store" }));
  },
  async saveMyProfile(input: Partial<Pick<MyProfileRecord, "display_name" | "job_title" | "phone" | "wechat">>): Promise<MyProfileRecord> {
    return readResponse<MyProfileRecord>(await fetch("/internal/workbench/profile", {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async distributionBatches(projectId: string, page = 1): Promise<{ data: DistributionBatchRecord[]; meta: { page: number; page_size: number; total: number } }> {
    // 与 sentimentItems 同理：分页体本身就是 { data, meta }，不走 readResponse 解包。
    const response = await fetch(`/internal/workbench/distribution?project_id=${encodeURIComponent(projectId)}&page=${page}`, { cache: "no-store" });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.error?.message ?? "批次加载失败");
    return { data: payload?.data ?? [], meta: payload?.meta ?? { page: 1, page_size: 20, total: 0 } };
  },
  async createDistributionBatch(projectId: string, input: { name: string; content_version_ids: string[]; channel_ids: string[]; expected_engine_ids?: string[]; notes?: string | null }): Promise<DistributionBatchRecord> {
    return readResponse<DistributionBatchRecord>(await fetch(`/internal/workbench/distribution?project_id=${encodeURIComponent(projectId)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async distributionBatchAction(projectId: string, batchId: string, action: "recheck" | "dispatch"): Promise<DistributionBatchRecord> {
    return readResponse<DistributionBatchRecord>(await fetch(`/internal/workbench/distribution/batch?project_id=${encodeURIComponent(projectId)}&batch_id=${encodeURIComponent(batchId)}&action=${action}`, {
      method: "POST",
    }));
  },
  async publishClosure(projectId: string): Promise<PublishClosureRecord> {
    return readResponse<PublishClosureRecord>(await fetch(`/internal/workbench/closure?project_id=${encodeURIComponent(projectId)}`, { cache: "no-store" }));
  },
  async contentQuality(projectId: string, id: string): Promise<ContentQualityReport> {
    return readResponse<ContentQualityReport>(await fetch(dataUrl("content-quality", projectId, { id }), { cache: "no-store" }));
  },
  async contentGeoScore(projectId: string, id: string): Promise<ContentGeoScoreRecord> {
    return readResponse<ContentGeoScoreRecord>(await fetch(dataUrl("content-geo-score", projectId, { id }), { cache: "no-store" }));
  },
  async contentDerivations(projectId: string, itemId: string): Promise<MasterDerivationList> {
    return readResponse<MasterDerivationList>(await fetch(`/internal/workbench/adaptation?project_id=${encodeURIComponent(projectId)}&item_id=${encodeURIComponent(itemId)}`, { cache: "no-store" }));
  },
  async consistencyDerivations(projectId: string, staleOnly = true): Promise<{ data: ChannelDerivationRecord[]; meta: { page: number; page_size: number; total: number } }> {
    // 分页体是 { data, meta } 本体，同样不套 readResponse 解包。
    const query = `project_id=${encodeURIComponent(projectId)}&view=consistency&stale_only=${staleOnly ? "true" : "false"}`;
    const response = await fetch(`/internal/workbench/adaptation?${query}`, { cache: "no-store" });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.error?.message ?? "一致性清单加载失败");
    return { data: (payload?.data ?? []) as ChannelDerivationRecord[], meta: payload?.meta ?? { page: 1, page_size: 20, total: 0 } };
  },
  async deriveToChannels(projectId: string, itemId: string, channelIds: string[], titleSuffix?: string | null): Promise<{ created: ChannelDerivationRecord[] }> {
    return readResponse<{ created: ChannelDerivationRecord[] }>(await fetch(`/internal/workbench/adaptation?project_id=${encodeURIComponent(projectId)}&item_id=${encodeURIComponent(itemId)}&action=derive`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ channel_ids: channelIds, title_suffix: titleSuffix || null }),
    }));
  },
  async syncDerivation(projectId: string, itemId: string, derivationId: string): Promise<ChannelDerivationRecord> {
    return readResponse<ChannelDerivationRecord>(await fetch(`/internal/workbench/adaptation?project_id=${encodeURIComponent(projectId)}&item_id=${encodeURIComponent(itemId)}&action=sync&derivation_id=${encodeURIComponent(derivationId)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }));
  },
  async contentTemplates(projectId: string, includeInactive = false): Promise<{ data: ContentTemplateRecord[]; meta: { page: number; page_size: number; total: number } }> {
    // 与 distributionBatches 同理：分页体是 { data, meta } 本体，不再套 readResponse 解包。
    const query = `project_id=${encodeURIComponent(projectId)}&page=1&page_size=20${includeInactive ? "&include_inactive=true" : ""}`;
    const response = await fetch(`/internal/workbench/templates?${query}`, { cache: "no-store" });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.error?.message ?? "模板加载失败");
    return { data: (payload?.data ?? []) as ContentTemplateRecord[], meta: payload?.meta ?? { page: 1, page_size: 20, total: 0 } };
  },
  async createContentTemplate(projectId: string, input: { name: string; channel_category?: string | null; question_type?: string | null; skeleton: string; notes?: string | null }): Promise<ContentTemplateRecord> {
    return readResponse<ContentTemplateRecord>(await fetch(`/internal/workbench/templates?project_id=${encodeURIComponent(projectId)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async updateContentTemplate(projectId: string, templateId: string, input: Record<string, unknown>): Promise<ContentTemplateRecord> {
    return readResponse<ContentTemplateRecord>(await fetch(`/internal/workbench/templates?project_id=${encodeURIComponent(projectId)}&template_id=${encodeURIComponent(templateId)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async generateFromTemplate(projectId: string, templateId: string, input: { title: string; slot_values: Record<string, string> }): Promise<TemplateGenerationRecord> {
    return readResponse<TemplateGenerationRecord>(await fetch(`/internal/workbench/templates?project_id=${encodeURIComponent(projectId)}&template_id=${encodeURIComponent(templateId)}&action=generate`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async publishBoard(projectId: string): Promise<PublishBoardRecord> {
    return readResponse<PublishBoardRecord>(await fetch(`/internal/workbench/publish-board?project_id=${encodeURIComponent(projectId)}`, { cache: "no-store" }));
  },
  async publishBoardBatches(projectId: string, limit = 50): Promise<PublishBoardBatchesRecord> {
    return readResponse<PublishBoardBatchesRecord>(await fetch(`/internal/workbench/publish-board/batches?project_id=${encodeURIComponent(projectId)}&limit=${limit}`, { cache: "no-store" }));
  },
  async createCorrectiveBatch(projectId: string, citationId: string, input: { name?: string | null; note?: string | null } = {}): Promise<unknown> {
    return readResponse<unknown>(await fetch(`/internal/workbench/sentiment/corrective?project_id=${encodeURIComponent(projectId)}&citation_id=${encodeURIComponent(citationId)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async leadAutoreply(projectId: string): Promise<LeadAutoreplyRecord> {
    return readResponse<LeadAutoreplyRecord>(await fetch(`/internal/workbench/leads/autoreply?project_id=${encodeURIComponent(projectId)}`, { cache: "no-store" }));
  },
  async saveLeadAutoreply(projectId: string, input: { enabled: boolean; script: string; include_contact: boolean; note?: string | null }): Promise<LeadAutoreplyRecord> {
    return readResponse<LeadAutoreplyRecord>(await fetch(`/internal/workbench/leads/autoreply?project_id=${encodeURIComponent(projectId)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async sentimentSummary(projectId: string): Promise<SentimentSummaryRecord> {
    return readResponse<SentimentSummaryRecord>(await fetch(`/internal/workbench/sentiment?view=summary&project_id=${encodeURIComponent(projectId)}`, { cache: "no-store" }));
  },
  async sentimentItems(projectId: string, filters: Record<string, string | undefined> = {}): Promise<{ data: SentimentItemRecord[]; meta: { page: number; page_size: number; total: number } }> {
    const query = new URLSearchParams({ project_id: projectId, view: "items" });
    for (const [key, value] of Object.entries(filters)) if (value) query.set(key, value);
    // 分页接口返回的是 { data, meta } 本体，不能再套 readResponse 的 .data 解包。
    const response = await fetch(`/internal/workbench/sentiment?${query}`, { cache: "no-store" });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.error?.message ?? "情绪原文加载失败");
    return { data: (payload?.data ?? []) as SentimentItemRecord[], meta: payload?.meta ?? { page: 1, page_size: 20, total: 0 } };
  },
  async labelSentiment(projectId: string, citationId: string, input: { polarity: string; note?: string | null }): Promise<unknown> {
    return readResponse<unknown>(await fetch(`/internal/workbench/sentiment?project_id=${encodeURIComponent(projectId)}&citation_id=${encodeURIComponent(citationId)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async diagnosisReport(projectId: string, filters: Record<string, string | undefined> = {}): Promise<DiagnosisReportRecord> {
    const query = new URLSearchParams({ project_id: projectId });
    for (const [key, value] of Object.entries(filters)) if (value) query.set(key, value);
    return readResponse<DiagnosisReportRecord>(await fetch(`/internal/workbench/diagnosis?${query}`, { cache: "no-store" }));
  },
  async startupMaterials(projectId: string): Promise<StartupMaterialsRecord> {
    return readResponse<StartupMaterialsRecord>(await fetch(`/internal/workbench/startup-materials?project_id=${encodeURIComponent(projectId)}`, { cache: "no-store" }));
  },
  async projectContacts(projectId: string, includeInactive = false): Promise<ProjectContactRecord[]> {
    const query = includeInactive ? "&include_inactive=true" : "";
    return readResponse<ProjectContactRecord[]>(await fetch(`/internal/workbench/contacts?project_id=${encodeURIComponent(projectId)}${query}`, { cache: "no-store" }));
  },
  async createProjectContact(projectId: string, input: Record<string, unknown>): Promise<ProjectContactRecord> {
    return readResponse<ProjectContactRecord>(await fetch(`/internal/workbench/contacts?project_id=${encodeURIComponent(projectId)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async updateProjectContact(projectId: string, id: string, input: Record<string, unknown>): Promise<ProjectContactRecord> {
    return readResponse<ProjectContactRecord>(await fetch(`/internal/workbench/contacts/${encodeURIComponent(id)}?project_id=${encodeURIComponent(projectId)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async deleteProjectContact(projectId: string, id: string): Promise<void> {
    await readResponse<unknown>(await fetch(`/internal/workbench/contacts/${encodeURIComponent(id)}?project_id=${encodeURIComponent(projectId)}`, { method: "DELETE" }));
  },
  async certifications(projectId: string, includeInactive = false): Promise<CertificationRecord[]> {
    const query = includeInactive ? "&include_inactive=true" : "";
    return readResponse<CertificationRecord[]>(await fetch(`/internal/workbench/certifications?project_id=${encodeURIComponent(projectId)}${query}`, { cache: "no-store" }));
  },
  async createCertification(projectId: string, input: Record<string, unknown>): Promise<CertificationRecord> {
    return readResponse<CertificationRecord>(await fetch(`/internal/workbench/certifications?project_id=${encodeURIComponent(projectId)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async updateCertification(projectId: string, id: string, input: Record<string, unknown>): Promise<CertificationRecord> {
    return readResponse<CertificationRecord>(await fetch(`/internal/workbench/certifications/${encodeURIComponent(id)}?project_id=${encodeURIComponent(projectId)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async deleteCertification(projectId: string, id: string): Promise<void> {
    await readResponse<unknown>(await fetch(`/internal/workbench/certifications/${encodeURIComponent(id)}?project_id=${encodeURIComponent(projectId)}`, { method: "DELETE" }));
  },
  async deleteMaterial(projectId: string, id: string): Promise<void> {
    await readResponse<unknown>(await fetch(`/internal/workbench/materials/${encodeURIComponent(id)}?project_id=${encodeURIComponent(projectId)}`, {
      method: "DELETE",
    }));
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
  async generateTasks(projectId: string, roundId: string, entryTypes?: string[], samplesPerCell = 1): Promise<BatchGenerationResult> {
    return readResponse<BatchGenerationResult>(await fetch(dataUrl("batch", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        round_id: roundId,
        samples_per_cell: samplesPerCell,
        ...(entryTypes?.length ? { entry_types: entryTypes } : {}),
      }),
    }));
  },
  async retestPlans(projectId: string): Promise<ApiEnvelope<RetestPlanRecord[]>> {
    return readPage<RetestPlanRecord[]>(await fetch(dataUrl("retest-plans", projectId), { cache: "no-store" }));
  },
  async createRetestPlan(projectId: string, input: Record<string, unknown>): Promise<RetestPlanRecord> {
    return readResponse<RetestPlanRecord>(await fetch(dataUrl("retest-plan", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async updateRetestPlan(projectId: string, planId: string, input: Record<string, unknown>): Promise<RetestPlanRecord> {
    return readResponse<RetestPlanRecord>(await fetch(dataUrl("retest-plan", projectId, { id: planId }), {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async runRetestPlan(projectId: string, planId: string): Promise<RetestPlanRunResult> {
    return readResponse<RetestPlanRunResult>(await fetch(dataUrl("retest-plan-run", projectId, { id: planId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async channels(projectId: string, page = 1, pageSize = 20, scope?: "publish" | "monitoring"): Promise<ApiEnvelope<ChannelRecord[]>> {
    return readPage<ChannelRecord[]>(await fetch(dataUrl("channels", projectId, { page, page_size: pageSize, ...(scope ? { scope } : {}) }), { cache: "no-store" }));
  },
  async channelAnomalies(projectId: string): Promise<ChannelAnomalyList> {
    return readResponse<ChannelAnomalyList>(await fetch(dataUrl("channel-anomalies", projectId), { cache: "no-store" }));
  },
  async channel(projectId: string, id: string): Promise<ChannelDetailRecord> {
    return readResponse<ChannelDetailRecord>(await fetch(dataUrl("channel", projectId, { id }), { cache: "no-store" }));
  },
  async downloadChannels(projectId: string, filters: { engine_id?: string; question_id?: string; start_date?: string; end_date?: string; review_status?: string } = {}): Promise<void> {
    const response = await fetch(dataUrl("channels-export", projectId, filters), { cache: "no-store" });
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
  async reviewChannel(projectId: string, id: string, decision: "approved" | "rejected", comment?: string): Promise<ChannelRecord> {
    return readResponse<ChannelRecord>(await fetch(dataUrl("channel-review", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, comment: comment || null }),
    }));
  },
  async deleteChannel(projectId: string, id: string): Promise<{ id: string; name: string | null; deleted: boolean }> {
    return readResponse<{ id: string; name: string | null; deleted: boolean }>(await fetch(dataUrl("channel", projectId, { id }), { method: "DELETE" }));
  },
  async resubmitChannel(projectId: string, id: string): Promise<ChannelRecord> {
    return readResponse<ChannelRecord>(await fetch(dataUrl("channel-submit", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
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
  async questionCandidates(projectId: string, page = 1, status?: string, bucket?: string): Promise<ApiEnvelope<QuestionCandidateRecord[]>> {
    return readPage<QuestionCandidateRecord[]>(await fetch(dataUrl("question-candidates", projectId, { page, page_size: 20, status, bucket }), { cache: "no-store" }));
  },
  async mineQuestionCandidates(projectId: string, limit = 20, buckets?: string[]): Promise<QuestionCandidateMineResult> {
    return readResponse<QuestionCandidateMineResult>(await fetch(dataUrl("question-candidates-mine", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ limit, buckets: buckets ?? [] }),
    }));
  },
  async importQuestionCandidates(projectId: string, texts: string[], bucket: string): Promise<QuestionCandidateImportResult> {
    return readResponse<QuestionCandidateImportResult>(await fetch(dataUrl("question-candidates-import", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texts, bucket }),
    }));
  },
  async acceptQuestionCandidate(projectId: string, id: string): Promise<QuestionCandidateAcceptResult> {
    return readResponse<QuestionCandidateAcceptResult>(await fetch(dataUrl("question-candidate-accept", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }));
  },
  async rejectQuestionCandidate(projectId: string, id: string): Promise<QuestionCandidateRecord> {
    return readResponse<QuestionCandidateRecord>(await fetch(dataUrl("question-candidate-reject", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
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
  async previewPageTypeReclassify(projectId: string, limit = 1000, mode: "path" | "content" = "path"): Promise<PageTypeReclassifyResult> {
    return readResponse<PageTypeReclassifyResult>(await fetch(dataUrl("page-type-preview", projectId, { limit, mode }), { cache: "no-store" }));
  },
  async applyPageTypeReclassify(projectId: string, limit = 1000, mode: "path" | "content" = "path"): Promise<PageTypeReclassifyResult> {
    return readResponse<PageTypeReclassifyResult>(await fetch(dataUrl("page-type-reclassify", projectId, { limit, mode }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }));
  },
  async backfillPageTitles(projectId: string, limit = 50, apply = false): Promise<PageTitleBackfillResult> {
    return readResponse<PageTitleBackfillResult>(await fetch(dataUrl("page-title-backfill", projectId, { limit, apply: apply ? "true" : "false" }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }));
  },
  async statsPageVisibility(projectId: string, limit = 50): Promise<PageVisibilityReport> {
    return readResponse<PageVisibilityReport>(await fetch(dataUrl("stats-page-visibility", projectId, { limit }), { cache: "no-store" }));
  },
  async statsDistributionCandidates(projectId: string, limit = 10): Promise<DistributionCandidates> {
    return readResponse<DistributionCandidates>(await fetch(dataUrl("stats-distribution-candidates", projectId, { limit }), { cache: "no-store" }));
  },
  async sourceDomains(projectId: string, limit = 50): Promise<SourceDomainsOverview> {
    return readResponse<SourceDomainsOverview>(await fetch(dataUrl("source-domains", projectId, { limit }), { cache: "no-store" }));
  },
  async collectSourceDomainEvidence(projectId: string, limit = 0): Promise<{ fetched: number; ok: number; failed: number }> {
    return readResponse<{ fetched: number; ok: number; failed: number }>(await fetch(dataUrl("source-domain-evidence", projectId, { limit }), { method: "POST" }));
  },
  async classifySourceDomains(projectId: string, decisions: Array<{ site: string; category: string; note?: string }>): Promise<{ changed: number }> {
    return readResponse<{ changed: number }>(await fetch(dataUrl("source-domain-classify", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decisions }),
    }));
  },
  async applySourceDomains(projectId: string, limit = 50): Promise<SourceDomainsOverview> {
    return readResponse<SourceDomainsOverview>(await fetch(dataUrl("source-domain-apply", projectId, { limit }), { method: "POST" }));
  },
  async previewBrandRelatedCitations(projectId: string, limit = 500): Promise<BrandRelatedPreview> {
    return readResponse<BrandRelatedPreview>(await fetch(dataUrl("citation-brand-related", projectId, { limit }), { cache: "no-store" }));
  },
  async applyBrandRelatedCitations(projectId: string, limit = 500): Promise<BrandRelatedPreview> {
    return readResponse<BrandRelatedPreview>(await fetch(dataUrl("brand-related-backfill", projectId, { limit }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }));
  },
  async sentimentSampling(projectId: string, roundNo = 1, size = 12): Promise<SentimentSampling> {
    return readResponse<SentimentSampling>(await fetch(dataUrl("sentiment-sampling", projectId, { round_no: roundNo, size }), { cache: "no-store" }));
  },
  async sentimentConsensus(projectId: string, roundNo = 1, size = 12): Promise<SentimentConsensus> {
    return readResponse<SentimentConsensus>(await fetch(dataUrl("sentiment-consensus", projectId, { round_no: roundNo, size }), { cache: "no-store" }));
  },
  async labelSentimentPolarity(projectId: string, citationId: string, polarity: string): Promise<{ citation_id: string; polarity: string }> {
    return readResponse(await fetch(dataUrl("sentiment-label", projectId, { id: citationId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ polarity }),
    }));
  },
  async statsContentFreshness(projectId: string, months = 18, limit = 100): Promise<ContentFreshness> {
    return readResponse<ContentFreshness>(await fetch(dataUrl("stats-content-freshness", projectId, { months, limit }), { cache: "no-store" }));
  },
  async statsContentConsistency(projectId: string, limit = 50): Promise<ContentConsistencyReport> {
    return readResponse<ContentConsistencyReport>(await fetch(dataUrl("stats-content-consistency", projectId, { limit }), { cache: "no-store" }));
  },
  async statsContentFormats(projectId: string): Promise<ContentFormatReport> {
    return readResponse<ContentFormatReport>(await fetch(dataUrl("stats-content-formats", projectId), { cache: "no-store" }));
  },
  async statsBrandSearch(projectId: string, days = 90, platform = ""): Promise<BrandSearchReport> {
    return readResponse<BrandSearchReport>(await fetch(dataUrl("stats-brand-search", projectId, { days, ...(platform ? { platform } : {}) }), { cache: "no-store" }));
  },
  async importBrandSearch(projectId: string, rows: { platform: string; date: string; search_volume: number; note?: string | null }[], source = "csv"): Promise<{ imported: number; updated: number; errors: { row: number; error: string }[]; report?: BrandSearchReport }> {
    return readResponse(await fetch(dataUrl("stats-brand-search-import", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows, source }),
    }));
  },
  async statsCompetitorSources(projectId: string, days = 90, limit = 20): Promise<CompetitorSourceReport> {
    return readResponse<CompetitorSourceReport>(await fetch(dataUrl("stats-competitor-sources", projectId, { days, limit }), { cache: "no-store" }));
  },
  async statsAdaptation(projectId: string): Promise<AdaptationReport> {
    return readResponse<AdaptationReport>(await fetch(dataUrl("stats-adaptation", projectId), { cache: "no-store" }));
  },
  async saveAdaptation(projectId: string, answers: Record<string, string>, note: string | null): Promise<AdaptationReport> {
    return readResponse<AdaptationReport>(await fetch(dataUrl("stats-adaptation", projectId), {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answers, note }),
    }));
  },
  async statsAcceptanceContract(projectId: string, days = 90, targetStreak = 30): Promise<AcceptanceContract> {
    return readResponse<AcceptanceContract>(await fetch(dataUrl("stats-acceptance-contract", projectId, { days, target_streak: targetStreak }), { cache: "no-store" }));
  },
  async archiveSampleSnapshot(projectId: string, sampleId: string): Promise<AnswerSnapshotSummary & { created: boolean }> {
    return readResponse(await fetch(dataUrl("sample-snapshot", projectId, { id: sampleId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }));
  },
  async snapshots(projectId: string, page = 1, pageSize = 50): Promise<ApiEnvelope<AnswerSnapshotSummary[]>> {
    return readPage<AnswerSnapshotSummary[]>(await fetch(dataUrl("snapshots", projectId, { page, page_size: pageSize }), { cache: "no-store" }));
  },
  async answerSnapshot(projectId: string, id: string): Promise<AnswerSnapshotDetail> {
    return readResponse<AnswerSnapshotDetail>(await fetch(dataUrl("snapshot", projectId, { id }), { cache: "no-store" }));
  },
  async captureSnapshots(projectId: string, limit = 50): Promise<{ candidates: number; captured: number; missing_answer: number }> {
    return readResponse(await fetch(dataUrl("snapshots-capture", projectId, { limit }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }));
  },
  async tasks(projectId: string, page = 1, roundId?: string, status?: string, pageSize = WORKBENCH_PAGE_SIZE): Promise<ApiEnvelope<MonitoringTaskRecord[]>> {
    return readPage<MonitoringTaskRecord[]>(await fetch(dataUrl("tasks", projectId, { page, page_size: pageSize, round_id: roundId, status }), { cache: "no-store" }));
  },
  async cancelMonitoringTask(projectId: string, id: string): Promise<{ task_id: string; status: string }> {
    return readResponse<{ task_id: string; status: string }>(await fetch(dataUrl("task-cancel", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }));
  },
  async cancelPublishTask(projectId: string, id: string): Promise<{ task_id: string; status: string }> {
    return readResponse<{ task_id: string; status: string }>(await fetch(dataUrl("publish-task-cancel", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }));
  },
  async createSample(projectId: string, taskId: string, input: Record<string, unknown>): Promise<ManualSampleCreated> {
    return readResponse<ManualSampleCreated>(await fetch(dataUrl("sample-create", projectId, { id: taskId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async createManualFailure(projectId: string, taskId: string, input: Record<string, unknown>): Promise<ManualFailureCreated> {
    return readResponse<ManualFailureCreated>(await fetch(dataUrl("manual-failure", projectId, { id: taskId }), {
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
  async recordSampleReview(projectId: string, id: string, note: string, result?: "hit" | "miss"): Promise<{ sample_id: string; status: string; review_result: string | null; reviewed_at: string; review_note: string }> {
    return readResponse<{ sample_id: string; status: string; review_result: string | null; reviewed_at: string; review_note: string }>(await fetch(dataUrl("sample-review-record", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ review_note: note, review_result: result ?? null }),
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
  async citationAnswerOptions(projectId: string, query?: string): Promise<ApiEnvelope<CitationAnswerOption[]>> {
    return readPage<CitationAnswerOption[]>(await fetch(dataUrl("citation-answer-options", projectId, { q: query, limit: 50 }), { cache: "no-store" }));
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
  async bulkClassifySourceReviews(projectId: string, reviewIds: string[], sourceCategory: string, note?: string): Promise<{ classified: number; citations: number; skipped: number }> {
    return readResponse<{ classified: number; citations: number; skipped: number }>(await fetch(dataUrl("source-reviews-bulk-classify", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ review_ids: reviewIds, source_category: sourceCategory, review_note: note || null }),
    }));
  },
  async ignoreSourceReview(projectId: string, reviewId: string): Promise<SourceReviewRecord> {
    return readResponse<SourceReviewRecord>(await fetch(dataUrl("source-review-ignore", projectId, { id: reviewId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
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
  async factPush(projectId: string, factId: string, targetType: "encyclopedia" | "webhook", targetRef = ""): Promise<FactPushRecord> {
    return readResponse<FactPushRecord>(await fetch(dataUrl("fact-push", projectId, { id: factId }), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_type: targetType, target_ref: targetRef }),
    }));
  },
  async factPushes(projectId: string, factId: string): Promise<ApiEnvelope<FactPushRecord[]>> {
    return readPage<FactPushRecord[]>(await fetch(dataUrl("fact-pushes", projectId, { id: factId, page_size: 50 }), { cache: "no-store" }));
  },
  async retryFactPush(projectId: string, pushId: string): Promise<FactPushRecord> {
    return readResponse<FactPushRecord>(await fetch(dataUrl("push-retry", projectId, { id: pushId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async generationGate(projectId: string, batchId: string, action: GenerationGateAction, input: Record<string, unknown> = {}): Promise<GenerationGateRecord> {
    return readResponse<GenerationGateRecord>(await fetch(`/internal/workbench/generation?project_id=${encodeURIComponent(projectId)}&batch_id=${encodeURIComponent(batchId)}&action=${action}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async generationGates(projectId: string, batchId: string): Promise<GenerationGateRecord[]> {
    return readResponse<GenerationGateRecord[]>(await fetch(`/internal/workbench/generation?project_id=${encodeURIComponent(projectId)}&batch_id=${encodeURIComponent(batchId)}&gates=1`, { cache: "no-store" }));
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
  async publishTasks(projectId: string, page = 1, status?: string, contentType?: string, withinDays?: number, pageSize = 20): Promise<ApiEnvelope<PublishTaskRecord[]>> {
    return readPage<PublishTaskRecord[]>(await fetch(dataUrl("publish-tasks", projectId, { page, page_size: Math.min(100, Math.max(1, pageSize)), status, content_type: contentType, within_days: withinDays }), { cache: "no-store" }));
  },
  async publishAccounts(projectId: string): Promise<ApiEnvelope<PublishAccountRecord[]>> {
    return readPage<PublishAccountRecord[]>(await fetch(dataUrl("publish-accounts", projectId, { page_size: 100 }), { cache: "no-store" }));
  },
  async createPublishAccount(projectId: string, input: Record<string, unknown>): Promise<PublishAccountRecord> {
    return readResponse<PublishAccountRecord>(await fetch(dataUrl("publish-account", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async updatePublishAccount(projectId: string, accountId: string, input: Record<string, unknown>): Promise<PublishAccountRecord> {
    return readResponse<PublishAccountRecord>(await fetch(dataUrl("publish-account", projectId, { id: accountId }), {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async deletePublishAccount(projectId: string, accountId: string): Promise<{ id: string; name: string | null; deleted: boolean }> {
    return readResponse<{ id: string; name: string | null; deleted: boolean }>(await fetch(dataUrl("publish-account", projectId, { id: accountId }), { method: "DELETE" }));
  },
  async oauthProviders(projectId: string): Promise<OAuthProviderRecord[]> {
    return readResponse<OAuthProviderRecord[]>(await fetch(dataUrl("oauth-providers", projectId), { cache: "no-store" }));
  },
  async oauthConnections(projectId: string): Promise<OAuthConnectionRecord[]> {
    return readResponse<OAuthConnectionRecord[]>(await fetch(dataUrl("oauth-connections", projectId), { cache: "no-store" }));
  },
  async authorizeOAuth(projectId: string, input: { provider_code: string; channel_id?: string; return_path?: string }): Promise<OAuthAuthorizeResult> {
    return readResponse<OAuthAuthorizeResult>(await fetch(dataUrl("oauth-authorize", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async refreshOAuthConnection(projectId: string, connectionId: string): Promise<OAuthConnectionRecord> {
    return readResponse<OAuthConnectionRecord>(await fetch(dataUrl("oauth-refresh", projectId, { id: connectionId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async revokeOAuthConnection(projectId: string, connectionId: string): Promise<OAuthConnectionRecord> {
    return readResponse<OAuthConnectionRecord>(await fetch(dataUrl("oauth-revoke", projectId, { id: connectionId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async approvedVersions(projectId: string): Promise<ApiEnvelope<ContentVersionRecord[]>> {
    return readPage<ContentVersionRecord[]>(await fetch(dataUrl("content-versions", projectId, { status: "approved", page_size: 100 }), { cache: "no-store" }));
  },
  async pageApprovals(projectId: string, options: { channel_id?: string; page_type?: string; permission?: string; status?: string; q?: string; page?: number; pageSize?: number } = {}): Promise<ApiEnvelope<PageApprovalRecord[]>> {
    return readPage<PageApprovalRecord[]>(await fetch(dataUrl("page-approvals", projectId, {
      channel_id: options.channel_id,
      page_type: options.page_type,
      permission: options.permission,
      status: options.status,
      q: options.q?.trim() || undefined,
      page: options.page ?? 1,
      page_size: options.pageSize ?? WORKBENCH_PAGE_SIZE,
    }), { cache: "no-store" }));
  },
  async pageApproval(projectId: string, approvalId: string): Promise<PageApprovalRecord> {
    return readResponse<PageApprovalRecord>(await fetch(dataUrl("page-approval", projectId, { id: approvalId }), { cache: "no-store" }));
  },
  async createPageApproval(projectId: string, input: { channel_id: string; page_url: string; title?: string | null; page_type: string; permission: string }): Promise<PageApprovalRecord> {
    return readResponse<PageApprovalRecord>(await fetch(dataUrl("page-approval", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async reviewPageApproval(projectId: string, approvalId: string, input: { decision: "approved" | "rejected"; note?: string | null }): Promise<PageApprovalRecord> {
    return readResponse<PageApprovalRecord>(await fetch(dataUrl("page-approval-review", projectId, { id: approvalId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async revokePageApproval(projectId: string, approvalId: string, note: string): Promise<PageApprovalRecord> {
    return readResponse<PageApprovalRecord>(await fetch(dataUrl("page-approval-revoke", projectId, { id: approvalId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note }),
    }));
  },
  async contentVersions(projectId: string, status?: string, page = 1, contentType?: string, withinDays?: number): Promise<ApiEnvelope<ContentVersionRecord[]>> {
    return readPage<ContentVersionRecord[]>(await fetch(dataUrl("content-versions", projectId, { status, page, page_size: 20, content_type: contentType, within_days: withinDays }), { cache: "no-store" }));
  },
  async contentVersion(projectId: string, id: string): Promise<ContentVersionDetail> {
    return readResponse<ContentVersionDetail>(await fetch(dataUrl("content-version", projectId, { id }), { cache: "no-store" }));
  },
  async sellingPoints(projectId: string): Promise<SellingPointRecord[]> {
    return readResponse<SellingPointRecord[]>(await fetch(dataUrl("selling-points", projectId), { cache: "no-store" }));
  },
  async sellingPointSummary(projectId: string): Promise<SellingPointSummary> {
    return readResponse<SellingPointSummary>(await fetch(dataUrl("selling-points-summary", projectId), { cache: "no-store" }));
  },
  async createSellingPoint(projectId: string, payload: { label: string; value_text: string | null; aliases: string[]; required: boolean; note: string | null }): Promise<SellingPointRecord> {
    return readResponse<SellingPointRecord>(await fetch(dataUrl("selling-point-create", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    }));
  },
  async updateSellingPoint(projectId: string, id: string, payload: Partial<{ label: string; value_text: string | null; aliases: string[]; required: boolean; is_active: boolean; note: string | null }>): Promise<SellingPointRecord> {
    return readResponse<SellingPointRecord>(await fetch(dataUrl("selling-point-update", projectId, { id }), {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    }));
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
  async publishAction(projectId: string, kind: "publish-task" | "publish-attempt" | "publish-receipt" | "publish-verify" | "publish-handoff" | "publish-execute" | "publish-mass-send", input: Record<string, unknown>, id?: string): Promise<unknown> {
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
  async statsByEntry(projectId: string, answerKind?: AnswerKindParam, roundId?: string, questionType?: QuestionTypeParam): Promise<StatsEntry[]> {
    return readResponse<StatsEntry[]>(await fetch(dataUrl("stats-by-entry", projectId, { answer_kind: answerKind, round_id: roundId, question_type: questionType }), { cache: "no-store" }));
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
  async statsSourceCoverage(projectId: string, days = 90, limit = 20): Promise<SourceCoverage> {
    return readResponse<SourceCoverage>(await fetch(dataUrl("stats-source-coverage", projectId, { days, limit }), { cache: "no-store" }));
  },
  async statsSourceTiers(projectId: string, days = 90, limit = 20): Promise<SourceTiers> {
    return readResponse<SourceTiers>(await fetch(dataUrl("stats-source-tiers", projectId, { days, limit }), { cache: "no-store" }));
  },
  async statsSourceMatrix(projectId: string, days = 90, limit = 20, tiers = "T0,T1,T2"): Promise<SourceMatrix> {
    return readResponse<SourceMatrix>(await fetch(dataUrl("stats-source-matrix", projectId, { days, limit, tiers }), { cache: "no-store" }));
  },
  async statsMonthly(projectId: string, month?: string): Promise<MonthlyReport> {    return readResponse<MonthlyReport>(await fetch(dataUrl("stats-monthly", projectId, { month }), { cache: "no-store" }));
  },
  async monthlySnapshots(projectId: string, month?: string): Promise<MonthlyReportSnapshotSummary[]> {
    return readResponse<MonthlyReportSnapshotSummary[]>(await fetch(dataUrl("monthly-snapshots", projectId, { month }), { cache: "no-store" }));
  },
  async monthlySnapshot(projectId: string, id: string): Promise<MonthlyReportSnapshot> {
    return readResponse<MonthlyReportSnapshot>(await fetch(dataUrl("monthly-snapshot", projectId, { id }), { cache: "no-store" }));
  },
  async freezeMonthlyReport(projectId: string, month: string): Promise<MonthlyReportSnapshot> {
    return readResponse<MonthlyReportSnapshot>(await fetch(dataUrl("monthly-snapshot", projectId, { month }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async reportShares(projectId: string, snapshotId?: string): Promise<ReportShareRecord[]> {
    return readResponse<ReportShareRecord[]>(await fetch(dataUrl("report-shares", projectId, { snapshot_id: snapshotId }), { cache: "no-store" }));
  },
  async createReportShare(projectId: string, body: Record<string, unknown>): Promise<ReportShareCreateResult> {
    return readResponse<ReportShareCreateResult>(await fetch(dataUrl("report-share", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }));
  },
  async revokeReportShare(projectId: string, shareId: string): Promise<ReportShareRecord> {
    return readResponse<ReportShareRecord>(await fetch(dataUrl("report-share-revoke", projectId, { id: shareId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async downloadMonthlyReport(projectId: string, month: string): Promise<void> {
    const response = await fetch(dataUrl("monthly-report-export", projectId, { month }), { cache: "no-store" });
    if (!response.ok) { await readResponse(response); return; }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)/)?.[1] ?? `geo-monthly-report-${month}.md`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  async leadFunnel(projectId: string, startDate?: string, endDate?: string): Promise<LeadFunnel> {
    return readResponse<LeadFunnel>(await fetch(dataUrl("lead-funnel", projectId, { start_date: startDate, end_date: endDate }), { cache: "no-store" }));
  },
  async dashboardTracks(projectId: string, days = 30): Promise<DashboardTracks> {
    return readResponse<DashboardTracks>(await fetch(dataUrl("dashboard-tracks", projectId, { days }), { cache: "no-store" }));
  },
  async geoBoard(projectId: string, options: {
    days?: number; engineId?: string; page?: number; pageSize?: number; leadPage?: number;
  } = {}): Promise<GeoBoard> {
    const { days = 30, engineId, page = 1, pageSize = 10, leadPage = 1 } = options;
    return readResponse<GeoBoard>(await fetch(dataUrl("dashboard-board", projectId, {
      days,
      engine_id: engineId,
      page,
      page_size: pageSize,
      lead_page: leadPage,
      lead_page_size: 10,
    }), { cache: "no-store" }));
  },
  async site(projectId: string): Promise<SiteRecord> {
    return readResponse<SiteRecord>(await fetch(`/internal/workbench/site?project_id=${projectId}`, { cache: "no-store" }));
  },
  async updateSite(projectId: string, input: Record<string, unknown>, moduleType?: string): Promise<SiteRecord> {
    const query = new URLSearchParams({ project_id: projectId });
    if (moduleType) query.set("module_type", moduleType);
    return readResponse<SiteRecord>(await fetch(`/internal/workbench/site?${query}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async leadVisitorReport(projectId: string): Promise<LeadVisitorReport> {
    return readResponse<LeadVisitorReport>(await fetch(dataUrl("lead-visitor-report", projectId), { cache: "no-store" }));
  },
  async healthCheckHistory(projectId: string): Promise<HealthCheckRunSummary[]> {
    return readResponse<HealthCheckRunSummary[]>(await fetch(`/internal/workbench/health?project_id=${projectId}`, { cache: "no-store" }));
  },
  async healthCheckRun(projectId: string, runId: string): Promise<HealthCheckRun> {
    const query = new URLSearchParams({ project_id: projectId, run_id: runId });
    return readResponse<HealthCheckRun>(await fetch(`/internal/workbench/health?${query}`, { cache: "no-store" }));
  },
  async runHealthCheck(projectId: string): Promise<HealthCheckRun> {
    return readResponse<HealthCheckRun>(await fetch(`/internal/workbench/health?project_id=${projectId}`, { method: "POST" }));
  },
  async trafficSummary(projectId: string, days = 30): Promise<TrafficSummary> {
    return readResponse<TrafficSummary>(await fetch(dataUrl("traffic-summary", projectId, { days }), { cache: "no-store" }));
  },
  async generationBatches(projectId: string): Promise<GenerationBatchSummary[]> {
    return readResponse<GenerationBatchSummary[]>(await fetch(`/internal/workbench/generation?project_id=${projectId}`, { cache: "no-store" }));
  },
  async generationBatch(projectId: string, batchId: string): Promise<GenerationBatchRecord> {
    return readResponse<GenerationBatchRecord>(await fetch(`/internal/workbench/generation?project_id=${projectId}&batch_id=${batchId}`, { cache: "no-store" }));
  },
  async createGenerationBatch(projectId: string, input: { name: string; source: "opportunity" | "question"; limit?: number }): Promise<GenerationBatchRecord> {
    return readResponse<GenerationBatchRecord>(await fetch(`/internal/workbench/generation?project_id=${projectId}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async runGenerationBatch(projectId: string, batchId: string): Promise<GenerationBatchRecord> {
    return readResponse<GenerationBatchRecord>(await fetch(`/internal/workbench/generation?project_id=${projectId}&batch_id=${batchId}`, { method: "POST" }));
  },
  async reviewGenerationItem(projectId: string, batchId: string, itemId: string, reviewed: boolean): Promise<{ item_id: string; reviewed: boolean }> {
    const query = new URLSearchParams({ project_id: projectId, batch_id: batchId, item_id: itemId });
    return readResponse(await fetch(`/internal/workbench/generation?${query}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reviewed }),
    }));
  },
  async exportGenerationBatch(projectId: string, batchId: string): Promise<void> {
    const response = await fetch(`/internal/workbench/generation?project_id=${projectId}&batch_id=${batchId}&export=1`, { cache: "no-store" });
    if (!response.ok) throw new Error("生成批次导出失败");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)/)?.[1] ?? `generation-${batchId.slice(0, 8)}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  async encyclopediaEntries(projectId: string): Promise<EncyclopediaEntryRecord[]> {
    return readResponse<EncyclopediaEntryRecord[]>(await fetch(`/internal/workbench/encyclopedia?project_id=${projectId}`, { cache: "no-store" }));
  },
  async createEncyclopediaEntry(projectId: string, input: { title: string; platform: string; body: string; summary?: string; references: EncyclopediaReference[] }): Promise<EncyclopediaEntryRecord> {
    return readResponse<EncyclopediaEntryRecord>(await fetch(`/internal/workbench/encyclopedia?project_id=${projectId}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async updateEncyclopediaEntry(projectId: string, entryId: string, input: { title?: string; platform?: string; body?: string; summary?: string; references?: EncyclopediaReference[] }): Promise<EncyclopediaEntryRecord> {
    return readResponse<EncyclopediaEntryRecord>(await fetch(`/internal/workbench/encyclopedia?project_id=${projectId}&entry_id=${entryId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async submitEncyclopediaEntry(projectId: string, entryId: string): Promise<EncyclopediaEntryRecord> {
    return readResponse<EncyclopediaEntryRecord>(await fetch(`/internal/workbench/encyclopedia?project_id=${projectId}&entry_id=${entryId}&action=submit`, { method: "POST" }));
  },
  async reviewEncyclopediaEntry(projectId: string, entryId: string, approve: boolean, note?: string): Promise<EncyclopediaEntryRecord> {
    return readResponse<EncyclopediaEntryRecord>(await fetch(`/internal/workbench/encyclopedia?project_id=${projectId}&entry_id=${entryId}&action=review`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approve, note: note || null }),
    }));
  },
  async publishEncyclopediaEntry(projectId: string, entryId: string, publishedUrl: string): Promise<EncyclopediaEntryRecord> {
    return readResponse<EncyclopediaEntryRecord>(await fetch(`/internal/workbench/encyclopedia?project_id=${projectId}&entry_id=${entryId}&action=publication`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ published_url: publishedUrl }),
    }));
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
  async runReceiptReachabilityCheck(projectId: string, limit = 20): Promise<{ checked: number; reachable: number; unreachable: number; failed: number; duration_ms: number }> {
    return readResponse(await fetch(dataUrl("receipt-reachability-check", projectId), {
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
  async deleteCompetitor(projectId: string, id: string): Promise<{ id: string; deleted: boolean }> {
    return readResponse<{ id: string; deleted: boolean }>(await fetch(dataUrl("competitor", projectId, { id }), { method: "DELETE" }));
  },
  async brandProfile(projectId: string): Promise<BrandProfileRecord> {
    return readResponse<BrandProfileRecord>(await fetch(dataUrl("brand-profile", projectId), { cache: "no-store" }));
  },
  async companyProfile(projectId: string): Promise<CompanyProfileRecord> {
    return readResponse<CompanyProfileRecord>(await fetch(dataUrl("company-profile", projectId), { cache: "no-store" }));
  },
  async saveCompanyProfile(projectId: string, input: Record<string, unknown>): Promise<CompanyProfileRecord> {
    return readResponse<CompanyProfileRecord>(await fetch(dataUrl("company-profile", projectId), {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  /** 四套对外画像按 kind 覆盖保存；返回整份档案，前端直接替换 state 里的 views。 */
  async saveCompanyProfileViews(projectId: string, views: Record<string, unknown>[]): Promise<CompanyProfileRecord> {
    return readResponse<CompanyProfileRecord>(await fetch(`/internal/workbench/company-views?project_id=${encodeURIComponent(projectId)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ views }),
    }));
  },
  /** 一键填表：只返回建议字段，不落库；模型不可用时后端退回事实整理。 */
  async draftCompanyProfile(projectId: string, prefer: "auto" | "rule" = "auto"): Promise<CompanyProfileDraftRecord> {
    return readResponse<CompanyProfileDraftRecord>(await fetch(`/internal/workbench/company-draft?project_id=${encodeURIComponent(projectId)}&prefer=${prefer}`, {
      method: "POST",
    }));
  },
  /** 起草模型配置：读回来的只有来源和指纹，Key 本身不回显。 */
  async companyDraftModel(projectId: string): Promise<CompanyDraftModelRecord> {
    return readResponse<CompanyDraftModelRecord>(await fetch(`/internal/workbench/company-draft-model?project_id=${encodeURIComponent(projectId)}`, { cache: "no-store" }));
  },
  async saveCompanyDraftModel(
    projectId: string,
    input: { base_url?: string; model?: string; api_key?: string; clear_key?: boolean; is_active?: boolean },
  ): Promise<CompanyDraftModelRecord> {
    return readResponse<CompanyDraftModelRecord>(await fetch(`/internal/workbench/company-draft-model?project_id=${encodeURIComponent(projectId)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  /** 用一句最小请求验证 Key/型号能不能调通。 */
  async testCompanyDraftModel(projectId: string): Promise<CompanyDraftModelTestRecord> {
    return readResponse<CompanyDraftModelTestRecord>(await fetch(`/internal/workbench/company-draft-model-test?project_id=${encodeURIComponent(projectId)}`, {
      method: "POST",
    }));
  },
  async brandGovernance(projectId: string): Promise<BrandGovernanceRecord> {
    return readResponse<BrandGovernanceRecord>(await fetch(dataUrl("brand-governance", projectId), { cache: "no-store" }));
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
  async users(q = "", page = 1): Promise<ApiEnvelope<UserAccountRecord[]>> {
    return readPage<UserAccountRecord[]>(await fetch(`/internal/workbench/system?kind=users&q=${encodeURIComponent(q)}&page=${page}&page_size=20`, { cache: "no-store" }));
  },
  async createUser(input: { username: string; display_name: string; email?: string | null; password: string }): Promise<UserAccountRecord> {
    return readResponse<UserAccountRecord>(await fetch("/internal/workbench/system?kind=user-create", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async updateUser(userId: string, input: { display_name?: string; email?: string | null; is_active?: boolean }): Promise<UserAccountRecord> {
    return readResponse<UserAccountRecord>(await fetch(`/internal/workbench/system?kind=user-update&user_id=${encodeURIComponent(userId)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
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
  async opportunitySuggestions(projectId: string, filters: { status?: string; rule_code?: string } = {}): Promise<ApiEnvelope<OpportunitySuggestionRecord[]>> {
    const params = new URLSearchParams({ project_id: projectId, page: "1", page_size: "50" });
    if (filters.status) params.set("status", filters.status);
    if (filters.rule_code) params.set("rule_code", filters.rule_code);
    return readPage<OpportunitySuggestionRecord[]>(await fetch(`/internal/workbench/opportunity-suggestions?${params}`, { cache: "no-store" }));
  },
  async generateOpportunitySuggestions(projectId: string): Promise<{ created: number; updated: number; skipped: number; total: number }> {
    return readResponse(await fetch("/internal/workbench/opportunity-suggestions", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, action: "generate" }),
    }));
  },
  async reviewOpportunitySuggestion(projectId: string, suggestionId: string, action: "accept" | "dismiss", note?: string): Promise<OpportunityRecord | OpportunitySuggestionRecord> {
    return readResponse(await fetch("/internal/workbench/opportunity-suggestions", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, suggestion_id: suggestionId, action, note }),
    }));
  },
  async alertRules(projectId: string): Promise<ApiEnvelope<AlertRuleRecord[]>> {
    return readPage<AlertRuleRecord[]>(await fetch(`/internal/workbench/alerts?project_id=${projectId}&kind=rules`, { cache: "no-store" }));
  },
  async updateAlertRule(projectId: string, ruleId: string, input: Record<string, unknown>): Promise<AlertRuleRecord> {
    return readResponse(await fetch("/internal/workbench/alerts", {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, rule_id: ruleId, ...input }),
    }));
  },
  async alertEvents(projectId: string, status?: string): Promise<ApiEnvelope<AlertEventRecord[]>> {
    const params = new URLSearchParams({ project_id: projectId, kind: "events", page: "1", page_size: "50" });
    if (status) params.set("status", status);
    return readPage<AlertEventRecord[]>(await fetch(`/internal/workbench/alerts?${params}`, { cache: "no-store" }));
  },
  async evaluateAlerts(projectId: string): Promise<{ count: number; events: AlertEventRecord[] }> {
    return readResponse(await fetch("/internal/workbench/alerts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, action: "evaluate" }),
    }));
  },
  async acknowledgeAlert(projectId: string, eventId: string, note?: string): Promise<AlertEventRecord> {
    return readResponse(await fetch("/internal/workbench/alerts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, event_id: eventId, action: "ack", note }),
    }));
  },
  async resolveAlert(projectId: string, eventId: string): Promise<AlertEventRecord> {
    return readResponse(await fetch("/internal/workbench/alerts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, event_id: eventId, action: "resolve" }),
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
  async checkPages(projectId: string, pageIds: string[]): Promise<PageCheckBatchResult> {
    return readResponse<PageCheckBatchResult>(await fetch(dataUrl("pages-check-batch", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ page_ids: pageIds }),
    }));
  },
  async importCrawlerEvents(projectId: string, events: Record<string, unknown>[], source?: string): Promise<CrawlerEventImportResult> {
    return readResponse<CrawlerEventImportResult>(await fetch(dataUrl("crawler-events-import", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ events, source: source || null }),
    }));
  },
  async importTrafficEvents(projectId: string, events: Record<string, unknown>[], source?: string): Promise<TrafficEventImportResult> {
    return readResponse<TrafficEventImportResult>(await fetch(dataUrl("traffic-events-import", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ events, source: source || null }),
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
  async withdrawQuote(projectId: string, id: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(dataUrl("quote-withdraw", projectId, { id }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    }));
  },
  async budgetApprovals(projectId: string, page = 1, filters: { status?: string; category?: string } = {}): Promise<ApiEnvelope<BudgetApproval[]>> {
    return readPage<BudgetApproval[]>(await fetch(dataUrl("budget-approvals", projectId, { page, page_size: 20, status: filters.status, category: filters.category }), { cache: "no-store" }));
  },
  async budgetApproval(projectId: string, id: string): Promise<BudgetApproval> {
    return readResponse<BudgetApproval>(await fetch(dataUrl("budget-approval", projectId, { id }), { cache: "no-store" }));
  },
  async publishReceipts(projectId: string, page = 1, filters: { has_budget?: boolean; has_page_approval?: boolean; channel_id?: string; task_id?: string } = {}, pageSize = 100): Promise<ApiEnvelope<PublishReceiptRecord[]>> {
    return readPage<PublishReceiptRecord[]>(await fetch(dataUrl("publish-receipts", projectId, {
      page, page_size: Math.min(100, Math.max(1, pageSize)),
      has_budget: filters.has_budget === undefined ? undefined : String(filters.has_budget),
      has_page_approval: filters.has_page_approval === undefined ? undefined : String(filters.has_page_approval),
      channel_id: filters.channel_id,
      task_id: filters.task_id,
    }), { cache: "no-store" }));
  },
  async linkBudgetReceipt(projectId: string, budgetId: string, receiptId: string): Promise<{ budget_approval_id: string; receipt_id: string; linked_receipt_count: number; remaining_quantity: number }> {
    return readResponse(await fetch(dataUrl("budget-receipt-link", projectId, { id: budgetId }), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ receipt_id: receiptId }),
    }));
  },
  async unlinkBudgetReceipt(projectId: string, budgetId: string, receiptId: string): Promise<{ budget_approval_id: string; receipt_id: string; linked_receipt_count: number; remaining_quantity: number }> {
    return readResponse(await fetch(dataUrl("budget-receipt-unlink", projectId, { id: budgetId, receipt_id: receiptId }), {
      method: "DELETE",
    }));
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
  async industryStatus(projectId: string): Promise<IndustryStatus> {
    return readResponse<IndustryStatus>(await fetch(onboardingUrl("status", projectId), { cache: "no-store" }));
  },
  async industryPresets(projectId: string): Promise<IndustryPresetOption[]> {
    return readResponse<IndustryPresetOption[]>(await fetch(onboardingUrl("presets", projectId), { cache: "no-store" }));
  },
  async onboardingPreview(projectId: string, input: Record<string, unknown>): Promise<OnboardingPreview> {
    return readResponse<OnboardingPreview>(await fetch(onboardingUrl("preview", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async onboardingApply(projectId: string, input: Record<string, unknown>): Promise<OnboardingApplyResult> {
    return readResponse<OnboardingApplyResult>(await fetch(onboardingUrl("apply", projectId), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async organizations(): Promise<OrganizationOverviewResult> {
    return readResponse<OrganizationOverviewResult>(await fetch("/internal/workbench/organizations?kind=overview", { cache: "no-store" }));
  },
  async createOrganization(input: { code: string; name: string }): Promise<OrganizationSummary> {
    return readResponse<OrganizationSummary>(await fetch("/internal/workbench/organizations", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async createProject(input: { code: string; name: string; organization_id: string }): Promise<Project> {
    return readResponse<Project>(await fetch("/internal/workbench/projects", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async organizationMembers(projectId: string): Promise<OrganizationMember[]> {
    return readResponse<OrganizationMember[]>(await fetch(`/internal/workbench/organization-members?project_id=${encodeURIComponent(projectId)}`, { cache: "no-store" }));
  },
  async addOrganizationMember(projectId: string, username: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(`/internal/workbench/organization-members?project_id=${encodeURIComponent(projectId)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username }),
    }));
  },
  async removeOrganizationMember(projectId: string, userId: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(`/internal/workbench/organization-members?project_id=${encodeURIComponent(projectId)}&user_id=${encodeURIComponent(userId)}`, { method: "DELETE" }));
  },
  async syncOrganizationMembers(projectId: string): Promise<Record<string, unknown>> {
    return readResponse<Record<string, unknown>>(await fetch(`/internal/workbench/organization-members?project_id=${encodeURIComponent(projectId)}&kind=sync`, { method: "POST" }));
  },
  async organizationSettings(projectId: string): Promise<OrganizationSettings> {
    return readResponse<OrganizationSettings>(await fetch(`/internal/workbench/organization?project_id=${encodeURIComponent(projectId)}`, { cache: "no-store" }));
  },
  async organizationUsage(projectId: string, days = 30): Promise<OrganizationUsageTrend> {
    return readResponse<OrganizationUsageTrend>(await fetch(`/internal/workbench/organization?kind=usage&days=${days}&project_id=${encodeURIComponent(projectId)}`, { cache: "no-store" }));
  },
  async saveOrganizationSettings(projectId: string, input: Record<string, unknown>): Promise<OrganizationSettings> {
    return readResponse<OrganizationSettings>(await fetch(`/internal/workbench/organization?project_id=${encodeURIComponent(projectId)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    }));
  },
  async consumption(projectId: string, start?: string, end?: string): Promise<ConsumptionSummary> {
    return readResponse<ConsumptionSummary>(await fetch(dataUrl("consumption", projectId, { start, end }), { cache: "no-store" }));
  },
  async consumptionEvents(
    projectId: string,
    options: { start?: string; end?: string; metric?: string; limit?: number } = {},
  ): Promise<ConsumptionEvent[]> {
    return readResponse<ConsumptionEvent[]>(await fetch(dataUrl("consumption-events", projectId, options), { cache: "no-store" }));
  },
  async organizationConsumption(organizationId: string, start?: string, end?: string): Promise<ConsumptionSummary> {
    const query = new URLSearchParams({ kind: "consumption", id: organizationId });
    if (start) query.set("start", start);
    if (end) query.set("end", end);
    return readResponse<ConsumptionSummary>(await fetch(`/internal/workbench/organizations?${query}`, { cache: "no-store" }));
  },
  async logout(): Promise<void> {
    await fetch("/internal/session", { method: "DELETE" });
  },
};
