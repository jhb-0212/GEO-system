export type Section =
  | "overview"
  | "projects"
  | "monitoring"
  | "diagnostics"
  | "channels"
  | "statistics"
  | "monthly"
  | "funnel"
  | "questions"
  | "samples"
  | "publishing"
  | "engines"
  | "reviews"
  | "leads"
  | "faq"
  | "materials"
  | "competitors"
  | "brand"
  | "metrics"
  | "facts"
  | "members"
  | "plans"
  | "opportunities"
  | "site-diagnostics"
  | "quotes"
  | "budget"
  | "activity"
  | "company"
  | "basic-info"
  | "feed-access"
  | "report"
  | "sentiment"
  | "board"
  | "closure"
  | "distribution"
  | "factory"
  | "adaptation"
  | "site"
  | "profile";

export type Tone = "blue" | "green" | "amber" | "red" | "slate";

export interface Project {
  id: string;
  code: string;
  name: string;
  owner: string;
  priority: number;
  businessConfirmedAt: string | null;
  businessConfirmedBy: string | null;
  status: "运行中" | "筹备中" | "已暂停" | "已归档";
  updatedAt: string;
  channels: number;
  tasks: number;
  roleCode?: string;
}

export interface MonitoringTask {
  id: string;
  serialNo?: string;
  question: string;
  questionTitle?: string;
  engine: string;
  engineCode?: string;
  entryName?: string | null;
  entryType?: string | null;
  entryUrl?: string | null;
  projectId: string;
  status: "进行中" | "待执行" | "已完成" | "需复核" | "失败" | "已取消" | "待核实";
  progress: number;
  updatedAt: string;
}

// B4 contract fields are kept as returned by the backend for later integration.
export interface MonitoringRound {
  id: string;
  project_id?: string;
  seq: number;
  name: string;
  is_baseline: boolean;
  status: string;
  planned_at: string | null;
  created_at: string | null;
}
export interface RetestPlanRecord {
  id: string;
  name: string;
  interval_days: number;
  first_run_at: string;
  next_run_at: string;
  entry_scope: string[];
  samples_per_cell: number;
  enabled: boolean;
  last_run_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  latest_round_id: string | null;
  latest_round_name: string | null;
  latest_round_status: string | null;
  latest_round_scheduled_for: string | null;
}
export interface RetestPlanRunResult {
  plan_id: string;
  plan_name: string;
  scheduled_for: string;
  round_id: string;
  status: string;
  created_task_count: number;
  api_task_count: number;
  manual_task_count: number;
}
export interface RoundCompletionResult {
  round: MonitoringRound;
  snapshot_id: string;
  snapshot_hash: string;
  captured_at: string;
  rule_version: string;
  task_counts: Record<string, number>;
}

