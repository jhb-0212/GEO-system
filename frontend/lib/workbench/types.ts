export type Section =
  | "overview"
  | "projects"
  | "monitoring"
  | "diagnostics"
  | "channels"
  | "statistics"
  | "geo-board"
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
  | "knowledge"
  | "competitors"
  | "brand"
  | "metrics"
  | "facts"
  | "members"
  | "plans"
  | "opportunities"
  | "alerts"
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
  | "dash"
  | "health"
  | "traffic"
  | "generation"
  | "encyclopedia"
  | "onboarding"
  | "consumption"
  | "organization"
  | "profile";

export type Tone = "blue" | "green" | "amber" | "red" | "slate";

export interface Project {
  id: string;
  code: string;
  name: string;
  owner: string;
  organizationId?: string;
  organizationName?: string | null;
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
  /** 进入待办的进入时间；仅用于待办排序/筛选，不能回退成 updatedAt。 */
  enteredTodoAt?: string | null;
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
  engine_codes: string[];
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
export interface QuestionCandidateRecord {
  id: string; text: string; bucket: "category" | "purchase" | "reputation";
  question_type: "brand" | "general"; audience: string | null; intent: string | null; priority: number;
  source: "rule" | "import"; source_ref: string | null; rationale: string | null;
  status: "pending" | "accepted" | "rejected";
  converted_question_id: string | null; created_at: string; reviewed_at: string | null;
}
export interface QuestionCandidateMineResult {
  created_count: number; skipped_count: number; counts: Record<string, number>; missing_context: string[];
}
export interface QuestionCandidateImportResult {
  created_count: number; skipped_count: number; counts: Record<string, number>;
}
export interface QuestionCandidateAcceptResult {
  candidate_id: string; question_id: string; question_code: string; version_no: number;
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
export interface SamplingContext {
  device_type?: string | null;
  os?: string | null;
  app_version?: string | null;
  login_state?: string | null;
  personalization?: string | null;
}
export interface SampleRecord {
  id: string; serial_no: number; task_id: string; status: string; attempt_no: number; sampled_at: string | null;
  trace_id?: string | null; latency_ms?: number | null; total_tokens?: number | null; estimated_cost_cny?: number | null;
  raw_answer?: string | null; answer_excerpt?: string | null; brand_mentioned: boolean | null; brand_identified?: boolean | null; failure_code: string | null;
  conversation_id?: string | null; conversation_mode?: string | null;
  sampling_context?: SamplingContext | null;
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
  scheduled_at?: string | null;
  receipt_id?: string | null;
  published_url?: string | null;
  received_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
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
export interface ContentVersionRecord { version_id: string; item_id: string; title: string; version_no: number; status: string; status_label?: string; kind: string; content_type?: string | null; channel_id: string | null; author_name?: string | null; submitted_at?: string | null }
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
  recommendation_known_answers?: number;
  brand_recommended_answers?: number;
  brand_recommendation_rate?: number | null;
  top3_answers?: number;
  top3_rate?: number | null;
  brand_entity_mentions?: number;
  competitor_entity_mentions?: number;
  answer_share?: number | null;
  citation_rate: number | null;
  channel_count: number;
  channel_total: number;
  observed_channel_count: number;
  page_count: number;
  excluded: { failed: number; manual_review: number; no_answer_surface: number; pending_or_running: number };
  failure_breakdown?: Record<string, number>;
  /** M3 三分：cited = 提及且有已复核带 URL 引用；mentioned_only；absent；三档相加 = valid_answers */
  brand_cited_answers?: number;
  brand_cited_rate?: number | null;
  three_state?: { cited: number; mentioned_only: number; absent: number; denominator: number };
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

/** M1 引用源覆盖：Top N 站点里我们占几个；分母固定 Top N，不是全网域名。 */
export interface SourceCoverageDomain {
  domain: string;
  citations: number;
  samples: number;
  competitor_citations: number;
  competitor_names: string[];
  source_category: string;
  owned_by_us: boolean;
  our_publications: number;
  channel_name: string | null;
  tier?: "T0" | "T1" | "T2" | "T3";
  tier_label?: string;
  tier_rule?: string;
  tier_reason?: string;
}

export interface SourceCoverage {
  days: number;
  scope: { valid_samples: number; reviewed_citations: number; reviewed_domains: number; top_n: number };
  coverage: { top_domains: number; owned_domains: number; owned_rate: number | null; covered_domains: number; covered_rate: number | null };
  domains: SourceCoverageDomain[];
  gaps: { domain: string; competitor_citations: number; competitor_names: string[] }[];
  notes: string[];
}
export interface SourceTierRow {
  tier: "T0" | "T1" | "T2" | "T3";
  label: string;
  definition: string;
  domains: number;
  citations: number;
  citation_share: number | null;
}

export interface SourceTierDomain {
  domain: string;
  citations: number;
  samples: number;
  competitor_citations: number;
  source_category: string;
  tier: "T0" | "T1" | "T2" | "T3";
  tier_label: string;
  tier_definition: string;
  tier_rule: string;
  tier_reason: string;
}

export interface SourceTiers {
  days: number;
  scope: { valid_samples: number; reviewed_citations: number; reviewed_domains: number; returned_domains: number };
  tiers: SourceTierRow[];
  domains: SourceTierDomain[];
  cross_validation: {
    brand_cited_answers: number;
    single_source_answers: number;
    multi_source_answers: number;
    tier01_supported_answers: number;
    multi_high_tier_answers: number;
    multi_source_rate: number | null;
    multi_high_tier_rate: number | null;
  };
  rules: { order: number; rule: string; tier: string; note: string }[];
  notes: string[];
}

export interface PageTypeReclassifyResult {
  dry_run: boolean;
  rule_version: string;
  mode: "path" | "content";
  scope: { candidates: number; scanned: number; changed: number; unchanged: number };
  by_target: Record<string, number>;
  by_rule: Record<string, number>;
  examples: { citation_id: string; url: string; domain: string | null; title: string | null; from: string; to: string; rule: string; reason: string }[];
  notes: string[];
}

export interface BrandRelatedPreview {
  apply: boolean;
  scope: { scanned: number; candidates: number; changed: number };
  by_term: Record<string, number>;
  by_domain: Record<string, number>;
  examples: {
    citation_id: string; raw_url: string; domain: string | null; title: string | null;
    page_type: string | null; matched_terms: string[]; reviewed_at: string | null;
  }[];
  notes: string[];
}

export interface SentimentLabelRecord {
  polarity: string; note: string | null; labeled_by: string | null; labeled_at: string | null;
}

export interface SentimentQueueItem {
  citation_id: string; title: string | null; excerpt: string | null; url: string; domain: string | null;
  page_type: string | null; published_at: string | null; labels: SentimentLabelRecord[];
  label_count: number; my_label_count: number; state: string; consensus: string | null;
  labelers: string[]; hints: string[];
}

export interface SentimentSampling {
  round_no: number; size: number; scope: string; widened: boolean; pool: number;
  sample: SentimentQueueItem[]; risk_scan: SentimentQueueItem[]; notes: string[];
}

export interface SourceDomainEntry {
  site: string;
  citations: number;
  pending: number;
  existing_categories: Record<string, number>;
  status: "settled" | "suggested" | "needs_review";
  suggested_category: string | null;
  reason: string;
  written: number;
  evidence: {
    title: string | null;
    description: string | null;
    sample_title: string | null;
    status: string;
    fetched_at: string | null;
  } | null;
}

export interface SourceDomainsOverview {
  apply: boolean;
  scope: {
    citations: number;
    sites: number;
    suggested_sites: number;
    needs_review_sites: number;
    settled_sites: number;
    citations_covered: number;
    changed: number;
  };
  domains: SourceDomainEntry[];
  notes: string[];
}

export interface SentimentConsensus {
  round_no: number; size: number; scope: string; widened: boolean; sampled: number;
  consensus_total: number;
  pending_second?: number; counts: Record<string, number>; disputed: number; unlabeled: number;
  min_report: number; reportable: boolean; positive_rate: number | null;
  disputed_items: SentimentQueueItem[]; notes: string[];
}

export interface ContentFreshness {
  window_months: number;
  cutoff: string;
  generated_at: string;
  summary: {
    total: number; published: number; fresh: number; stale: number; unpublished: number;
    published_unverified: number; stale_rate: number | null; masters: number; channel_copies: number;
  };
  by_channel: {
    channel_id: string | null; channel_name: string; items: number; fresh: number; stale: number;
    unpublished: number; published_unverified: number; stale_rate: number | null; oldest_published_at: string | null;
  }[];
  items: {
    item_id: string; title: string; kind: string; status: "fresh" | "stale" | "unpublished" | "published_unverified";
    channel_id: string | null; channel_name: string; published_at: string | null; age_days: number | null; stale_by_days: number;
  }[];
  notes: string[];
}

export interface ContentConsistencyFactConflict {
  code: "contact_mismatch" | "fee_mismatch" | "address_unverified";
  severity: "high" | "warning";
  item_id: string;
  version_id: string;
  title: string;
  channel_name: string | null;
  fact_key: string | null;
  fact_value: string | null;
  found: string;
  message: string;
  recommended_action: string;
}

export interface ContentConsistencyDerivation {
  id: string;
  master_item_id: string;
  channel_id: string;
  channel_item_id: string;
  channel_item_title: string | null;
  channel_name: string | null;
  master_item_title?: string | null;
  master_version_no?: number | null;
  item_status: string | null;
  version_status: string | null;
  stale: boolean;
  created_at: string | null;
  synced_at: string | null;
}

export interface ContentConsistencyAnomaly {
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
}

export interface ContentConsistencyReport {
  generated_at: string;
  summary: {
    contents_scanned: number;
    approved_facts: number;
    fact_conflicts: number;
    stale_derivations: number;
    channel_anomalies: number;
    channel_anomalies_high: number;
  };
  fact_conflicts: ContentConsistencyFactConflict[];
  stale_derivations: ContentConsistencyDerivation[];
  channel_anomalies: ContentConsistencyAnomaly[];
  notes: string[];
}

export interface ContentFormatRow {
  content_type: string | null;
  label: string;
  master_items: number;
  channel_items: number;
  current_versions: number;
  citation_linked_items: number;
  citation_coverage: number | null;
}

export interface ContentFormatReport {
  summary: {
    master_items: number;
    master_with_format: number;
    master_without_format: number;
    channel_items: number;
    current_versions: number;
    citation_linked_items: number;
    citation_coverage: number | null;
  };
  formats: ContentFormatRow[];
  notes: string[];
}

export interface AdaptationAnswerRow {
  key: string;
  label: string;
  hint: string;
  answer: "yes" | "partial" | "no" | "unknown";
  answer_label: string;
  points: number | null;
}

export interface AdaptationReport {
  evaluated: boolean;
  answers: AdaptationAnswerRow[];
  score: number | null;
  max_score: number;
  evaluated_count: number;
  verdict: "insufficient" | "prioritize" | "pilot" | "defer";
  verdict_label: string;
  reason: string;
  note: string | null;
  evaluated_at: string | null;
  evaluated_by: string | null;
  disclaimer: string;
}

export interface AcceptanceContract {
  window_days: number;
  start_at: string;
  generated_at: string;
  valid_answers: number;
  rates: { mention_rate: number | null; citation_rate: number | null; positive_rate: number | null };
  numerators: { mentioned: number; cited: number; positive: number; labeled: number };
  cited_source_mix: {
    by_category: Record<string, number>;
    total: number;
    low_trust_total: number;
    low_trust_share: number | null;
    low_trust_categories: string[];
    unknown_total: number;
    unknown_share: number | null;
  };
  streak: { days: number; target: number; ok: boolean; last_date: string | null };
  ready: { rates_present: boolean; missing: string[]; streak_ok: boolean; contract_ok: boolean };
  definitions: string[];
  notes: string[];
}

export interface PageTitleBackfillResult {
  dry_run: boolean;
  scope: { candidates: number; titled: number; untitled: number };
  by_status: Record<string, number>;
  examples: { raw_url: string; title: string; snippet: string | null; status: string }[];
  notes: string[];
}

export interface AnswerSnapshotSummary {
  id: string;
  sample_id: string;
  sample_serial_no: number | null;
  question_code: string | null;
  question_title: string | null;
  engine_name: string | null;
  answer_chars: number;
  citation_count: number;
  answer_hash: string;
  content_hash: string;
  captured_at: string | null;
  answer_drift: boolean | null;
}

export interface AnswerSnapshotDetail extends AnswerSnapshotSummary {
  payload: {
    sample: Record<string, unknown>;
    question: Record<string, unknown>;
    engine: Record<string, unknown>;
    answer: { raw_answer: string | null; raw_response: unknown };
    citations: { raw_url: string; domain: string; page_type: string; source_category: string; review_status: string; competitor_id: string | null }[];
  };
}

export interface SourceMatrixForm {
  form: string;
  label: string;
  citations: number;
  citation_share: number | null;
}

export interface SourceMatrixDomain {
  domain: string;
  tier: "T0" | "T1" | "T2" | "T3";
  tier_label: string;
  tier_rule: string;
  citations: number;
  forms: { form: string; label: string; citations: number }[];
  top_form: string | null;
  top_form_label: string | null;
  top_form_share: number | null;
  competitor_citations: number;
  owned_by_us: boolean;
  our_publications: number;
  status: "owned" | "covered" | "gap" | "untouched";
}

export interface SourceMatrix {
  days: number;
  scope: {
    valid_samples: number;
    reviewed_citations: number;
    domains_in_scope: number;
    returned_domains: number;
    tiers: string[];
    invalid_tiers: string[];
  };
  forms: SourceMatrixForm[];
  domains: SourceMatrixDomain[];
  notes: string[];
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
  recommendation_known_answers?: number; brand_recommended_answers?: number;
  brand_recommendation_rate?: number | null; top3_answers?: number; top3_rate?: number | null;
}
export interface StatsEntry extends StatsEngine {
  entry_id: string;
  entry_name: string;
  entry_type: "web_user" | "app_user" | "api" | "app_search";
  entry_label: string;
}
export interface StatsQuestion {
  question_id: string; question_code: string; question_title: string; question_type: string;
  valid_answers: number; brand_mentioned_answers: number; brand_identified_answers: number; citation_answers: number;
  citation_observable_answers: number; citation_unobservable_answers: number;
  brand_mention_rate: number | null; brand_identified_rate: number | null; citation_rate: number | null;
  recommendation_known_answers?: number; brand_recommended_answers?: number;
  brand_recommendation_rate?: number | null; top3_answers?: number; top3_rate?: number | null;
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
  brand_recommendation_rate?: number | null; top3_rate?: number | null;
  brand_entity_mentions?: number; answer_share?: number | null;
  sov_detail?: {
    denominator_samples: number;
    entities: { entity: string; kind: "brand" | "competitor"; mentioned_samples: number; share: number | null }[];
    note: string | null;
  } | null;
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
  by_engine?: LeadFunnelGroup[];
  by_article?: LeadFunnelGroup[];
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
  entry_breakdown?: StatsEntry[] | null;
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
export interface ReportShareRecord {
  share_id: string;
  project_id: string;
  snapshot_id: string;
  month: string | null;
  label: string | null;
  brand_name: string | null;
  brand_logo_url: string | null;
  accent_color: string;
  contact_text: string | null;
  show_leads: boolean;
  password_enabled: boolean;
  expires_at: string;
  revoked_at: string | null;
  view_count: number;
  last_viewed_at: string | null;
  created_at: string;
  status: "active" | "expired" | "revoked";
  share_path: string | null;
}
export interface ReportShareCreateResult {
  share_id: string;
  snapshot_id: string;
  token: string;
  share_path: string;
  expires_at: string;
  password_enabled: boolean;
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
/** 四套对外画像之一：企业 / 招聘 / 会议 / 活动。没配置过也会返回空壳。 */
export interface CompanyProfileViewRecord {
  kind: "company" | "recruit" | "meeting" | "activity";
  title?: string | null;
  audience?: string | null;
  scenario_words: string[];
  description?: string | null;
  cautions?: string | null;
  configured: boolean;
  is_active: boolean;
  updated_at?: string | null;
}

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
  /** 企业 / 招聘 / 会议 / 活动四套对外说法；不并入 completeness。 */
  views?: CompanyProfileViewRecord[];
}

/**
 * 一键填表的建议字段。全部可选：证据里没有的项后端不会给，
 * 前端只把它填进空字段，不动人工已填的内容。
 */
export interface CompanyProfileDraftFields {
  legal_name?: string | null;
  brand_name?: string | null;
  slogan?: string | null;
  province?: string | null;
  business_phone?: string | null;
  service_hotline?: string | null;
  contact_email?: string | null;
  stores?: string[];
  industries?: string[];
  regions?: string[];
  products?: CompanyProduct[];
  description?: string | null;
  founder_intro?: string | null;
  highlights?: string | null;
  pain_points?: string | null;
  story?: string | null;
}

export interface CompanyProfileDraftRecord {
  /** ai = 模型起草；rule = 只把已批准事实搬进表单，必须在界面上区分。 */
  mode: "ai" | "rule";
  model?: string | null;
  fields: CompanyProfileDraftFields;
  /** 每个字段的证据来源，例如「事实库 · 业务电话」「模型起草 · qwen-test」。 */
  basis: Record<string, string>;
  note?: string | null;
  evidence: Record<string, number>;
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
  target_channel_ids: string[];
  channel_names: string[];
  /** 期望被引引擎：结果口径，不参与预检阻断 */
  expected_engines: string[];
  expected_engine_names: string[];
  precheck: { ready: boolean; status: string; checks: DistributionCheckRecord[]; failed: string[] } | null;
  notes: string | null;
  item_count: number;
  /** 确认投喂后实际生成的发布任务数（0 表示还没确认或没有可发内容） */
  task_count: number;
  /** 确认投喂时冻结的准入证据：渠道准入、发布账号、内容版本、预检哈希 */
  approval_snapshot: {
    snapshot_at?: string;
    batch_id?: string;
    task_key?: string;
    precheck_hash?: string | null;
    channels?: { id: string; name: string; approval_status: string; is_active: boolean }[];
    accounts?: { channel_id: string; account_id: string; account_name: string }[];
    versions?: { id: string; status: string; content_hash: string }[];
  } | null;
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

export interface ContentGeoScoreCheck {
  key: string;
  label: string;
  points: number;
  max_points: number;
  ok: boolean;
  detail: string;
}

export interface ContentGeoScoreIssue {
  check_key: string;
  detail: string;
  severity: string;
  paragraph_index: number;
  excerpt: string;
  char_start: number;
  char_end: number;
}

export interface ContentGeoScoreDimension {
  key: string;
  label: string;
  score: number;
  issues: ContentGeoScoreIssue[];
  low: boolean;
  hint: string;
  checks: ContentGeoScoreCheck[];
}

export interface ContentCompletenessQuestion {
  title: string;
  status: "covered" | "keyword_only" | "unanswered";
  intent: string;
  detail: string;
}

export interface ContentCompletenessFact {
  fact_key: string | null;
  fact_type: string | null;
  fact_value: string;
  stale: boolean;
}

export interface ContentGeoCompleteness {
  status: "ok" | "partial" | "missing" | "no_questions";
  questions_total: number;
  questions_answered: number;
  questions: ContentCompletenessQuestion[];
  facts_total: number;
  facts_used: number;
  facts_unused: ContentCompletenessFact[];
  notes: string[];
}

export interface SellingPointCheckRow {
  id: string;
  label: string;
  value_text: string | null;
  required: boolean;
  status: "covered" | "mentioned" | "missing";
  status_label: string;
}

export interface SellingPointCheck {
  status: "ok" | "partial" | "missing" | "no_points";
  status_label: string;
  points_total: number;
  covered: number;
  mentioned: number;
  missing: number;
  required_total: number;
  required_covered: number;
  required_coverage: number | null;
  points: SellingPointCheckRow[];
  notes: string[];
}

export interface SellingPointRecord {
  id: string;
  label: string;
  value_text: string | null;
  aliases: string[];
  required: boolean;
  is_active: boolean;
  note: string | null;
  updated_at: string;
}

export interface SellingPointSummaryRow {
  id: string;
  label: string;
  value_text: string | null;
  required: boolean;
  is_active: boolean;
  content_total: number;
  covered: number;
  mentioned: number;
  missing: number;
  coverage: number | null;
}

export interface SellingPointSummary {
  summary: {
    points_total: number;
    contents_total: number;
    required_points: number;
    required_coverage: number | null;
  };
  points: SellingPointSummaryRow[];
  notes: string[];
}

export interface BrandSearchPoint { date: string; search_volume: number }
export interface BrandSearchPlatform {
  platform: string;
  points: number;
  first_date: string;
  latest_date: string;
  first_volume: number;
  latest_volume: number;
  previous_volume: number | null;
  delta: number | null;
  delta_pct: number | null;
  period_delta: number | null;
  series: BrandSearchPoint[];
}

export interface BrandSearchReport {
  window_days: number;
  start_date: string;
  end_date: string;
  platforms: BrandSearchPlatform[];
  notes: string[];
}

export interface CompetitorSourceDomain {
  domain: string;
  tier: string;
  tier_label: string;
  tier_rule: string;
  source_category: string;
  citations: number;
  samples: number;
}

export interface CompetitorSourceRow {
  id: string;
  name: string;
  citations: number;
  samples: number;
  domain_count: number;
  tier_counts: Record<string, number>;
  tier_shares: Record<string, number>;
  high_quality_citations: number;
  high_quality_share: number;
  top_domains: CompetitorSourceDomain[];
}

export interface CompetitorSourceReport {
  window_days: number;
  start_date: string;
  end_date: string;
  competitors: CompetitorSourceRow[];
  summary: {
    competitors: number;
    citations: number;
    competitors_with_t0_t1: number;
    average_high_quality_share: number | null;
  };
  notes: string[];
}

export interface ContentGeoScoreRecord {
  rule_version: string;
  computed_at: string;
  dimensions: ContentGeoScoreDimension[];
  completeness: ContentGeoCompleteness;
  selling_points: SellingPointCheck;
  attention_count: number;
  paragraph_count: number;
  body_metrics: Record<string, number>;
  disclaimer: string;
  version_id: string;
  item_id: string;
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
  reachable?: boolean | null;
  reachability_status?: number | null;
  reachability_error?: string | null;
  reachability_checked_at?: string | null;
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
    reachability_checked?: number;
    reachable?: number;
    unreachable?: number;
    reachable_rate?: number | null;
  };
  caveats: string[];
}

export interface SentimentSummaryRecord {
  total_reviewed_citations: number;
  labeled: number;
  unlabeled: number;
  pending_second: number;
  disputed: number;
  consensus_total: number;
  counts: { positive: number; neutral: number; negative: number };
  coverage: number | null;
  consensus_coverage: number | null;
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
  state: "unlabeled" | "pending_second" | "disputed" | "positive" | "neutral" | "negative";
  label_count: number;
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
  /** 服务端待办进入时间；mock 也必须提供，不能用展示时间代替。 */
  enteredTodoAt?: string | null;
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

export interface KnowledgeDocumentRecord {
  id: string;
  project_id: string;
  material_id: string;
  material_title: string | null;
  file_name: string | null;
  category: string | null;
  parse_status: "pending" | "parsing" | "ready" | "failed" | "unsupported";
  parser_version: string | null;
  page_count: number | null;
  language: string | null;
  checksum: string | null;
  error: string | null;
  char_count: number;
  chunk_count: number;
  candidate_count: number;
  embedding_status: string;
  search_mode: string;
  parsed_at: string | null;
  created_at: string | null;
}

export interface KnowledgeChunkRecord {
  id: string;
  document_id: string;
  chunk_no: number;
  text: string;
  token_count: number;
  page_from: number | null;
  page_to: number | null;
  section: string | null;
}

export interface KnowledgeCandidateFactRecord {
  id: string;
  document_id: string;
  document_title: string | null;
  chunk_id: string | null;
  claim_text: string;
  subject: string | null;
  predicate: string | null;
  object: string | null;
  evidence_text: string;
  suggested_fact_type: string;
  suggested_fact_key: string;
  confidence: number;
  source_page: number | null;
  status: "suggested" | "accepted" | "rejected";
  fact_id: string | null;
  created_at?: string | null;
  review_note: string | null;
  reviewed_at: string | null;
}

export interface KnowledgeSearchItem {
  chunk_id: string;
  document_id: string;
  document_title: string;
  file_name: string;
  chunk_no: number;
  page_from: number | null;
  page_to: number | null;
  section: string | null;
  text: string;
  score: number;
  similarity: number;
  vector_similarity: number;
  matched_terms: string[];
}

export interface KnowledgeSearchResult {
  query: string;
  search_mode: string;
  embedding_status: string;
  items: KnowledgeSearchItem[];
  total_scanned: number;
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

export interface UserAccountRecord {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
  is_active: boolean;
  is_system_admin: boolean;
  last_login_at: string | null;
  created_at: string;
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

export interface AlertRuleRecord {
  id: string;
  code: string;
  name: string;
  severity: string;
  is_enabled: boolean;
  thresholds: Record<string, number>;
}

export interface AlertEventRecord {
  id: string;
  rule_id: string;
  code: string;
  severity: string;
  status: string;
  title: string;
  message: string;
  metric_value: number | null;
  baseline_value: number | null;
  current_samples: number | null;
  baseline_samples: number | null;
  trigger_count: number;
  dedupe_key: string;
  triggered_at: string | null;
  last_seen_at: string | null;
  acknowledged_at: string | null;
  note: string | null;
  webhook_status: string | null;
  payload: Record<string, unknown>;
}

export interface OpportunitySuggestionRecord {
  id: string;
  rule_code: string;
  title: string;
  description: string | null;
  gap_type: string;
  severity: string;
  score: number;
  question_id: string | null;
  sample_id: string | null;
  source_type: string | null;
  source_id: string | null;
  evidence: Record<string, unknown>;
  status: string;
  accepted_opportunity_id: string | null;
  review_note: string | null;
  generated_at: string | null;
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


export interface DashboardMetric {
  key: string;
  label: string;
  numerator: number;
  denominator: number;
  value: number | null;
  unit: string;
  has_data: boolean;
}

export interface DashboardTrack {
  track: "dispatch" | "measurement";
  label: string;
  window_days: number;
  metrics: DashboardMetric[];
  notes: string[];
}

export interface DashboardTracks {
  days: number;
  disclaimer: string;
  tracks: DashboardTrack[];
}

/** GEO 数据大屏：四个主数 + 榜单 + 趋势 + 平台占比 + 报表明细 + 线索事件。 */
export type GeoBoardKpiKey = "training_words" | "recommended_words" | "indexed_total" | "lead_events";

export interface GeoBoardKpi {
  key: GeoBoardKpiKey;
  label: string;
  unit: string;
  value: number;
  window_value: number;
  window_days: number;
  spark: number[];
  /** demo = 本项目完全无记录时的内置样例，卡片必须标「演示」。 */
  source: "real" | "demo";
  note: string;
}

export interface GeoBoardTopKeyword {
  rank: number;
  keyword_id: string;
  name: string;
  questions: number;
  citations: number;
}

export interface GeoBoardEngineShare {
  engine_id: string;
  engine_name: string;
  value: number;
  share: number | null;
}

export interface GeoBoardReportRow {
  citation_id: string;
  training_word: string;
  /** 最新搜索词场景：该引用所属问题的题干，缺省回退到 answer_entity。 */
  question?: string | null;
  /** 引用来源标题（页面/文章名），没有标题时回退站点名或域名。 */
  source_title?: string | null;
  answer_entity: string;
  platform: string;
  voucher_url: string;
  official_url: string | null;
  reviewed: boolean;
  occurred_at: string | null;
}

export type GeoBoardReportKind = "all" | "search" | "qa" | "intent" | "brand";

/** 采集端：pc = 网页用户端；mobile = 客户端 + 应用内搜索；api = 官方 API；all = 三档合并。 */
export type GeoBoardDevice = "all" | "pc" | "mobile" | "api";

/** 线索事件类型：traffic = 访问事件；lead = 表单线索；all = 合并时间轴。 */
export type GeoBoardLeadKind = "all" | "traffic" | "lead";

export interface GeoBoardReport {
  total: number;
  page: number;
  page_size: number;
  pages: number;
  rows: GeoBoardReportRow[];
  /** 当前报表类型：search = 检索结果类样本，qa = 生成回答类样本，intent = 问题带意图，brand = 命中品牌。 */
  kind: GeoBoardReportKind;
  device: GeoBoardDevice;
  engines: { engine_id: string | null; engine_name: string; value: number }[];
  selected_engine_id: string | null;
}

export interface GeoBoardLeadEvent {
  event: string;
  region: string;
  ip_masked: string;
  source: string;
  url: string | null;
  occurred_at: string | null;
}

export interface GeoBoard {
  project_window: { days: number; start_date: string; end_date: string; timezone: string };
  /** 品牌标识：项目级品牌档案，未配置时回退项目名。 */
  brand: { name: string; configured: boolean; active: boolean };
  kpis: GeoBoardKpi[];
  has_demo: boolean;
  top_keywords: { items: GeoBoardTopKeyword[]; total: number; max: number };
  indexed_series: { source: "real" | "demo"; items: { date: string; value: number }[] };
  engine_share: { items: GeoBoardEngineShare[]; total: number };
  report: GeoBoardReport;
  lead_events: {
    total: number;
    page: number;
    page_size: number;
    pages: number;
    rows: GeoBoardLeadEvent[];
    kind: GeoBoardLeadKind;
    counts: Record<GeoBoardLeadKind, number>;
  };
  notes: string[];
}

export type HealthCheckStatus = "pass" | "fail" | "unknown";

export interface HealthCheckItemRecord {
  check_key: string;
  category: string;
  label: string;
  numerator: number;
  denominator: number;
  unit: string;
  target_percent: number;
  ratio: number | null;
  status: HealthCheckStatus;
  hint: string;
}

export interface HealthCheckTotals {
  total: number;
  passed: number;
  failed: number;
  unknown: number;
}

export interface HealthCheckRun {
  run_id: string;
  ruleset_version: string;
  created_at: string;
  totals: HealthCheckTotals;
  items: HealthCheckItemRecord[];
  disclaimer?: string;
}

export interface HealthCheckRunSummary {
  run_id: string;
  ruleset_version: string;
  created_at: string;
  totals: HealthCheckTotals;
}

export interface TrafficBreakdownRow {
  events: number;
  visitors: number;
}

export interface TrafficRegionRow extends TrafficBreakdownRow {
  region: string;
}

export interface TrafficChannelRow extends TrafficBreakdownRow {
  channel: string;
}

export interface TrafficSummary {
  days: number;
  totals: { pv: number; sessions: number; visitors: number; bot_events: number };
  by_region: TrafficRegionRow[];
  by_channel: TrafficChannelRow[];
  notes: string[];
}

export interface GenerationBrief {
  source: string;
  question: string | null;
  gap_type: string | null;
  opportunity_id: string | null;
  question_id: string | null;
  samples?: number | null;
  mentions?: number | null;
  evidence_refs?: Record<string, unknown>[];
  brand: string | null;
  official_urls: string[];
  facts: { key: string; value: string }[];
  faqs: { question: string; answer: string }[];
  sources: { domain: string; citations: number }[];
  guidance: string;
}

export interface GenerationItemRecord {
  item_id: string;
  title: string;
  status: "pending" | "drafted" | "failed";
  generation_mode: "template" | "model";
  question_id: string | null;
  opportunity_id: string | null;
  brief: GenerationBrief;
  draft_body: string | null;
  failure_reason: string | null;
  reviewed: boolean;
}

export interface GenerationBatchRecord {
  batch_id: string;
  name: string;
  source: "opportunity" | "question";
  status: "queued" | "running" | "completed" | "failed";
  engine_code: string | null;
  note: string | null;
  created_at: string;
  totals: { total: number; drafted: number; failed: number; pending?: number; reviewed?: number };
  items: GenerationItemRecord[];
  disclaimer?: string;
}

export interface GenerationBatchSummary {
  batch_id: string;
  name: string;
  source: "opportunity" | "question";
  status: string;
  engine_code: string | null;
  created_at: string;
  totals: { total: number; drafted: number; failed: number };
}

export interface EncyclopediaReference {
  title: string;
  url: string;
  note?: string | null;
}

export interface EncyclopediaEntryRecord {
  entry_id: string;
  slug: string;
  title: string;
  platform: string;
  platform_label: string;
  summary: string | null;
  body: string;
  references: EncyclopediaReference[];
  status: "draft" | "pending_review" | "published" | "rejected";
  status_label: string;
  version: number;
  review_note: string | null;
  reviewed_at: string | null;
  published_url: string | null;
  published_at: string | null;
  updated_at: string | null;
}



export interface PageVisibilityRow {
  receipt_id: string;
  url: string;
  title: string | null;
  channel: string | null;
  received_at: string | null;
  accessible: "yes" | "no" | "unknown";
  accessible_status: number | null;
  accessible_at: string | null;
  searchable: "yes" | "no" | "unknown";
  searchable_detail: string;
  searchable_query: string | null;
  cited: number;
}

export interface PageVisibilityReport {
  summary: {
    receipts: number;
    accessible: { yes: number; no: number; unknown: number };
    searchable: { yes: number; no: number; unknown: number };
    cited_pages: number;
    cited_total: number;
  };
  pages: PageVisibilityRow[];
  notes: string[];
}

export interface DistributionCandidate {
  channel_id: string;
  channel: string;
  code: string;
  status: string | null;
  approval_status: string | null;
  cited: number;
  receipts: number;
  engines: string[];
}

export interface DistributionCandidates {
  candidates: DistributionCandidate[];
  others: DistributionCandidate[];
  summary: { channels: number; approved: number; with_citations: number; with_receipts: number };
  notes: string[];
}

export interface IndustryRequirement {
  key: string;
  label: string;
  required: boolean;
}

export interface IndustryStatus {
  selected: boolean;
  preset_code: string;
  preset_name: string;
  source: string;
  message: string | null;
  industry_specific: boolean;
  requirements: IndustryRequirement[];
}

export interface IndustryPresetOption {
  code: string;
  name: string;
}

export interface OnboardingQuestionDraft {
  code: string;
  text: string;
  question_type: string;
  audience?: string | null;
  intent?: string | null;
}

export interface OnboardingChannelDraft {
  code: string;
  name: string;
  category: string;
  tier?: string | null;
}

export interface OnboardingPlanDraft {
  round_name: string;
  is_baseline: boolean;
  planned_at: string;
  engines: string[];
  samples_per_cell: number;
  questions: number;
  cells: number;
  status: string;
  note: string;
}

export interface OnboardingPreview {
  brand: { name: string; aliases: string[]; domains: string[]; region: string };
  preset: { code: string; name: string };
  products: string[];
  competitors: { name: string; domain: string | null }[];
  derived: {
    questions: OnboardingQuestionDraft[];
    channels: OnboardingChannelDraft[];
    strategy: Record<string, unknown>;
    plan: OnboardingPlanDraft;
  };
  warnings: string[];
}

export interface OnboardingApplyResult {
  brand: { created: number };
  competitors: { created: number; total: number };
  questions: { created: number; total: number };
  channels: { created: number; total: number };
  strategy: { preset_code: string; version: number };
  plan: Record<string, unknown>;
  round_id: string | null;
  tasks_created: number;
  engines_resolved: number;
  warnings: string[];
}

export interface OrganizationSummary {
  id: string;
  code: string;
  name: string;
  status: string;
  project_count: number;
  member_count: number;
}

export interface OrganizationMember {
  user_id: string;
  username: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  in_project: boolean;
}

export interface OrganizationOverview extends OrganizationSummary {
  max_project_members: number;
  quotas: { projects: number | null; members: number | null };
  alerts: { key: string; level: "warning" | "exceeded"; message: string }[];
  health: "ok" | "warning" | "exceeded";
}

export interface OrganizationOverviewResult {
  organizations: OrganizationOverview[];
  webhook_configured: boolean;
}

export interface OrganizationQuotas {
  projects: number | null;
  members: number | null;
  project_members: number | null;
  /** 消耗额度：只提示不拦截；键为计量项（collection/generation/...） */
  consumption?: Record<string, number> | null;
}

export interface OrganizationAlert {
  key: string;
  used: number;
  limit: number;
  level: "warning" | "exceeded";
  message: string;
}

export interface OrganizationSettings {
  organization_id: string;
  code: string;
  name: string;
  inherit_members: boolean;
  inherit_role: "viewer" | "editor" | "reviewer";
  quotas: OrganizationQuotas;
  strategy: Record<string, unknown>;
  usage: OrganizationQuotas;
  alerts: OrganizationAlert[];
}

export interface OrganizationUsagePoint {
  date: string;
  projects: number;
  members: number;
  source?: "snapshot" | "recalculated";
}

export interface OrganizationUsageTrend {
  days: number;
  series: OrganizationUsagePoint[];
  snapshot_days?: number;
  recalculated_days?: number;
}

/** 消耗计量：单位不同，六项并列，不做合计。 */
export type ConsumptionBasis = "facts" | "events";

export interface ConsumptionDetail {
  key: string;
  label: string;
  quantity: number;
}

export interface ConsumptionQuotaState {
  limit: number;
  used: number;
  level: "warning" | "exceeded";
  message: string;
}

export interface ConsumptionMetricRow {
  metric: string;
  label: string;
  unit: string;
  basis: ConsumptionBasis;
  source: string;
  note: string;
  quantity: number;
  detail?: ConsumptionDetail[];
  quota?: ConsumptionQuotaState;
}

export interface ConsumptionSummary {
  scope: "project" | "organization";
  project_id: string | null;
  organization_id: string | null;
  range: { start: string; end: string };
  metrics: ConsumptionMetricRow[];
  alerts: ({ metric: string } & ConsumptionQuotaState)[];
  note: string;
}

export interface ConsumptionEvent {
  id: string;
  project_id: string;
  metric: string;
  label: string;
  quantity: number;
  unit: string;
  source_type: string;
  source_id: string;
  occurred_on: string;
  meta: Record<string, unknown>;
}

export interface PublishBoardBatchRecord {
  batch_id: string;
  name: string;
  status: string;
  /** 批次确认时记下的任务数；0 = 还没确认投喂 */
  task_count: number;
  item_count: number;
  created_at: string | null;
  dispatched_at: string | null;
  /** 本批次任务的状态分布（pending/published/failed…） */
  task_states: Record<string, number>;
  channels: Record<string, number>;
  tasks_total: number;
  with_receipt: number;
  reachable: number;
  visibility_checked: number;
  visibility_matched: number;
  cited: number;
  /** 这一批卡在哪一段；cited 表示走完全链 */
  stage: "not_dispatched" | "no_receipt" | "no_visibility_check" | "not_cited" | "cited";
  receipt_rate: number | null;
}

export interface PublishBoardBatchesRecord {
  items: PublishBoardBatchRecord[];
  summary: {
    batches: number;
    tasks: number;
    receipts: number;
    cited: number;
    not_dispatched: number;
  };
  caveats: string[];
}

export interface LeadAutoreplyRecord {
  enabled: boolean;
  script: string;
  include_contact: boolean;
  note?: string | null;
  /** 后端按当前配置拼出的实际回显（含联系方式行） */
  preview?: string;
}


/** 事实推送到 EEAT 信源的记录（G9）。sent 只代表送达对方，不代表对方已采用。 */
export interface FactPushRecord {
  id: string;
  fact_id: string;
  target_type: "encyclopedia" | "webhook";
  target_ref: string;
  status: "pending" | "sent" | "failed";
  attempt_count: number;
  external_ref: string | null;
  error: string | null;
  sent_at: string | null;
  created_at: string | null;
  created?: boolean;
}

export type TodoRange = "today" | "week" | "all";

export type TodoTone = "amber" | "red" | "blue";

/** 后端聚合的六类待办分组；计数是全量，items 是有上限的预览。 */
export interface TodoCenterItem {
  key: string;
  group: "采集失败" | "内容审核" | "发布队列" | "事实审批" | "知识解析" | "异常预警";
  title: string;
  meta: string;
  section: string;
  tone: TodoTone;
  badge: string;
  at: string | null;
}

export interface TodoCenterGroup {
  key: "reviews" | "publish" | "collect" | "facts" | "knowledge" | "alerts";
  label: string;
  section: string;
  counts: Record<TodoRange, number>;
  total: number;
  items: TodoCenterItem[];
}

export interface TodoCenter {
  project_id: string;
  range: TodoRange;
  business_timezone: string;
  generated_at: string;
  window: { start: string; end: string } | null;
  counts: Record<TodoRange, number>;
  groups: TodoCenterGroup[];
}

export type GenerationGateAction = "precheck" | "sample-review" | "gate-approval";

/** 批次闸门结论（precheck / sample_review / approval），只决定要不要全量出稿。 */
export interface GenerationGateRecord {
  id: string;
  batch_id: string;
  gate_type: "precheck" | "sample_review" | "approval";
  passed: boolean;
  score: number | null;
  threshold: number | null;
  sample_size: number;
  blockers: { code: string; message: string; item_id?: string }[];
  metrics: Record<string, unknown>;
  note: string | null;
  created_at: string | null;
}

/** 起草模型配置快照：只带「有没有 Key」和来源，后端不回显 Key 本身。 */
export interface CompanyDraftModelRecord {
  configured: boolean;
  /** project = 项目里存的密文；env = 环境变量 DEEPSEEK_API_KEY；none = 都没有。 */
  source: "project" | "env" | "none";
  base_url: string;
  model: string;
  has_secret: boolean;
  is_active: boolean;
  /** 环境变量那把 Key 的指纹（前 6 位 + 后 4 位），用来核对现在生效的是哪把。 */
  env_key_hint?: string | null;
  updated_at?: string | null;
}

export interface CompanyDraftModelTestRecord {
  ok: boolean;
  message: string;
  model?: string | null;
}