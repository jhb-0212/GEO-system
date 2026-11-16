export type Section =
  | "overview"
  | "projects"
  | "monitoring"
  | "diagnostics"
  | "channels"
  | "statistics"
  | "questions"
  | "samples"
  | "publishing"
  | "engines"
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
  status: "进行中" | "待执行" | "已完成" | "需复核" | "失败";
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

export interface ChannelAlias { domain: string; alias_name: string | null }
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
export interface SampleRecord {
  id: string; task_id: string; status: string; attempt_no: number; sampled_at: string | null;
  trace_id?: string | null; latency_ms?: number | null; total_tokens?: number | null; estimated_cost_cny?: number | null;
  raw_answer: string | null; brand_mentioned: boolean | null; failure_code: string | null;
  review_result: string | null; review_note: string | null;
}
export interface DiagnosticSample {
  sample_id: string; task_id: string; trace_id: string | null; sample_status: string; task_status: string;
  attempt_no: number; retry_count: number; sampled_at: string | null; finished_at: string | null;
  failure_code: string | null; failure_note: string | null; latency_ms: number | null;
  total_tokens: number | null; estimated_cost_cny: number | null; gateway_version: string | null;
  engine_code: string | null; engine_name: string | null; question_code: string | null; question_title: string | null;
}
export interface SampleDetail extends SampleRecord {
  citations: { citation_id: string; raw_url: string; domain: string | null; review_status: string }[];
  evidence_files: { evidence_id: string; file_type: string; content_type: string | null; byte_size: number | null; checksum: string | null }[];
}
export interface CitationRecord {
  citation_id: string; sample_id: string; raw_url: string; domain: string | null;
  review_status: string; review_note: string | null; channel_id: string | null; competitor_id: string | null;
  is_brand_related: boolean;
}
export interface UnknownDomainRecord {
  channel_id: string; code: string; name: string; primary_domain: string | null;
  citation_count: number; sample_count: number; last_sampled_at: string | null;
}
export interface PublishTaskRecord { id: string; status: string; channel_id: string; version_id: string; trace_id?: string | null }
export interface PublishAccountRecord { id: string; account_name: string; channel_id: string; is_active: boolean }
export interface ContentVersionRecord { version_id: string; item_id: string; title: string; version_no: number; status: string; kind: string; channel_id: string | null; author_name?: string | null; submitted_at?: string | null }
export interface ContentVersionDetail extends ContentVersionRecord { kind: string; channel_id: string | null; body: string; content_hash: string; change_note: string | null }
export interface ContentReviewRecord { id: string; decision: string; reviewer_name: string | null; comment: string | null; created_at: string }
export interface ChannelRecord {
  id: string;
  code: string;
  name: string;
  category: string;
  status: string;
  primary_domain: string | null;
  notes?: string | null;
  is_active?: boolean;
  aliases?: ChannelAlias[];
}
export interface ChannelDetailRecord extends ChannelRecord {
  notes: string | null;
  is_active: boolean;
  aliases: ChannelAlias[];
  citation_count: number;
  sample_count: number;
  page_count: number;
  page_urls: string[];
  engine_codes: string[];
  question_codes: string[];
  first_sampled_at: string | null;
  last_sampled_at: string | null;
  citations: { citation_id: string; engine_name: string; question_code: string; raw_url: string; review_status: string; sampled_at: string | null }[];
}
export interface EngineRecord { id: string; code: string; name: string; vendor: string; is_active: boolean }
export interface EngineEntryRecord {
  id: string; engine_id: string; entry_type: string; name: string; entry_url: string | null;
  protocol: string; model_name: string | null; credential_ref: string | null;
  credential_configured: boolean; supports_search: boolean; access_note: string | null;
  last_verified_at: string | null; is_active: boolean;
}
export interface EngineConnectionResult {
  success: boolean; protocol: string; endpoint: string | null; model_name: string | null;
  latency_ms: number | null; error_code: string | null; message: string; checked_at: string;
}

export interface StatsOverview {
  valid_answers: number;
  brand_mentioned_answers: number;
  citation_answers: number;
  brand_mention_rate: number | null;
  citation_rate: number | null;
  channel_count: number;
  page_count: number;
  excluded: { failed: number; manual_review: number; pending_or_running: number };
}
export interface StatsEngine {
  engine_id: string; engine_code: string; engine_name: string;
  valid_answers: number; brand_mentioned_answers: number; citation_answers: number;
  brand_mention_rate: number | null; citation_rate: number | null;
}
export interface StatsQuestion {
  question_id: string; question_code: string; question_title: string; question_type: string;
  valid_answers: number; brand_mentioned_answers: number; citation_answers: number;
  brand_mention_rate: number | null; citation_rate: number | null;
}

export interface BatchGenerationResult {
  round_id: string;
  requested_question_count: number;
  eligible_question_count: number;
  inactive_question_count: number;
  inactive_question_ids: string[];
  inactive_questions: { id: string; code: string; title: string; status: string }[];
  question_version_missing_count: number;
  question_version_missing_question_ids: string[];
  engine_count: number;
  expected_task_count: number;
  eligible_expected_task_count: number;
  created_task_count: number;
  reused_task_count: number;
  generated_task_count: number;
  complete: boolean;
  skipped_reason: "question_version_missing" | "engine_entries_insufficient" | "inactive_questions" | null;
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
  status: "待跟进" | "跟进中" | "已转化" | "已流失";
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
  userName?: string;
  isSystemAdmin?: boolean;
  permissions?: string[];
  brandMentionRate?: number | null;
  leadAccess: "allowed" | "forbidden" | "unavailable";
  projects: Project[];
  tasks: MonitoringTask[];
  reviews: ReviewItem[];
  leads: Lead[];
  activities: Activity[];
  trend: (number | null)[];
  engines: { name: string; share: number; color: string }[];
}

export interface ApiEnvelope<T> {
  data: T;
  meta?: { page: number; page_size: number; total: number };
}

export interface ApiErrorEnvelope {
  error: { code: string; message: string };
}