export interface ChannelAlias { domain: string | null; alias_name: string | null }
export interface QuestionRecord {
  id: string; code: string; title: string; question_type: "brand" | "general";
  audience: string | null; intent: string | null; priority: number;
  status: "draft" | "active" | "archived"; current_version_no: number; current_text: string | null;
  created_at?: string; updated_at?: string;
}
export interface QuestionVersionRecord {
  id: string; question_id: string; version_no: number; text: string; change_note: string | null; created_at: string; created_by?: string | null;
}
export interface KeywordRecord {
  id: string; name: string; category: string | null; priority: number; is_active: boolean;
  notes: string | null; content_version_ids: string[]; created_at?: string; updated_at?: string;
}
export interface MonitoringTaskRecord {
  id: string; serial_no: number; round_id: string; status: string; sampling_no: number;
  question_code: string; question_title: string; engine_code: string; engine_name: string;
  entry_name?: string | null; entry_type?: string | null; entry_url?: string | null;
  trace_id?: string | null; created_at: string; updated_at: string;
}
export interface SampleRecord {
  id: string; serial_no: number; task_id: string; status: string; attempt_no: number; sampled_at: string | null;
  trace_id?: string | null; latency_ms?: number | null; total_tokens?: number | null; estimated_cost_cny?: number | null;
  raw_answer?: string | null; answer_excerpt?: string | null; brand_mentioned: boolean | null; brand_identified?: boolean | null; failure_code: string | null;
  conversation_id?: string | null; conversation_mode?: string | null;
  brand_match_kind?: string | null; brand_match_term?: string | null; matcher_version?: string | null;
  failure_note?: string | null;
  review_result: string | null; review_note: string | null;
  reviewed_at?: string | null; reviewed_by?: string | null;
  evidence_count?: number;
}
export interface ManualSampleCreated {
  sample_id: string; task_id: string; task_status: string; attempt_no: number; status: string;
  answer_kind: string; brand_mentioned: boolean; brand_identified: boolean; citation_count: number;
}
export interface ManualFailureCreated {
  sample_id: string; serial_no: number; task_id: string; task_status: string; attempt_no: number;
  status: string; failure_code: string; failure_note: string | null; sampling_mode: string | null;
  conversation_id: string; conversation_mode: string;
}
export interface DiagnosticSample {
  sample_id: string; serial_no: number; task_id: string; trace_id: string | null; sample_status: string; task_status: string;
  attempt_no: number; retry_count: number; sampled_at: string | null; finished_at: string | null;
  failure_code: string | null; failure_note: string | null; latency_ms: number | null;
  total_tokens: number | null; estimated_cost_cny: number | null; gateway_version: string | null;
  engine_code: string | null; engine_name: string | null; question_code: string | null; question_title: string | null;
}
export interface SampleDetail extends SampleRecord {
  brand_match_offset?: number | null; brand_match_offset_end?: number | null;
  brand_match_evidence?: string | null; brand_list_rank?: number | null;
  raw_response?: Record<string, unknown> | null;
  request_payload?: Record<string, unknown> | null;
  sampling_mode: string; model_version?: string | null; engine_model?: string | null;
  conversation_id?: string | null; conversation_mode?: string | null;
  competitor_matches: { competitor_id: string; competitor_name: string; position: number | null; position_verified: boolean; evidence_text: string | null }[];
  engine_code?: string | null; engine_name?: string | null; engine_entry_id?: string | null;
  entry_name?: string | null; entry_type?: string | null;
  round_id?: string | null; round_seq?: number | null; round_name?: string | null;
  round_status?: string | null; round_snapshot_hash?: string | null;
  question_id?: string | null; question_code?: string | null; question_title?: string | null;
  question_version_id?: string | null; question_version_no?: number | null; question_text?: string | null;
  question_type?: string | null; question_intent?: string | null;
  citations: { citation_id: string; raw_url: string; normalized_url?: string | null; domain: string | null; title?: string | null; site_name?: string | null; snippet?: string | null; published_at?: string | null; citation_order?: number | null; is_domain_level?: boolean; source_category?: string | null; page_type?: string | null; source_category_source?: string | null; page_type_source?: string | null; classification_rule_version?: string | null; review_status: string; is_brand_related: boolean; channel_id?: string | null; channel_name?: string | null }[];
  evidence_files: { evidence_id: string; file_type: string; content_type: string | null; byte_size: number | null; checksum: string | null }[];
}
export interface CitationRecord {
  citation_id: string; sample_id: string; raw_url: string; normalized_url?: string | null; domain: string | null;
  title?: string | null; site_name?: string | null; snippet?: string | null; published_at?: string | null; position?: number | null;
  source_category?: string | null; page_type?: string | null;
  classification_source?: string | null; classification_rule_version?: string | null;
  review_status: string; review_note: string | null; channel_id: string | null; competitor_id: string | null;
  is_brand_related: boolean;
}
export interface CitationAnswerOption {
  trace_id: string;
  question_title: string;
  question_text: string;
  engine_name: string;
  entry_name: string;
  answer_excerpt: string | null;
  sampled_at: string | null;
  citation_ids: string[];
  citation_count: number;
  domains: string[];
}
export interface SourceReviewRecord {
  review_id: string; domain: string; status: string;
  source_category: string | null; suggested_source_category: string | null;
  classification_source: string | null; rule_version: string | null;
  citation_count: number; sample_count: number;
  last_sampled_at: string | null; reviewed_at: string | null; review_note: string | null;
}
export interface StatSnapshotRecord {
  snapshot_id: string; round_id: string; captured_at: string; captured_by: string | null;
  rule_version: string; matcher_version: string; classifier_version: string;
  snapshot_hash: string; scope: Record<string, unknown>; metrics: Record<string, unknown>;
  definitions: Record<string, unknown>;
}
export interface FactRecord {
  id: string; fact_type: string; fact_key: string; fact_value: string;
  source_document: string | null; source_url: string | null; owner: string | null;
  approval_status: string; effective_from: string | null; effective_until: string | null;
  version_no: number; superseded_by: string | null;
  business_confirmed: boolean; business_confirmed_note: string | null;
  created_by: string | null; approved_by: string | null; approved_at: string | null;
  rejection_note: string | null; created_at: string; updated_at: string;
}
export interface FactVersionRecord {
  version_no: number; action: string; snapshot: Record<string, unknown>;
  previous_snapshot: Record<string, unknown> | null; change_note: string | null;
  actor_id: string | null; created_at: string;
}
export interface FactTypeOption { value: string; label: string }
export interface FactClaimRecord {
  id: string; serial_no: number; sample_id: string; citation_id: string | null; claim_text: string;
  fact_id: string | null; verdict: string | null; source_url: string | null;
  reviewed_by: string | null; reviewed_at: string | null; correction_task_id: string | null;
  created_at: string;
}
export interface CorrectionTaskRecord {
  id: string; claim_id: string | null; fact_id: string | null; title: string;
  description: string | null; source_url: string | null; status: string; priority: number;
  created_by: string | null; resolved_at: string | null; created_at: string;
}
export interface UnknownDomainRecord {
  channel_id: string; code: string; name: string; primary_domain: string | null;
  citation_count: number; sample_count: number; last_sampled_at: string | null;
}
export interface PublishTaskRecord {
  id: string;
  serial_no: number;
  status: string;
  publish_mode?: "manual" | "api" | "authorized" | string;
  handoff_reason?: string | null;
  handoff_note?: string | null;
  channel_id: string;
  account_id?: string | null;
  account_name?: string | null;
  version_id: string;
  version_no: number;
  version_title?: string | null;
  trace_id?: string | null;
  receipt_id?: string | null;
  published_url?: string | null;
  received_at?: string | null;
  budget_approval_id?: string | null;
  budget_title?: string | null;
}
export interface PublishAccountRecord {
  id: string;
  account_name: string;
  channel_id: string;
  is_active: boolean;
  notes?: string | null;
  task_count?: number;
  oauth_connection_id?: string | null;
  oauth_status?: string | null;
  oauth_provider_code?: string | null;
  oauth_external_account_name?: string | null;
}
export interface OAuthProviderRecord {
  code: string;
  name: string;
  scopes: string[];
}
export interface OAuthConnectionRecord {
  id: string;
  provider_code: string;
  provider_name: string;
  channel_id: string | null;
  external_account_id: string;
  external_account_name: string | null;
  external_account_email: string | null;
  scopes: string[];
  status: "connected" | "revoked" | "error";
  has_refresh_token: boolean;
  expires_at: string | null;
  connected_at: string | null;
  last_refreshed_at: string | null;
  revoked_at: string | null;
}
export interface OAuthAuthorizeResult {
  authorization_url: string;
  state: string;
  expires_at: string;
}
export interface ContentVersionRecord { version_id: string; item_id: string; title: string; version_no: number; status: string; status_label?: string; kind: string; channel_id: string | null; author_name?: string | null; submitted_at?: string | null }
export interface ContentFactLink {
  fact_id: string; fact_type: string; fact_key: string; fact_value: string;
  approval_status: string; current_version_no: number; linked_version_no: number;
  stale: boolean; warning: string | null;
}
export interface ContentVersionDetail extends ContentVersionRecord { kind: string; channel_id: string | null; body: string; content_hash: string; change_note: string | null; question_ids: string[]; citation_ids: string[]; fact_ids: string[]; fact_links: ContentFactLink[] }
export interface ContentVersionLinks { version_id: string; question_ids: string[]; citation_ids: string[]; fact_ids: string[]; fact_links: ContentFactLink[] }
export interface EvidenceUploadResult { evidence_id: string; sample_id: string; file_type: string; content_type: string | null; byte_size: number; checksum: string }
export interface ContentExportPackage {
  version_id: string;
  item_id: string;
  title: string;
  slug_suggestion: string;
  version_no: number;
  status: string;
  canonical_hint: string | null;
  meta_description: string;
  markdown: string;
  html: string;
  jsonld: Record<string, unknown>[];
  checklist: string[];
  content_hash: string;
}
export interface ContentReviewRecord { id: string; decision: string; reviewer_name: string | null; comment: string | null; created_at: string }
export interface ChannelApprovalRecord {
  id: string;
  submitted_by: string | null;
  submitted_by_name: string | null;
  submitted_at: string | null;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  decision: string | null;
  comment: string | null;
  created_at: string | null;
}
export interface ChannelRecord {
  id: string;
  code: string;
  name: string;
  category: string;
  status: string;
  approval_status: string;
  primary_domain: string | null;
  publish_url?: string | null;
  login_url?: string | null;
  owner_name?: string | null;
  owner_contact?: string | null;
  notes?: string | null;
  is_active?: boolean;
  submitted_by?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  decision_comment?: string | null;
  aliases?: ChannelAlias[];
}
export interface ChannelDetailRecord extends ChannelRecord {
  notes: string | null;
  is_active: boolean;
  aliases: ChannelAlias[];
  citation_count: number;
  sample_count: number;
  page_count: number;
  citation_page: number;
  citation_page_size: number;
  page_urls: string[];
  engine_codes: string[];
  question_codes: string[];
  first_sampled_at: string | null;
  last_sampled_at: string | null;
  approvals: ChannelApprovalRecord[];
  citations: { citation_id: string; engine_name: string; question_code: string; raw_url: string; title?: string | null; site_name?: string | null; snippet?: string | null; published_at?: string | null; review_status: string; sampled_at: string | null }[];
  observed_domain_count: number;
  observed_citation_count: number;
  observed_sample_count: number;
  observed_page_count: number;
  observed_page_urls: string[];
  observed_engine_codes: string[];
  observed_question_codes: string[];
  observed_citations: { citation_id: string; engine_name: string; question_code: string; raw_url: string; title?: string | null; site_name?: string | null; snippet?: string | null; published_at?: string | null; review_status: string; sampled_at: string | null }[];
}
export interface ChannelAnomalyRecord {
  code: string;
  severity: "high" | "warning";
  channel_id: string;
  channel_code: string;
  channel_name: string;
  channel_status: string;
  task_id: string | null;
  task_status: string | null;
  receipt_id: string | null;
  published_url: string | null;
  message: string;
  recommended_action: string;
  task_updated_at: string | null;
  receipt_received_at: string | null;
}
export interface ChannelAnomalyList {
  generated_at: string;
  counts: { total: number; high: number; warning: number };
  anomalies: ChannelAnomalyRecord[];
}
export interface EngineRecord { id: string; code: string; name: string; vendor: string; is_active: boolean }
export interface EngineEntryRecord {
  id: string; engine_id: string; entry_type: string; name: string; entry_url: string | null;
  protocol: string; model_name: string | null; credential_ref: string | null;
  credential_configured: boolean; config_redacted?: boolean; supports_search: boolean; supports_citation?: boolean; access_note: string | null;
  /** 密钥来源：database=系统内填写（加密落库） / environment=服务器环境变量 / none */
  credential_source?: "database" | "environment" | "none" | null;
  credential_updated_at?: string | null;
  last_verified_at: string | null; is_active: boolean;
}
export interface EngineConnectionResult {
  success: boolean; protocol: string; endpoint: string | null; model_name: string | null;
  latency_ms: number | null; error_code: string | null; message: string; checked_at: string;
}

export interface StatsOverview {
  valid_answers: number;
  brand_mentioned_answers: number;
  brand_identified_answers: number;
  citation_answers: number;
  citation_observable_answers: number;
  citation_unobservable_answers: number;
  brand_mention_rate: number | null;
  brand_identified_rate: number | null;
  citation_rate: number | null;
  channel_count: number;
  channel_total: number;
  observed_channel_count: number;
  page_count: number;
  excluded: { failed: number; manual_review: number; no_answer_surface: number; pending_or_running: number };
  failure_breakdown?: Record<string, number>;
}
export interface StatsAnswerKindOverview extends StatsOverview {
  answer_kind: "answer" | "search_result";
}
export interface StatsSource {
  domain: string;
  citations: number;
  samples: number;
  brand_related: number;
  channel_citations: number;
  last_sampled_at: string | null;
}
export interface StatsPublishVisibility {
  receipt_id: string;
  published_url: string;
  checked_at: string | null;
  matched: boolean;
  position: number | null;
  matched_url: string | null;
  query: string;
  site: string | null;
  result_count: number;
  error_code: string | null;
}
export interface StatsEngine {
  engine_id: string; engine_code: string; engine_name: string;
  valid_answers: number; brand_mentioned_answers: number; brand_identified_answers: number; citation_answers: number;
  citation_observable_answers: number; citation_unobservable_answers: number;
  brand_mention_rate: number | null; brand_identified_rate: number | null; citation_rate: number | null;
}
export interface StatsQuestion {
  question_id: string; question_code: string; question_title: string; question_type: string;
  valid_answers: number; brand_mentioned_answers: number; brand_identified_answers: number; citation_answers: number;
  citation_observable_answers: number; citation_unobservable_answers: number;
  brand_mention_rate: number | null; brand_identified_rate: number | null; citation_rate: number | null;
}
export interface EngineHealth {
  engine_id: string; engine_code: string; engine_name: string;
  entry_id: string; entry_name: string; protocol: string; model_name: string | null;
  is_active: boolean; entry_url_configured: boolean; credential_configured: boolean; price_configured: boolean;
  task_count: number; sample_count: number; valid_answers: number; failed_count: number;
  failure_rate: number | null; avg_latency_ms: number | null; total_tokens: number;
  estimated_cost_cny: number | null; last_sampled_at: string | null;
  availability: "disabled" | "no_endpoint" | "no_credentials" | "untested" | "healthy" | "degraded" | "failing"; access_note: string | null;
}
export interface GeoOverview {
  valid_answers: number; mention_rate: number | null; citation_share: number | null; sov: number | null;
  sentiment: { positive: number; neutral: number; negative: number; not_mentioned: number; positive_rate: number | null; average_score: number | null; kpi_eligible?: boolean; basis?: string | null };
  brand_position: { sample_count: number; average_rank: number | null; top1_rate: number | null };
  prompt_coverage: number | null; freshness_hours: number | null; fresh_24h_rate: number | null; failure_rate: number | null;
  statement: string;
  counts: Record<string, number>;
  by_competitor: { competitor: string; mentioned_samples: number }[];
}
export interface LeadVisitorBucket { label: string; count: number }

export interface LeadVisitorReport {
  total_leads: number;
  valid_leads: number;
  distinct_visitors: number;
  leads_with_visitor: number;
  repeat_rate: number | null;
  by_region: LeadVisitorBucket[];
  by_source: LeadVisitorBucket[];
  unread_messages: number;
}

export interface LeadFunnelStage {
  key: string; label: string; count: number; rate: number | null; step_rate: number | null;
}
export interface LeadFunnelGroup {
  key: string; label: string; total: number; valid: number; contacted: number; enrolled: number;
}
export interface LeadFunnelAiAttribution {
  crawler_events: number;
  verified_bot_events: number;
  human_visits: number;
  trackable_visits: number;
  human_sessions: number;
  monitored_citations: number;
  monitored_citation_urls: number;
  self_reported_ai_leads: number;
  engine_attributed_leads: number;
  self_reported_ai_valid_leads: number;
}
export interface LeadFunnel {
  start_at: string | null; end_at: string | null;
  total: number; valid: number; contacted: number; enrolled: number; lost: number;
  status_counts: { unknown: number; contacted: number; enrolled: number; lost: number };
  contact_rate: number | null; conversion_rate: number | null;
  stages: LeadFunnelStage[];
  ai_attribution: LeadFunnelAiAttribution;
  by_source: LeadFunnelGroup[];
  by_channel: LeadFunnelGroup[];
  by_question: LeadFunnelGroup[];
}
export interface MonthlyAnswerStats {
  valid_answers: number; brand_mentioned_answers: number; citation_answers: number;
  brand_identified_answers: number; citation_observable_answers: number; citation_unobservable_answers: number;
  brand_mention_rate: number | null; brand_identified_rate: number | null; citation_rate: number | null;
  total_samples: number; failure_rate: number | null; fresh_24h_rate: number | null; prompt_coverage: number | null;
}
export interface MonthlyReport {
  month: string; period_start: string; period_end: string;
  tasks: { total: number; done: number; failed: number; running: number; pending: number; completion_rate: number | null };
  answers: MonthlyAnswerStats;
  answer_breakdown?: { general: MonthlyAnswerStats; brand: MonthlyAnswerStats } | null;
  leads: LeadFunnel | null;
  published_receipts: number;
}
export interface MonthlyReportSnapshotSummary {
  snapshot_id: string;
  month: string;
  period_start: string;
  period_end: string;
  captured_at: string;
  captured_by: string | null;
  captured_by_name: string | null;
  rule_version: string;
  snapshot_hash: string;
  tasks_total: number;
  valid_answers: number;
  brand_mention_rate: number | null;
  general_brand_mention_rate?: number | null;
  brand_brand_mention_rate?: number | null;
  brand_identified_rate?: number | null;
  citation_rate: number | null;
  citation_observable_answers?: number | null;
  citation_unobservable_answers?: number | null;
  published_receipts: number;
}
export interface MonthlyReportSnapshot extends MonthlyReportSnapshotSummary {
  definitions: Record<string, unknown>;
  report: MonthlyReport;
}
export interface TraceChain {
  trace_id: string; found: boolean;
  rounds: { id: string; seq: number; status: string }[];
  tasks: { id: string; serial_no: number; round_id: string; status: string; question_code: string | null; question_title: string | null; question_version_id: string; version_no: number; engine_code: string; engine_name: string; entry_name: string; sampling_mode: string }[];
  samples: { id: string; serial_no: number; task_id: string; attempt_no: number; status: string; brand_mentioned: boolean | null; failure_code: string | null; failure_note: string | null; latency_ms: number | null; total_tokens: number | null; estimated_cost_cny: number | null; gateway_version: string | null; sampled_at: string | null }[];
  citations: { id: string; sample_id: string; domain: string | null; raw_url: string; title?: string | null; site_name?: string | null; snippet?: string | null; published_at?: string | null; is_brand_related: boolean; citation_usage: string | null; review_status: string | null }[];
  content_versions: { id: string; item_id: string; item_title: string; version_no: number; status: string; content_hash: string }[];
  publish_tasks: { id: string; serial_no: number; version_id: string; status: string; publish_mode: string; channel_name: string | null; account_name: string | null; trace_id: string | null; created_at: string | null }[];
  counts: { rounds: number; tasks: number; samples: number; citations: number; content_versions: number; publish_tasks: number };
}

export interface BatchGenerationResult {
  round_id: string;
  requested_question_count: number;
  eligible_question_count: number;
  expected_question_count?: number;
  inactive_question_count: number;
  inactive_question_ids: string[];
  inactive_questions: { id: string; code: string; title: string; status: string }[];
  question_version_missing_count: number;
  question_version_missing_question_ids: string[];
  engine_count: number;
  expected_engine_count?: number;
  engine_entry_count?: number;
  missing_engine_entry_count?: number;
  expected_engine_entry_count?: number;
  requested_entry_types?: string[];
  samples_per_cell?: number;
  expected_task_count: number;
  eligible_expected_task_count: number;
  created_task_count: number;
  reused_task_count: number;
  generated_task_count: number;
  complete: boolean;
  skipped_reason: "question_version_missing" | "engine_entries_insufficient" | "no_active_question" | "inactive_questions" | null;
}

export interface CompanyProduct {
  name: string;
  summary?: string | null;
  highlights?: string | null;
}

/**
 * 企业档案（对标「基础信息 / 企业智能体画像」）。
 * completeness / missing / conflicts 由后端算，前端不重复实现规则；
 * conflicts 里是 `字段:fact_id` 键，只有带进 acknowledged_conflicts 才允许保存。
 */
export interface CompanyProfileRecord {
  configured: boolean;
  legal_name?: string | null;
  brand_name?: string | null;
  slogan?: string | null;
  province?: string | null;
  headcount?: string | number | null;
  founded_on?: string | null;
  business_phone?: string | null;
  service_hotline?: string | null;
  contact_email?: string | null;
  stores: string[];
  official_urls: string[];
  /** 官网地址的唯一写入口在品牌设置，档案里只是派生只读值。 */
  official_urls_source?: "brand_profile";
  industries: string[];
  regions: string[];
  products: CompanyProduct[];
  description?: string | null;
  highlights?: string | null;
  pain_points?: string | null;
  story?: string | null;
  founder_intro?: string | null;
  extra?: unknown;
  is_active?: boolean;
  updated_at?: string | null;
  completeness: number;
  missing: string[];
  conflicts: string[];
}

export interface StartupMaterialItemRecord {
  key: string;
  label: string;
  status: "ready" | "partial" | "missing";
  count: number;
  detail: string;
}

export interface DistributionCheckRecord {
  key: string;
  label: string;
  ok: boolean;
  detail: string;
}

export interface DistributionBatchRecord {
  id: string;
  name: string;
  status: "blocked" | "ready" | "dispatched";
  target_engines: string[];
  engine_names: string[];
  precheck: { ready: boolean; status: string; checks: DistributionCheckRecord[]; failed: string[] } | null;
  notes: string | null;
  item_count: number;
  items: { version_id: string; title: string }[];
  last_checked_at: string | null;
  dispatched_at: string | null;
  created_at: string;
}

export interface PublishClosureItemRecord {
  task_id: string;
  serial_no: number;
  task_status: string;
  channel_name: string | null;
  content_title: string;
  scheduled_at: string | null;
  receipt_id: string | null;
  published_url: string | null;
  published_host: string | null;
  received_at: string | null;
  visibility_checked_at: string | null;
  visibility_matched: boolean | null;
  visibility_error_code: string | null;
  cited: boolean;
  stage: string;
  stage_label: string;
  hint: string;
}

export interface PublishClosureRecord {
  items: PublishClosureItemRecord[];
  counts: Record<string, number>;
  summary: {
    total_tasks: number;
    tasks_with_receipt: number;
    closed: number;
    closure_rate: number | null;
    broken_before_receipt: number;
    broken_after_receipt: number;
  };
  caveats: string[];
}

export interface QualityItemRecord {
  key: string;
  label: string;
  detail: string;
}

export interface ContentQualityReport {
  ok: boolean;
  blockers: QualityItemRecord[];
  warnings: QualityItemRecord[];
  counts: { blockers: number; warnings: number };
  version_id: string;
  content_hash: string;
}

export interface DerivationCheckRecord {
  key: string;
  label: string;
  ok: boolean;
  detail: string;
}

export interface ChannelDerivationRecord {
  id: string;
  channel_item_id: string;
  channel_item_title: string | null;
  channel_name: string | null;
  channel_category: string | null;
  channel_category_label: string;
  item_status: string | null;
  version_status: string | null;
  source_content_hash: string;
  source_version_id: string;
  stale: boolean;
  checks: DerivationCheckRecord[];
  created_at: string;
  synced_at: string | null;
  master_item_title?: string | null;
  master_version_no?: number | null;
}

export interface MasterDerivationList {
  master_item_id: string;
  master_title: string;
  master_version_no: number;
  master_version_status: string;
  master_hash: string;
  derivations: ChannelDerivationRecord[];
  stale_count: number;
}

export interface ContentTemplateSlot {
  key: string;
  label: string;
  required: boolean;
}

export interface ContentTemplateRecord {
  id: string;
  name: string;
  channel_category: string | null;
  question_type: string | null;
  skeleton: string;
  slots: ContentTemplateSlot[];
  notes: string | null;
  is_active: boolean;
  created_at: string;
}

export interface TemplateGenerationRecord {
  item_id: string;
  version_id: string;
  title: string;
  body: string;
  content_hash: string;
  status: string;
}

export interface PublishBoardItemRecord {
  receipt_id: string;
  task_serial_no: number;
  channel_name: string | null;
  content_title: string | null;
  published_url: string;
  published_host: string | null;
  received_at: string;
  verified_at: string | null;
  visibility_checked_at: string | null;
  visibility_matched: boolean | null;
  visibility_position: number | null;
  visibility_error_code: string | null;
  cited: boolean;
}

export interface PublishBoardRecord {
  items: PublishBoardItemRecord[];
  summary: {
    total_receipts: number;
    visibility_checked: number;
    visibility_matched: number;
    visibility_errored: number;
    cited: number;
    visibility_match_rate: number | null;
    cited_rate: number | null;
  };
  caveats: string[];
}

export interface SentimentSummaryRecord {
  total_reviewed_citations: number;
  labeled: number;
  unlabeled: number;
  counts: { positive: number; neutral: number; negative: number };
  coverage: number | null;
  generated_at: string;
}

export interface SentimentItemRecord {
  citation_id: string;
  title: string | null;
  excerpt: string | null;
  url: string;
  domain: string | null;
  source_category: string;
  page_type: string | null;
  published_at: string | null;
  polarity: "positive" | "neutral" | "negative" | null;
  note: string | null;
  grade: string | null;
  labeled_at: string | null;
  credibility_score: number;
  credibility_tier: string;
}

export interface DiagnosisDimensionRecord {
  key: string;
  label: string;
  value: number | null;
  numerator: number;
  denominator: number;
  unit: string;
  definition: string;
  basis: string;
  extra: Record<string, unknown>;
  has_data: boolean;
}

export interface DiagnosisReportRecord {
  generated_at: string;
  scope: {
    round_id?: string | null;
    engine_id?: string | null;
    question_id?: string | null;
    start_at?: string | null;
    end_at?: string | null;
    answer_kind?: string | null;
    question_type?: string | null;
    valid_answers: number;
    excluded: Record<string, number>;
  };
  dimensions: DiagnosisDimensionRecord[];
  caveats: string[];
}

export interface ProjectContactRecord {
  id: string;
  project_id: string;
  channel: string;
  channel_label: string;
  value: string;
  label: string | null;
  is_public: boolean;
  sort_order: number;
  notes: string | null;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

/** 投喂材料盘点：`missing` 是后端算好的缺口，不用 0 或空值假装已具备。 */
export interface StartupMaterialsRecord {
  ready: boolean;
  missing: string[];
  items: StartupMaterialItemRecord[];
  generated_at: string;
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
  serialNo?: string;
  contactName: string;
  phone: string;
  interest: string;
  source: string;
  projectId: string;
  reportedAiProduct?: string | null;
  isValid?: boolean;
  status: "待跟进" | "跟进中" | "已转化" | "已流失";
  createdAt: string;
  note?: string | null;
  ownerName?: string | null;
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

export interface FaqRecord {
  id: string;
  project_id: string;
  question: string;
  answer: string;
  category?: string | null;
  status: "draft" | "pending_review" | "rejected" | "published" | "unpublished";
  sort_order: number;
  deleted_at?: string | null;
  deleted_by?: string | null;
  review_comment?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface MaterialRecord {
  id: string;
  project_id: string;
  title: string;
  category: "image" | "video" | "document" | "case";
  group_name?: string | null;
  sort_order?: number;
  source?: string | null;
  description: string | null;
  file_name: string;
  content_type: string | null;
  byte_size: number;
  checksum: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CompetitorRecord {
  id: string;
  name: string;
  domain: string | null;
  is_active: boolean;
  notes: string | null;
  created_at?: string;
  updated_at?: string | null;
}

export interface BrandProfileRecord {
  configured: boolean;
  canonical_name: string | null;
  aliases: string[];
  identifiers: string[];
  owned_domains: string[];
  notes: string | null;
  is_active: boolean;
  updated_at?: string | null;
  /** 生效词表：采集与统计实际使用的就是这三组，界面必须原样展示以便自查口径 */
  effective_mention_terms: string[];
  effective_identifier_terms: string[];
  effective_owned_domains: string[];
}

export interface BrandGovernanceOwnerRecord {
  name: string;
  contact: string | null;
  channels: number;
}

export interface BrandGovernanceRecord {
  configured: boolean;
  domains: string[];
  mention_terms: number;
  identifier_terms: number;
  materials_total: number;
  materials_by_category: Record<string, number>;
  channels_total: number;
  channels_with_owner: number;
  channel_owners: BrandGovernanceOwnerRecord[];
  ready: boolean;
  missing: string[];
}

export interface MetricDefinitionRecord {
  id: string;
  code: string;
  name: string;
  rule_version: number;
  formula: string;
  description: string | null;
  effective_from: string;
  effective_to: string | null;
  status: "active" | "retired";
  created_at?: string;
  updated_at?: string | null;
}

export interface MemberRecord {
  member_id: string;
  user_id: string;
  username: string | null;
  display_name: string | null;
  email: string | null;
  role_code: string | null;
  is_active: boolean;
}

export interface UserCandidate {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
}

export interface PlanRecord {
  id: string;
  title: string;
  plan_type: "article" | "video";
  status: string;
  channel_id: string | null;
  content_item_id: string | null;
  site_page_id: string | null;
  owner_id: string | null;
  owner_name: string | null;
  scheduled_at: string | null;
  notes: string | null;
  is_published: boolean;
  publish_url: string | null;
  published_at: string | null;
  play_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface OpportunityRecord {
  id: string;
  title: string;
  gap_type: string;
  status: string;
  question_id: string | null;
  sample_id: string | null;
  evidence_refs: Record<string, unknown>[];
  score_factors: Record<string, number>;
  score_weights: Record<string, number>;
  priority_score: number;
  owner_id: string | null;
  owner_name: string | null;
  linked_content_plan_id: string | null;
  linked_content_item_id: string | null;
  linked_publish_task_id: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface PageRecord {
  id: string;
  slug: string;
  title: string;
  page_type: string;
  url: string;
  canonical_url: string | null;
  publish_status: string;
  content_item_id: string | null;
  last_published_at: string | null;
  robots_allowed: boolean | null;
  in_sitemap: boolean | null;
  canonical_ok: boolean | null;
  http_status: number | null;
  js_dependent: boolean | null;
  checked_at: string | null;
  check_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SiteDiagnosticsSummary {
  pages_total: number;
  pages_checked: number;
  robots_blocked: number;
  not_in_sitemap: number;
  canonical_bad: number;
  http_error: number;
  js_dependent: number;
  crawler_events: number;
  verified_bot_events: number;
  crawled_pages: number;
  traffic_events: number;
  bot_traffic_events: number;
  visitor_sessions: number;
  leads_with_session: number;
  buckets: Record<string, number>;
}

export interface PageCheckResult {
  id: string;
  url: string;
  canonical_url: string | null;
  robots_allowed: boolean | null;
  in_sitemap: boolean | null;
  canonical_ok: boolean | null;
  http_status: number | null;
  js_dependent: boolean | null;
  checked_at: string;
  check_error: string | null;
}

export interface PageCheckBatchResult {
  checked: number;
  errors: number;
  items: PageCheckResult[];
}

export interface CrawlerEventImportResult {
  imported: number;
  matched_pages: number;
}

export interface TrafficEventImportResult {
  imported: number;
}

export interface QuoteRecord {
  id: string;
  plan_id: string;
  plan_title: string | null;
  channel_id: string | null;
  channel_name: string | null;
  unit_price: number;
  quantity: number;
  currency: string;
  budget: number;
  status: "pending" | "approved" | "rejected" | "withdrawn";
  approved_by: string | null;
  approved_by_name: string | null;
  approved_at: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export type BudgetCategory = "development_hours" | "content_production" | "media_placement" | "monitoring_service";
export type BudgetApprovalStatus = "pending" | "approved" | "rejected";

export interface BudgetReceipt {
  receipt_id: string;
  task_id: string;
  published_url: string;
  received_at: string;
}

export interface PublishReceiptRecord {
  id: string;
  task_id: string;
  serial_no: number;
  channel_id: string;
  channel_name: string | null;
  published_url: string;
  page_approval_id: string | null;
  received_at: string;
  verified_at: string | null;
  budget_approval_id: string | null;
  budget_title: string | null;
}

export type PageApprovalStatus = "pending" | "approved" | "rejected" | "revoked";
export type PagePermission = "official" | "authorized" | "third_party";

export interface PageApprovalRecord {
  id: string;
  channel_id: string;
  channel_name: string | null;
  page_url: string;
  normalized_url: string;
  url_key: string;
  title: string | null;
  page_type: string;
  permission: PagePermission;
  status: PageApprovalStatus;
  can_publish: boolean;
  requested_by: string;
  requested_by_name: string | null;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface BudgetApproval {
  id: string;
  category: BudgetCategory;
  title: string;
  quantity: number | null;
  unit: string | null;
  unit_price: number | null;
  amount: number;
  currency: string;
  status: BudgetApprovalStatus;
  media_quote_id?: string | null;
  media_quote?: QuoteRecord | null;
  media_quote_channel_name?: string | null;
  linked_receipt_count?: number;
  remaining_quantity?: number | null;
  receipt_complete?: boolean;
  receipts?: BudgetReceipt[];
  requested_by: string | null;
  requested_by_name: string | null;
  approved_by: string | null;
  approved_by_name: string | null;
  approved_at: string | null;
  note: string | null;
  decision_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface Activity {
  id: string;
  serialNo?: string;
  actor: string;
  action: string;
  target: string;
  time: string;
  tone: Tone;
}

export interface AuditLogRecord {
  id: string;
  serial_no: number;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  payload?: Record<string, unknown> | null;
  created_at: string;
}

export interface WorkbenchSnapshot {
  source: "mock" | "live";
  userName?: string;
  username?: string;
  currentUserId?: string;
  isSystemAdmin?: boolean;
  /** 当前所选项目内的成员角色码；系统管理员未加入该项目时为 null */
  projectRoleCode?: string | null;
  permissions?: string[];
  globalPermissions?: string[];
  brandMentionRate?: number | null;
  leadAccess: "allowed" | "forbidden" | "unavailable";
  projects: Project[];
  tasks: MonitoringTask[];
  reviews: ReviewItem[];
  leads: Lead[];
  activities: Activity[];
  activityTotal?: number;
  /** 后端真实总数：tasks/reviews 受单次加载上限影响，计数必须用 total 而不是数组长度 */
  taskTotal?: number;
  reviewTotal?: number;
  /** 任一聚合列表被截断：界面需显式提示「已加载 X / 共 Y」，不能静默少算 */
  truncated?: boolean;
  activeProjectId?: string;
  trend: (number | null)[];
  /** 与 trend 一一对应的自然日，用于横轴展示真实年月日 */
  trendDates?: string[];
  engines: { name: string; share: number; color: string }[];
}

export interface ApiEnvelope<T> {
  data: T;
  meta?: { page: number; page_size: number; total: number };
}

export interface ApiErrorEnvelope {
  error: { code: string; message: string };
}

export interface CertificationRecord {
  id: string;
  project_id: string;
  name: string;
  category: string | null;
  issuer: string | null;
  cert_no: string | null;
  issued_on: string | null;
  expires_on: string | null;
  status: "valid" | "expiring" | "expired" | null;
  days_left: number | null;
  evidence_url: string | null;
  notes: string | null;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface MyProfileRecord {
  id: string;
  username: string;
  display_name: string;
  job_title?: string | null;
  phone?: string | null;
  wechat?: string | null;
  is_system_admin: boolean;
}


export interface SiteModuleRecord {
  id: string;
  module_type: "home" | "services" | "news" | "download" | "poster" | "card";
  title: string;
  content: Record<string, unknown>;
  sort_order: number;
  is_active: boolean;
}

export interface SiteRecord {
  slug: string;
  title: string;
  intro: string | null;
  is_published: boolean;
  modules: SiteModuleRecord[];
}
