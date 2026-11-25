CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE TABLE public.ai_engine_entries (
    engine_id uuid NOT NULL,
    entry_type character varying(32) NOT NULL,
    name character varying(64) NOT NULL,
    entry_url text,
    supports_search boolean NOT NULL,
    access_note text,
    last_verified_at timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    protocol character varying(32) DEFAULT 'custom'::character varying NOT NULL,
    model_name character varying(128),
    credential_ref character varying(64),
    encrypted_secret text,
    encrypted_secret_secondary text,
    credential_updated_at timestamp with time zone,
    CONSTRAINT ck_ai_engine_entries_engine_entry_type CHECK (((entry_type)::text = ANY ((ARRAY['web_user'::character varying, 'app_user'::character varying, 'api'::character varying, 'app_search'::character varying])::text[]))),
    CONSTRAINT ck_ai_engine_entries_engine_protocol CHECK (((protocol)::text = ANY ((ARRAY['openai_compatible'::character varying, 'yuanbao_search'::character varying, 'deepseek_web_search'::character varying, 'doubao_search'::character varying, 'wenxin_search'::character varying, 'custom'::character varying])::text[])))
);
CREATE TABLE public.ai_engines (
    code character varying(32) NOT NULL,
    name character varying(64) NOT NULL,
    vendor character varying(64) NOT NULL,
    supports_search boolean NOT NULL,
    supports_citation boolean NOT NULL,
    access_note text,
    last_verified_at timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);
CREATE TABLE public.alert_events (
    project_id uuid NOT NULL,
    rule_id uuid NOT NULL,
    code character varying(32) NOT NULL,
    severity character varying(32) NOT NULL,
    status character varying(32) DEFAULT 'open'::character varying NOT NULL,
    dedupe_key character varying(80) NOT NULL,
    title character varying(200) NOT NULL,
    message text NOT NULL,
    metric_value numeric(12,6),
    baseline_value numeric(12,6),
    current_samples integer,
    baseline_samples integer,
    trigger_count integer DEFAULT 1 NOT NULL,
    triggered_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    acknowledged_by uuid,
    acknowledged_at timestamp with time zone,
    note text,
    webhook_status character varying(32),
    webhook_sent_at timestamp with time zone,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_alert_events_alert_event_code CHECK (((code)::text = ANY ((ARRAY['mention_rate_drop'::character varying, 'recommendation_rate_drop'::character varying, 'competitor_outrank'::character varying, 'negative_share_rise'::character varying, 'collection_failure_rate'::character varying])::text[]))),
    CONSTRAINT ck_alert_events_alert_event_severity CHECK (((severity)::text = ANY ((ARRAY['info'::character varying, 'warning'::character varying, 'critical'::character varying])::text[]))),
    CONSTRAINT ck_alert_events_alert_event_status CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'acknowledged'::character varying, 'resolved'::character varying])::text[])))
);
CREATE TABLE public.alert_rules (
    project_id uuid NOT NULL,
    code character varying(32) NOT NULL,
    name character varying(128) NOT NULL,
    severity character varying(32) DEFAULT 'warning'::character varying NOT NULL,
    is_enabled boolean DEFAULT true NOT NULL,
    thresholds jsonb DEFAULT '{}'::jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_alert_rules_alert_rule_code CHECK (((code)::text = ANY ((ARRAY['mention_rate_drop'::character varying, 'recommendation_rate_drop'::character varying, 'competitor_outrank'::character varying, 'negative_share_rise'::character varying, 'collection_failure_rate'::character varying])::text[]))),
    CONSTRAINT ck_alert_rules_alert_severity CHECK (((severity)::text = ANY ((ARRAY['info'::character varying, 'warning'::character varying, 'critical'::character varying])::text[])))
);
CREATE TABLE public.answer_fact_claims (
    project_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    citation_id uuid,
    claim_text text NOT NULL,
    fact_id uuid,
    verdict character varying(32),
    source_url character varying(1024),
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    correction_task_id uuid,
    created_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    serial_no integer NOT NULL,
    CONSTRAINT ck_answer_fact_claims_fact_claim_verdict CHECK (((verdict)::text = ANY ((ARRAY['correct'::character varying, 'wrong'::character varying, 'expired'::character varying, 'unconfirmed'::character varying])::text[])))
);
CREATE SEQUENCE public.answer_fact_claims_serial_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.answer_fact_claims_serial_no_seq OWNED BY public.answer_fact_claims.serial_no;
CREATE TABLE public.answer_snapshots (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    content_hash character varying(64) NOT NULL,
    answer_hash character varying(64) NOT NULL,
    payload jsonb NOT NULL,
    captured_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.api_keys (
    project_id uuid NOT NULL,
    name character varying(128) NOT NULL,
    key_prefix character varying(16) NOT NULL,
    key_hash character varying(64) NOT NULL,
    scopes jsonb DEFAULT '[]'::jsonb NOT NULL,
    rate_limit_per_minute integer DEFAULT 60 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    expires_at timestamp with time zone,
    last_used_at timestamp with time zone,
    revoked_at timestamp with time zone,
    created_by uuid,
    meta jsonb DEFAULT '{}'::jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.audit_logs (
    project_id uuid,
    actor_id uuid,
    action character varying(64) NOT NULL,
    target_type character varying(64),
    target_id uuid,
    payload jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    id uuid NOT NULL,
    serial_no integer NOT NULL
);
CREATE SEQUENCE public.audit_logs_serial_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.audit_logs_serial_no_seq OWNED BY public.audit_logs.serial_no;
CREATE TABLE public.brand_profiles (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    canonical_name character varying(255) NOT NULL,
    aliases jsonb,
    identifiers jsonb,
    owned_domains jsonb,
    notes text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.brand_search_snapshots (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    platform character varying(32) NOT NULL,
    snapshot_date date NOT NULL,
    search_volume integer NOT NULL,
    source character varying(32) NOT NULL,
    note text,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.budget_approvals (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    category character varying(32) NOT NULL,
    title character varying(255) NOT NULL,
    quantity numeric(12,2),
    unit character varying(32),
    unit_price numeric(12,2),
    amount numeric(14,2) NOT NULL,
    currency character varying(8) DEFAULT 'CNY'::character varying NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    requested_by uuid,
    approved_by uuid,
    approved_at timestamp with time zone,
    note text,
    decision_note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    media_quote_id uuid,
    CONSTRAINT ck_budget_approvals_amount_positive CHECK ((amount > (0)::numeric)),
    CONSTRAINT ck_budget_approvals_budget_approval_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying])::text[]))),
    CONSTRAINT ck_budget_approvals_budget_category CHECK (((category)::text = ANY ((ARRAY['development_hours'::character varying, 'content_production'::character varying, 'media_placement'::character varying, 'monitoring_service'::character varying])::text[]))),
    CONSTRAINT ck_budget_approvals_quantity_positive CHECK (((quantity IS NULL) OR (quantity > (0)::numeric))),
    CONSTRAINT ck_budget_approvals_unit_price_nonnegative CHECK (((unit_price IS NULL) OR (unit_price >= (0)::numeric)))
);
CREATE TABLE public.certifications (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    category character varying(64),
    issuer character varying(255),
    cert_no character varying(128),
    issued_on date,
    expires_on date,
    evidence_url character varying(512),
    notes text,
    is_active boolean DEFAULT true NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.channel_aliases (
    project_id uuid NOT NULL,
    channel_id uuid NOT NULL,
    domain character varying(255),
    alias_name character varying(128),
    notes text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.channel_approvals (
    project_id uuid NOT NULL,
    channel_id uuid NOT NULL,
    submitted_by uuid,
    submitted_at timestamp with time zone,
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    decision character varying(32),
    comment text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_channel_approvals_ck_channel_approvals_decision CHECK (((decision IS NULL) OR ((decision)::text = ANY ((ARRAY['approved'::character varying, 'rejected'::character varying])::text[]))))
);
CREATE TABLE public.channels (
    project_id uuid NOT NULL,
    code character varying(64) NOT NULL,
    name character varying(128) NOT NULL,
    category character varying(32) NOT NULL,
    status character varying(32) DEFAULT 'candidate'::character varying NOT NULL,
    primary_domain character varying(255),
    notes text,
    is_active boolean DEFAULT true NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    import_batch_id uuid,
    publish_url character varying(512),
    login_url character varying(512),
    owner_name character varying(128),
    owner_contact character varying(255),
    approval_status character varying(32) DEFAULT 'pending_review'::character varying NOT NULL,
    submitted_by uuid,
    submitted_at timestamp with time zone,
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    decision_comment text,
    CONSTRAINT ck_channels_channel_category CHECK (((category)::text = ANY ((ARRAY['own_site'::character varying, 'content_platform'::character varying, 'video'::character varying, 'community'::character varying, 'encyclopedia'::character varying, 'local_media'::character varying, 'industry_media'::character varying, 'institution'::character varying])::text[]))),
    CONSTRAINT ck_channels_channel_status CHECK (((status)::text = ANY ((ARRAY['candidate'::character varying, 'published'::character varying, 'observed'::character varying, 'review_pending'::character varying])::text[]))),
    CONSTRAINT ck_channels_ck_channels_approval_status CHECK (((approval_status)::text = ANY ((ARRAY['pending_review'::character varying, 'approved'::character varying, 'rejected'::character varying])::text[])))
);
CREATE TABLE public.citation_source_reviews (
    project_id uuid NOT NULL,
    domain character varying(255) NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    source_category character varying(32),
    suggested_source_category character varying(32),
    classification_source character varying(32),
    classification_rule_version character varying(32),
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    review_note text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_citation_source_reviews_source_review_category CHECK (((source_category)::text = ANY ((ARRAY['brand_owned'::character varying, 'competitor_owned'::character varying, 'social_community'::character varying, 'content_platform'::character varying, 'news_media'::character varying, 'industry_media'::character varying, 'government_institution'::character varying, 'education_institution'::character varying, 'reference'::character varying, 'ecommerce'::character varying, 'other'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT ck_citation_source_reviews_source_review_classification_source CHECK (((classification_source)::text = ANY ((ARRAY['rule'::character varying, 'manual'::character varying])::text[]))),
    CONSTRAINT ck_citation_source_reviews_source_review_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'classified'::character varying, 'ignored'::character varying])::text[]))),
    CONSTRAINT ck_citation_source_reviews_source_review_suggested_category CHECK (((suggested_source_category)::text = ANY ((ARRAY['brand_owned'::character varying, 'competitor_owned'::character varying, 'social_community'::character varying, 'content_platform'::character varying, 'news_media'::character varying, 'industry_media'::character varying, 'government_institution'::character varying, 'education_institution'::character varying, 'reference'::character varying, 'ecommerce'::character varying, 'other'::character varying, 'unknown'::character varying])::text[])))
);
CREATE TABLE public.company_profiles (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    legal_name character varying(255) NOT NULL,
    brand_name character varying(255),
    slogan character varying(255),
    province character varying(64),
    headcount integer,
    founded_on date,
    business_phone character varying(64),
    service_hotline character varying(64),
    contact_email character varying(255),
    stores jsonb,
    official_urls jsonb,
    industries jsonb,
    regions jsonb,
    products jsonb,
    description text,
    highlights text,
    pain_points text,
    story text,
    founder_intro text,
    extra text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.competitors (
    project_id uuid NOT NULL,
    name character varying(128) NOT NULL,
    domain character varying(255),
    is_active boolean DEFAULT true NOT NULL,
    notes text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.content_derivations (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    master_item_id uuid NOT NULL,
    channel_item_id uuid NOT NULL,
    channel_id uuid NOT NULL,
    source_version_id uuid NOT NULL,
    source_content_hash character varying(64) NOT NULL,
    checks jsonb DEFAULT '[]'::jsonb NOT NULL,
    synced_at character varying(32),
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.content_items (
    project_id uuid NOT NULL,
    parent_id uuid,
    channel_id uuid,
    kind character varying(32) NOT NULL,
    title character varying(255) NOT NULL,
    status character varying(32) DEFAULT 'draft'::character varying NOT NULL,
    current_version_id uuid,
    created_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    import_batch_id uuid,
    content_type character varying(32),
    CONSTRAINT ck_content_items_content_kind CHECK (((kind)::text = ANY ((ARRAY['master'::character varying, 'channel'::character varying])::text[]))),
    CONSTRAINT ck_content_items_content_links CHECK (((((kind)::text = 'master'::text) AND (parent_id IS NULL) AND (channel_id IS NULL)) OR (((kind)::text = 'channel'::text) AND (((status)::text = 'archived'::text) OR ((parent_id IS NOT NULL) AND (channel_id IS NOT NULL)))))),
    CONSTRAINT ck_content_items_content_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'pending_review'::character varying, 'approved'::character varying, 'rejected'::character varying, 'pending_publish'::character varying, 'published'::character varying, 'needs_attention'::character varying, 'archived'::character varying])::text[])))
);
CREATE TABLE public.content_plans (
    project_id uuid NOT NULL,
    title character varying(255) NOT NULL,
    plan_type character varying(32) NOT NULL,
    channel_id uuid,
    content_item_id uuid,
    site_page_id uuid,
    owner_id uuid,
    scheduled_at timestamp with time zone,
    status character varying(32) DEFAULT 'proposed'::character varying NOT NULL,
    notes text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_published boolean DEFAULT false NOT NULL,
    publish_url character varying(500),
    published_at timestamp with time zone,
    play_note text,
    CONSTRAINT ck_content_plans_content_plan_status CHECK (((status)::text = ANY ((ARRAY['proposed'::character varying, 'scheduled'::character varying, 'in_production'::character varying, 'pending_review'::character varying, 'published'::character varying, 'cancelled'::character varying])::text[]))),
    CONSTRAINT ck_content_plans_plan_type CHECK (((plan_type)::text = ANY ((ARRAY['article'::character varying, 'video'::character varying])::text[])))
);
CREATE TABLE public.content_reviews (
    project_id uuid NOT NULL,
    version_id uuid NOT NULL,
    reviewer_id uuid NOT NULL,
    decision character varying(32) NOT NULL,
    comment text,
    content_hash_snapshot character varying(64) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_content_reviews_review_decision CHECK (((decision)::text = ANY ((ARRAY['approved'::character varying, 'rejected'::character varying])::text[])))
);
CREATE TABLE public.content_templates (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    name character varying(120) NOT NULL,
    channel_category character varying(32),
    question_type character varying(16),
    skeleton text NOT NULL,
    slots jsonb DEFAULT '[]'::jsonb NOT NULL,
    notes text,
    is_active boolean DEFAULT true NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.content_version_citations (
    project_id uuid NOT NULL,
    version_id uuid NOT NULL,
    citation_id uuid NOT NULL,
    id uuid NOT NULL
);
CREATE TABLE public.content_version_facts (
    project_id uuid NOT NULL,
    version_id uuid NOT NULL,
    fact_id uuid NOT NULL,
    fact_version_no integer NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.content_version_keywords (
    project_id uuid NOT NULL,
    version_id uuid NOT NULL,
    keyword_id uuid NOT NULL,
    id uuid NOT NULL
);
CREATE TABLE public.content_version_questions (
    project_id uuid NOT NULL,
    version_id uuid NOT NULL,
    question_id uuid NOT NULL,
    id uuid NOT NULL
);
CREATE TABLE public.content_versions (
    project_id uuid NOT NULL,
    item_id uuid NOT NULL,
    version_no integer NOT NULL,
    body text NOT NULL,
    content_hash character varying(64) NOT NULL,
    change_note text,
    status character varying(32) DEFAULT 'draft'::character varying NOT NULL,
    created_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    import_batch_id uuid,
    submitted_by uuid,
    submitted_at timestamp with time zone,
    CONSTRAINT ck_content_versions_content_version_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'pending_review'::character varying, 'approved'::character varying, 'rejected'::character varying, 'pending_publish'::character varying, 'published'::character varying, 'needs_attention'::character varying, 'archived'::character varying])::text[])))
);
CREATE TABLE public.correction_tasks (
    project_id uuid NOT NULL,
    claim_id uuid,
    fact_id uuid,
    title character varying(255) NOT NULL,
    description text,
    source_url character varying(1024),
    status character varying(32) DEFAULT 'open'::character varying NOT NULL,
    priority integer DEFAULT 1 NOT NULL,
    created_by uuid,
    resolved_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_correction_tasks_correction_task_status CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'in_progress'::character varying, 'resolved'::character varying, 'dismissed'::character varying])::text[])))
);
CREATE TABLE public.crawler_events (
    project_id uuid NOT NULL,
    public_page_id uuid,
    page_url text NOT NULL,
    ua_claimed character varying(512),
    source_ip character varying(64),
    verified_bot boolean DEFAULT false NOT NULL,
    http_status integer,
    bytes bigint,
    occurred_at timestamp with time zone NOT NULL,
    import_source character varying(64),
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.distribution_batch_items (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    batch_id uuid NOT NULL,
    content_version_id uuid NOT NULL,
    title character varying(255) NOT NULL
);
CREATE TABLE public.distribution_batches (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    name character varying(120) NOT NULL,
    status character varying(32) DEFAULT 'blocked'::character varying NOT NULL,
    precheck jsonb,
    notes text,
    item_count integer DEFAULT 0 NOT NULL,
    last_checked_at timestamp with time zone,
    dispatched_at timestamp with time zone,
    dispatched_by uuid,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    target_channel_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    expected_engines jsonb DEFAULT '[]'::jsonb NOT NULL,
    approval_snapshot jsonb,
    task_count integer DEFAULT 0 NOT NULL,
    CONSTRAINT ck_distribution_batches_distribution_batch_status CHECK (((status)::text = ANY ((ARRAY['blocked'::character varying, 'ready'::character varying, 'dispatched'::character varying])::text[])))
);
CREATE TABLE public.distribution_pushes (
    project_id uuid NOT NULL,
    fact_id uuid NOT NULL,
    target_type character varying(32) NOT NULL,
    target_ref character varying(1024) DEFAULT ''::character varying NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    idempotency_key character varying(64) NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    external_ref character varying(255),
    error text,
    response_payload jsonb,
    sent_at timestamp with time zone,
    last_attempt_at timestamp with time zone,
    created_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_distribution_pushes_push_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'sent'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT ck_distribution_pushes_push_target_type CHECK (((target_type)::text = ANY ((ARRAY['encyclopedia'::character varying, 'webhook'::character varying])::text[])))
);
CREATE TABLE public.encyclopedia_entries (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    slug character varying(128) NOT NULL,
    title character varying(255) NOT NULL,
    platform character varying(32) NOT NULL,
    summary text,
    body text NOT NULL,
    "references" jsonb DEFAULT '[]'::jsonb NOT NULL,
    status character varying(32) DEFAULT 'draft'::character varying NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    reviewer_id uuid,
    review_note text,
    reviewed_at timestamp with time zone,
    published_url text,
    published_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_encyclopedia_entries_ck_encyclopedia_entries_platform CHECK (((platform)::text = ANY ((ARRAY['baidu_baike'::character varying, 'sogou_baike'::character varying, 'douyin_baike'::character varying, 'wikipedia'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT ck_encyclopedia_entries_encyclopedia_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'pending_review'::character varying, 'published'::character varying, 'rejected'::character varying])::text[])))
);
CREATE TABLE public.engine_targets (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    channel_id uuid NOT NULL,
    content_plan_id uuid,
    engine_id uuid NOT NULL,
    priority integer DEFAULT 1 NOT NULL,
    note text,
    source character varying(20) DEFAULT 'manual'::character varying NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.evidence_files (
    project_id uuid NOT NULL,
    sample_id uuid,
    storage_key text NOT NULL,
    file_type character varying(32) NOT NULL,
    checksum character varying(128),
    byte_size bigint,
    content_type character varying(128),
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_evidence_files_evidence_file_type CHECK (((file_type)::text = ANY ((ARRAY['screenshot'::character varying, 'attachment'::character varying, 'pdf'::character varying, 'other'::character varying])::text[])))
);
CREATE TABLE public.fact_versions (
    project_id uuid NOT NULL,
    fact_id uuid NOT NULL,
    version_no integer NOT NULL,
    action character varying(32) NOT NULL,
    snapshot jsonb NOT NULL,
    previous_snapshot jsonb,
    change_note text,
    actor_id uuid,
    created_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    CONSTRAINT ck_fact_versions_fact_version_action CHECK (((action)::text = ANY ((ARRAY['created'::character varying, 'revised'::character varying, 'submitted'::character varying, 'approved'::character varying, 'rejected'::character varying, 'expired'::character varying])::text[])))
);
CREATE TABLE public.facts (
    project_id uuid NOT NULL,
    fact_type character varying(32) NOT NULL,
    fact_key character varying(128) NOT NULL,
    fact_value text NOT NULL,
    source_document text,
    source_url character varying(1024),
    owner character varying(128),
    approval_status character varying(32) DEFAULT 'draft'::character varying NOT NULL,
    effective_from timestamp with time zone,
    effective_until timestamp with time zone,
    version_no integer DEFAULT 1 NOT NULL,
    superseded_by uuid,
    business_confirmed boolean DEFAULT false NOT NULL,
    business_confirmed_note text,
    created_by uuid,
    approved_by uuid,
    approved_at timestamp with time zone,
    rejection_note text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_facts_fact_status CHECK (((approval_status)::text = ANY ((ARRAY['draft'::character varying, 'pending_review'::character varying, 'approved'::character varying, 'expired'::character varying])::text[]))),
    CONSTRAINT ck_facts_fact_type CHECK (((fact_type)::text = ANY ((ARRAY['organization'::character varying, 'base_address'::character varying, 'contact'::character varying, 'course_name'::character varying, 'course_content'::character varying, 'course_duration'::character varying, 'course_fee'::character varying, 'faculty'::character varying, 'training_result'::character varying, 'employment_service'::character varying, 'partner'::character varying, 'certification'::character varying])::text[])))
);
CREATE TABLE public.faqs (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    question character varying(255) NOT NULL,
    answer text NOT NULL,
    status character varying(32) DEFAULT 'draft'::character varying NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    category character varying(64),
    deleted_at timestamp with time zone,
    deleted_by uuid,
    review_comment text,
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    CONSTRAINT ck_faqs_faq_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'pending_review'::character varying, 'rejected'::character varying, 'published'::character varying, 'unpublished'::character varying])::text[])))
);
CREATE TABLE public.generation_batches (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    name character varying(120) NOT NULL,
    source character varying(16) NOT NULL,
    status character varying(32) DEFAULT 'queued'::character varying NOT NULL,
    engine_code character varying(64),
    total_items integer DEFAULT 0 NOT NULL,
    drafted_items integer DEFAULT 0 NOT NULL,
    failed_items integer DEFAULT 0 NOT NULL,
    note text,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_generation_batches_ck_generation_batches_source CHECK (((source)::text = ANY ((ARRAY['opportunity'::character varying, 'question'::character varying, 'remediation'::character varying])::text[]))),
    CONSTRAINT ck_generation_batches_generation_batch_status CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying])::text[])))
);
CREATE TABLE public.generation_gate_results (
    project_id uuid NOT NULL,
    batch_id uuid NOT NULL,
    gate_type character varying(32) NOT NULL,
    passed boolean DEFAULT false NOT NULL,
    score integer,
    threshold integer,
    sample_size integer DEFAULT 0 NOT NULL,
    blockers jsonb DEFAULT '[]'::jsonb NOT NULL,
    metrics jsonb DEFAULT '{}'::jsonb NOT NULL,
    note text,
    created_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_generation_gate_results_gate_type CHECK (((gate_type)::text = ANY ((ARRAY['precheck'::character varying, 'sample_review'::character varying, 'approval'::character varying])::text[])))
);
CREATE TABLE public.generation_items (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    batch_id uuid NOT NULL,
    question_id uuid,
    opportunity_id uuid,
    title character varying(255) NOT NULL,
    brief jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    generation_mode character varying(32) DEFAULT 'template'::character varying NOT NULL,
    draft_body text,
    failure_reason text,
    sort_order integer DEFAULT 0 NOT NULL,
    reviewed boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_generation_items_generation_item_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'drafted'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT ck_generation_items_generation_mode CHECK (((generation_mode)::text = ANY ((ARRAY['template'::character varying, 'model'::character varying])::text[])))
);
CREATE TABLE public.health_check_items (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    run_id uuid NOT NULL,
    check_key character varying(64) NOT NULL,
    category character varying(32) NOT NULL,
    label character varying(120) NOT NULL,
    numerator integer DEFAULT 0 NOT NULL,
    denominator integer DEFAULT 0 NOT NULL,
    unit character varying(8) DEFAULT '条'::character varying NOT NULL,
    target_percent integer DEFAULT 100 NOT NULL,
    status character varying(32) NOT NULL,
    hint text NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_health_check_items_health_check_status CHECK (((status)::text = ANY ((ARRAY['pass'::character varying, 'fail'::character varying, 'unknown'::character varying])::text[])))
);
CREATE TABLE public.health_check_runs (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    ruleset_version character varying(16) NOT NULL,
    total_items integer DEFAULT 0 NOT NULL,
    passed_items integer DEFAULT 0 NOT NULL,
    failed_items integer DEFAULT 0 NOT NULL,
    unknown_items integer DEFAULT 0 NOT NULL,
    triggered_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.import_batches (
    project_id uuid NOT NULL,
    source_system character varying(64) NOT NULL,
    mapping_version character varying(32) NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    counts jsonb,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    rollback_note text,
    created_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_import_batches_import_batch_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying, 'rolled_back'::character varying])::text[])))
);
CREATE TABLE public.industry_presets (
    id uuid NOT NULL,
    code character varying(64) NOT NULL,
    name character varying(64) NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.keywords (
    project_id uuid NOT NULL,
    name character varying(128) NOT NULL,
    category character varying(64),
    priority integer NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    notes text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.knowledge_candidate_facts (
    project_id uuid NOT NULL,
    document_id uuid NOT NULL,
    chunk_id uuid,
    claim_text text NOT NULL,
    subject character varying(255),
    predicate character varying(128),
    object text,
    evidence_text text NOT NULL,
    suggested_fact_type character varying(32) NOT NULL,
    suggested_fact_key character varying(128) NOT NULL,
    confidence double precision DEFAULT '0.5'::double precision NOT NULL,
    source_page integer,
    fingerprint character varying(64) NOT NULL,
    status character varying(32) DEFAULT 'suggested'::character varying NOT NULL,
    fact_id uuid,
    review_note text,
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_knowledge_candidate_facts_fact_type CHECK (((suggested_fact_type)::text = ANY ((ARRAY['organization'::character varying, 'base_address'::character varying, 'contact'::character varying, 'course_name'::character varying, 'course_content'::character varying, 'course_duration'::character varying, 'course_fee'::character varying, 'faculty'::character varying, 'training_result'::character varying, 'employment_service'::character varying, 'partner'::character varying, 'certification'::character varying])::text[]))),
    CONSTRAINT ck_knowledge_candidate_facts_knowledge_candidate_status CHECK (((status)::text = ANY ((ARRAY['suggested'::character varying, 'accepted'::character varying, 'rejected'::character varying])::text[])))
);
CREATE TABLE public.knowledge_chunks (
    project_id uuid NOT NULL,
    document_id uuid NOT NULL,
    chunk_no integer NOT NULL,
    text text NOT NULL,
    token_count integer DEFAULT 0 NOT NULL,
    page_from integer,
    page_to integer,
    section character varying(255),
    embedding jsonb,
    embedding_vec public.vector(1024),
    embedding_model character varying(64),
    metadata jsonb,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.knowledge_documents (
    project_id uuid NOT NULL,
    material_id uuid NOT NULL,
    parse_status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    parser_version character varying(64),
    page_count integer,
    language character varying(16),
    checksum character varying(64),
    error text,
    char_count integer DEFAULT 0 NOT NULL,
    chunk_count integer DEFAULT 0 NOT NULL,
    candidate_count integer DEFAULT 0 NOT NULL,
    metadata jsonb,
    parsed_at timestamp with time zone,
    created_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_knowledge_documents_knowledge_parse_status CHECK (((parse_status)::text = ANY ((ARRAY['pending'::character varying, 'parsing'::character varying, 'ready'::character varying, 'failed'::character varying, 'unsupported'::character varying])::text[])))
);
CREATE TABLE public.lead_attributions (
    project_id uuid NOT NULL,
    lead_id uuid NOT NULL,
    sample_id uuid,
    question_id uuid,
    engine_id uuid,
    channel_id uuid,
    content_item_id uuid,
    article_url character varying(512),
    answer_kind character varying(32),
    confidence character varying(16) DEFAULT 'low'::character varying NOT NULL,
    confidence_score numeric(5,2),
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.lead_messages (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    seq integer NOT NULL,
    lead_id uuid NOT NULL,
    author_role character varying(16) NOT NULL,
    body text NOT NULL,
    is_read boolean DEFAULT true NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
ALTER TABLE public.lead_messages ALTER COLUMN seq ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.lead_messages_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
CREATE TABLE public.leads (
    project_id uuid NOT NULL,
    lead_source character varying(64),
    reported_ai_product character varying(64),
    interested_course character varying(128),
    contact_name character varying(64),
    contact_phone character varying(64),
    contact_wechat character varying(64),
    is_valid boolean DEFAULT true NOT NULL,
    enrollment_status character varying(32) DEFAULT 'unknown'::character varying NOT NULL,
    note text,
    owner_id uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    import_batch_id uuid,
    source_question_id uuid,
    source_channel_id uuid,
    source_engine_id uuid,
    landing_url character varying(512),
    utm_campaign character varying(128),
    session_id character varying(64),
    serial_no integer NOT NULL,
    ip_hash character varying(64),
    visitor_region character varying(64),
    CONSTRAINT ck_leads_enrollment_status CHECK (((enrollment_status)::text = ANY ((ARRAY['unknown'::character varying, 'contacted'::character varying, 'enrolled'::character varying, 'lost'::character varying])::text[])))
);
CREATE SEQUENCE public.leads_serial_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.leads_serial_no_seq OWNED BY public.leads.serial_no;
CREATE TABLE public.materials (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    title character varying(255) NOT NULL,
    category character varying(32) DEFAULT 'document'::character varying NOT NULL,
    description text,
    file_name character varying(255) NOT NULL,
    content_type character varying(128),
    byte_size integer NOT NULL,
    checksum character varying(64) NOT NULL,
    storage_key character varying(512) NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    group_name character varying(120),
    sort_order integer DEFAULT 0 NOT NULL,
    source character varying(64),
    CONSTRAINT ck_materials_material_category CHECK (((category)::text = ANY ((ARRAY['image'::character varying, 'video'::character varying, 'document'::character varying, 'case'::character varying])::text[])))
);
CREATE TABLE public.media_matrix_configs (
    id uuid NOT NULL,
    key character varying(64) NOT NULL,
    payload jsonb DEFAULT '[]'::jsonb NOT NULL,
    updated_by uuid,
    note character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.media_orders (
    project_id uuid NOT NULL,
    provider_id uuid NOT NULL,
    idempotency_key character varying(120) NOT NULL,
    external_order_id character varying(128),
    media_name character varying(200) NOT NULL,
    quantity integer NOT NULL,
    unit_price numeric(12,2),
    currency character varying(8) NOT NULL,
    status character varying(32) DEFAULT 'draft'::character varying NOT NULL,
    request_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    response_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    error text,
    created_by uuid,
    submitted_at timestamp with time zone,
    published_at timestamp with time zone,
    publish_url character varying(500),
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_media_orders_media_order_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'submitted'::character varying, 'confirmed'::character varying, 'published'::character varying, 'failed'::character varying, 'cancelled'::character varying])::text[])))
);
CREATE TABLE public.media_providers (
    project_id uuid NOT NULL,
    code character varying(64) NOT NULL,
    name character varying(128) NOT NULL,
    adapter character varying(32) NOT NULL,
    endpoint character varying(500),
    token_env character varying(128),
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    capabilities jsonb DEFAULT '[]'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    last_health character varying(32),
    last_checked_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_media_providers_media_provider_adapter CHECK (((adapter)::text = ANY ((ARRAY['generic_http'::character varying, 'manual'::character varying])::text[])))
);
CREATE TABLE public.media_quotes (
    project_id uuid NOT NULL,
    plan_id uuid NOT NULL,
    channel_id uuid,
    unit_price numeric(12,2) NOT NULL,
    quantity integer NOT NULL,
    currency character varying(8) NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    approved_by uuid,
    approved_at timestamp with time zone,
    note text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_media_quotes_quote_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'withdrawn'::character varying])::text[])))
);
CREATE TABLE public.metric_definitions (
    project_id uuid NOT NULL,
    code character varying(64) NOT NULL,
    name character varying(128) NOT NULL,
    rule_version integer NOT NULL,
    formula text NOT NULL,
    description text,
    effective_from timestamp with time zone NOT NULL,
    effective_to timestamp with time zone,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_metric_definitions_metric_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'retired'::character varying])::text[])))
);
CREATE TABLE public.monitoring_brand_mentions (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    brand_profile_id uuid,
    term character varying(255) NOT NULL,
    term_type character varying(32) NOT NULL,
    offset_start integer NOT NULL,
    offset_end integer NOT NULL,
    evidence_text text,
    sentence text,
    list_rank integer,
    requires_review boolean DEFAULT false NOT NULL,
    matcher_version character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.monitoring_citations (
    project_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    raw_url text NOT NULL,
    normalized_url text,
    domain character varying(255),
    channel_id uuid,
    is_brand_related boolean NOT NULL,
    review_status character varying(32) DEFAULT 'auto'::character varying NOT NULL,
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    review_note text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    citation_usage character varying(32),
    competitor_id uuid,
    trace_id character varying(32),
    title text,
    "position" integer,
    source_category character varying(32) DEFAULT 'unknown'::character varying NOT NULL,
    page_type character varying(32) DEFAULT 'other'::character varying NOT NULL,
    classification_source character varying(32),
    classification_rule_version character varying(32),
    provider_fields jsonb,
    citation_order integer,
    provider_payload jsonb,
    parse_version character varying(32),
    is_domain_level boolean DEFAULT false NOT NULL,
    source_category_source character varying(32) DEFAULT 'unknown'::character varying NOT NULL,
    page_type_source character varying(32) DEFAULT 'unknown'::character varying NOT NULL,
    classified_at timestamp with time zone,
    classification_reviewed_by uuid,
    classification_reviewed_at timestamp with time zone,
    classification_note text,
    site_name character varying(255),
    snippet text,
    published_at timestamp with time zone,
    CONSTRAINT ck_monitoring_citations_citation_classification_source CHECK (((classification_source)::text = ANY ((ARRAY['rule'::character varying, 'manual'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_citations_citation_page_type CHECK (((page_type)::text = ANY ((ARRAY['homepage'::character varying, 'course_or_product'::character varying, 'article'::character varying, 'listicle'::character varying, 'how_to'::character varying, 'comparison'::character varying, 'review'::character varying, 'forum_or_qa'::character varying, 'video'::character varying, 'case_study'::character varying, 'faq'::character varying, 'search_surface'::character varying, 'other'::character varying, 'admissions'::character varying, 'recruitment'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_citations_citation_review_status CHECK (((review_status)::text = ANY ((ARRAY['auto'::character varying, 'manual_confirmed'::character varying, 'manual_rejected'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_citations_citation_source_category CHECK (((source_category)::text = ANY ((ARRAY['brand_owned'::character varying, 'competitor_owned'::character varying, 'social_community'::character varying, 'content_platform'::character varying, 'news_media'::character varying, 'industry_media'::character varying, 'government_institution'::character varying, 'education_institution'::character varying, 'reference'::character varying, 'ecommerce'::character varying, 'other'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_citations_citation_usage CHECK (((citation_usage)::text = ANY ((ARRAY['used'::character varying, 'cited'::character varying])::text[])))
);
CREATE TABLE public.monitoring_competitor_mentions (
    project_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    competitor_id uuid NOT NULL,
    "position" integer,
    evidence_text text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.monitoring_execution_attempts (
    project_id uuid NOT NULL,
    task_id uuid NOT NULL,
    attempt_no integer NOT NULL,
    worker_id character varying(64) NOT NULL,
    status character varying(32) DEFAULT 'claimed'::character varying NOT NULL,
    lease_expires_at timestamp with time zone,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    failure_code character varying(32),
    note text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_monitoring_execution_attempts_attempt_failure_code CHECK (((failure_code)::text = ANY ((ARRAY['login_blocked'::character varying, 'timeout'::character varying, 'access_blocked'::character varying, 'captcha'::character varying, 'rate_limited'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_execution_attempts_attempt_status CHECK (((status)::text = ANY ((ARRAY['claimed'::character varying, 'dispatching'::character varying, 'succeeded'::character varying, 'failed'::character varying, 'rate_limited'::character varying, 'lease_expired'::character varying, 'uncertain'::character varying])::text[])))
);
CREATE TABLE public.monitoring_retest_plans (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    name character varying(128) NOT NULL,
    interval_days integer DEFAULT 7 NOT NULL,
    first_run_at timestamp with time zone NOT NULL,
    next_run_at timestamp with time zone NOT NULL,
    entry_scope jsonb DEFAULT '["api", "app_search"]'::jsonb NOT NULL,
    samples_per_cell integer DEFAULT 1 NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    last_run_at timestamp with time zone,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    engine_codes jsonb DEFAULT '[]'::jsonb NOT NULL
);
CREATE TABLE public.monitoring_rounds (
    project_id uuid NOT NULL,
    seq integer NOT NULL,
    name character varying(128) NOT NULL,
    is_baseline boolean NOT NULL,
    planned_at timestamp with time zone,
    status character varying(32) DEFAULT 'planning'::character varying NOT NULL,
    created_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    analysis_config_snapshot jsonb,
    analysis_config_hash character varying(64),
    analysis_config_version character varying(32),
    analysis_config_captured_at timestamp with time zone,
    retest_plan_id uuid,
    scheduled_for timestamp with time zone,
    CONSTRAINT ck_monitoring_rounds_round_status CHECK (((status)::text = ANY ((ARRAY['planning'::character varying, 'running'::character varying, 'completed'::character varying, 'closed'::character varying])::text[])))
);
CREATE TABLE public.monitoring_samples (
    project_id uuid NOT NULL,
    task_id uuid NOT NULL,
    attempt_no integer NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    sampled_at timestamp with time zone,
    finished_at timestamp with time zone,
    sampling_mode character varying(32) NOT NULL,
    raw_answer text,
    raw_response jsonb,
    brand_mentioned boolean,
    failure_code character varying(32),
    failure_note text,
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    review_result character varying(32),
    review_note text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    engine_model character varying(64),
    model_version character varying(64),
    country_code character varying(8),
    language character varying(16),
    trace_id character varying(32),
    request_payload jsonb,
    latency_ms integer,
    prompt_tokens integer,
    completion_tokens integer,
    total_tokens integer,
    estimated_cost_cny numeric(14,6),
    gateway_version character varying(32),
    brand_identified boolean,
    answer_kind character varying(32),
    analysis_version character varying(32),
    analysis_config_hash character varying(64),
    analyzed_at timestamp with time zone,
    brand_match_kind character varying(16),
    brand_match_term character varying(128),
    brand_match_offset integer,
    brand_match_evidence text,
    brand_list_rank integer,
    matcher_version character varying(32),
    conversation_id character varying(64) NOT NULL,
    conversation_mode character varying(16) DEFAULT 'stateless'::character varying NOT NULL,
    serial_no integer NOT NULL,
    brand_match_offset_end integer,
    sampling_context jsonb,
    brand_recommendation boolean,
    recommendation_reason character varying(64),
    entity_mention_count integer,
    CONSTRAINT ck_monitoring_samples_answer_kind CHECK (((answer_kind)::text = ANY ((ARRAY['answer'::character varying, 'search_result'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_samples_ck_monitoring_samples_conversation_mode CHECK (((conversation_mode)::text = ANY ((ARRAY['stateless'::character varying, 'fresh'::character varying, 'manual'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_samples_failure_code CHECK (((failure_code)::text = ANY ((ARRAY['login_blocked'::character varying, 'timeout'::character varying, 'access_blocked'::character varying, 'captcha'::character varying, 'rate_limited'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_samples_review_result CHECK (((review_result)::text = ANY ((ARRAY['hit'::character varying, 'miss'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_samples_sample_sampling_mode CHECK (((sampling_mode)::text = ANY ((ARRAY['search_on'::character varying, 'search_off'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_samples_sample_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'hit'::character varying, 'miss'::character varying, 'no_answer_surface'::character varying, 'failed'::character varying, 'manual_review'::character varying])::text[])))
);
CREATE SEQUENCE public.monitoring_samples_serial_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.monitoring_samples_serial_no_seq OWNED BY public.monitoring_samples.serial_no;
CREATE TABLE public.monitoring_source_profiles (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    domain character varying(255) NOT NULL,
    source_category character varying(32) NOT NULL,
    suggested_source_category character varying(32),
    classification_rule_version character varying(32),
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.monitoring_tasks (
    project_id uuid NOT NULL,
    round_id uuid NOT NULL,
    question_version_id uuid NOT NULL,
    engine_entry_id uuid NOT NULL,
    sampling_no integer NOT NULL,
    sampling_mode character varying(32) NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    planned_at timestamp with time zone,
    created_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    trace_id character varying(32),
    lease_owner character varying(64),
    lease_expires_at timestamp with time zone,
    serial_no integer NOT NULL,
    CONSTRAINT ck_monitoring_tasks_sampling_mode CHECK (((sampling_mode)::text = ANY ((ARRAY['search_on'::character varying, 'search_off'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_tasks_task_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'done'::character varying, 'failed'::character varying, 'cancelled'::character varying, 'uncertain'::character varying])::text[])))
);
CREATE SEQUENCE public.monitoring_tasks_serial_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.monitoring_tasks_serial_no_seq OWNED BY public.monitoring_tasks.serial_no;
CREATE TABLE public.monthly_report_snapshots (
    project_id uuid NOT NULL,
    month character varying(7) NOT NULL,
    period_start timestamp with time zone NOT NULL,
    period_end timestamp with time zone NOT NULL,
    captured_by uuid,
    captured_at timestamp with time zone NOT NULL,
    report jsonb NOT NULL,
    definitions jsonb DEFAULT '{}'::jsonb NOT NULL,
    rule_version character varying(32) NOT NULL,
    snapshot_hash character varying(64) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.oauth_authorization_states (
    project_id uuid NOT NULL,
    provider_code character varying(64) NOT NULL,
    channel_id uuid,
    state_hash character varying(64) NOT NULL,
    code_verifier_encrypted text NOT NULL,
    redirect_uri character varying(2048) NOT NULL,
    return_path character varying(512) NOT NULL,
    created_by uuid,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.oauth_connections (
    project_id uuid NOT NULL,
    channel_id uuid,
    provider_code character varying(64) NOT NULL,
    external_account_id character varying(255) NOT NULL,
    external_account_name character varying(255),
    external_account_email character varying(255),
    scopes jsonb DEFAULT '[]'::jsonb NOT NULL,
    status character varying(32) DEFAULT 'connected'::character varying NOT NULL,
    access_token_encrypted text,
    refresh_token_encrypted text,
    token_type character varying(32) DEFAULT 'Bearer'::character varying NOT NULL,
    expires_at timestamp with time zone,
    connected_by uuid,
    connected_at timestamp with time zone,
    last_refreshed_at timestamp with time zone,
    revoked_at timestamp with time zone,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_oauth_connections_oauth_connection_status CHECK (((status)::text = ANY ((ARRAY['connected'::character varying, 'revoked'::character varying, 'error'::character varying])::text[])))
);
CREATE TABLE public.opportunities (
    project_id uuid NOT NULL,
    title character varying(255) NOT NULL,
    gap_type character varying(32) NOT NULL,
    question_id uuid,
    sample_id uuid,
    evidence_refs jsonb NOT NULL,
    score_factors jsonb NOT NULL,
    score_weights jsonb NOT NULL,
    priority_score numeric(3,2) NOT NULL,
    owner_id uuid,
    status character varying(32) DEFAULT 'open'::character varying NOT NULL,
    linked_content_plan_id uuid,
    linked_content_item_id uuid,
    linked_publish_task_id uuid,
    notes text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_opportunities_opportunity_gap_type CHECK (((gap_type)::text = ANY ((ARRAY['own_page'::character varying, 'media_report'::character varying, 'reference_site'::character varying, 'ugc'::character varying, 'fact_correction'::character varying, 'website_fix'::character varying])::text[]))),
    CONSTRAINT ck_opportunities_opportunity_status CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'in_progress'::character varying, 'done'::character varying, 'dismissed'::character varying])::text[])))
);
CREATE TABLE public.opportunity_suggestions (
    project_id uuid NOT NULL,
    rule_code character varying(32) NOT NULL,
    fingerprint character varying(128) NOT NULL,
    title character varying(255) NOT NULL,
    description text,
    gap_type character varying(32) NOT NULL,
    severity character varying(16) DEFAULT 'medium'::character varying NOT NULL,
    score double precision DEFAULT '3'::double precision NOT NULL,
    question_id uuid,
    sample_id uuid,
    source_type character varying(32),
    source_id character varying(64),
    evidence jsonb NOT NULL,
    status character varying(32) DEFAULT 'suggested'::character varying NOT NULL,
    accepted_opportunity_id uuid,
    review_note text,
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    generated_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_opportunity_suggestions_opportunity_suggestion_gap_type CHECK (((gap_type)::text = ANY ((ARRAY['own_page'::character varying, 'media_report'::character varying, 'reference_site'::character varying, 'ugc'::character varying, 'fact_correction'::character varying, 'website_fix'::character varying])::text[]))),
    CONSTRAINT ck_opportunity_suggestions_opportunity_suggestion_rule CHECK (((rule_code)::text = ANY ((ARRAY['brand_absent'::character varying, 'competitor_outrank'::character varying, 'source_gap'::character varying, 'fact_error'::character varying, 'stale_content'::character varying])::text[]))),
    CONSTRAINT ck_opportunity_suggestions_opportunity_suggestion_status CHECK (((status)::text = ANY ((ARRAY['suggested'::character varying, 'accepted'::character varying, 'dismissed'::character varying])::text[])))
);
CREATE TABLE public.organization_members (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role character varying(32) DEFAULT 'member'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.organization_usage_snapshots (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    captured_on date NOT NULL,
    projects integer DEFAULT 0 NOT NULL,
    members integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.organizations (
    id uuid NOT NULL,
    code character varying(64) NOT NULL,
    name character varying(128) NOT NULL,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    branding jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    settings jsonb DEFAULT '{}'::jsonb NOT NULL
);
CREATE TABLE public.outbox_events (
    project_id uuid,
    topic character varying(64) NOT NULL,
    payload jsonb NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    dispatched_at timestamp with time zone,
    error_note text,
    id uuid NOT NULL,
    failure_count integer DEFAULT 0 NOT NULL,
    CONSTRAINT ck_outbox_events_ck_outbox_events_project_or_system CHECK (((project_id IS NOT NULL) OR ((topic)::text ~~ 'system.%'::text))),
    CONSTRAINT ck_outbox_events_outbox_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'dispatched'::character varying, 'failed'::character varying])::text[])))
);
CREATE TABLE public.page_approvals (
    project_id uuid NOT NULL,
    channel_id uuid NOT NULL,
    page_url text NOT NULL,
    normalized_url text NOT NULL,
    url_key character varying(512) NOT NULL,
    title character varying(255),
    page_type character varying(32) NOT NULL,
    permission character varying(32) NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    requested_by uuid NOT NULL,
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    review_note text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_page_approvals_page_approval_page_type CHECK (((page_type)::text = ANY ((ARRAY['homepage'::character varying, 'course_or_product'::character varying, 'article'::character varying, 'listicle'::character varying, 'how_to'::character varying, 'comparison'::character varying, 'review'::character varying, 'forum_or_qa'::character varying, 'video'::character varying, 'case_study'::character varying, 'faq'::character varying, 'search_surface'::character varying, 'other'::character varying, 'admissions'::character varying, 'recruitment'::character varying])::text[]))),
    CONSTRAINT ck_page_approvals_page_approval_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'revoked'::character varying])::text[]))),
    CONSTRAINT ck_page_approvals_page_permission CHECK (((permission)::text = ANY ((ARRAY['official'::character varying, 'authorized'::character varying, 'third_party'::character varying])::text[])))
);
CREATE TABLE public.permissions (
    id uuid NOT NULL,
    code character varying(64) NOT NULL,
    name character varying(64) NOT NULL,
    scope character varying(32) DEFAULT 'project'::character varying NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_permissions_ck_permissions_permission_scope CHECK (((scope)::text = ANY ((ARRAY['system'::character varying, 'project'::character varying])::text[])))
);
CREATE TABLE public.project_contacts (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    channel character varying(32) NOT NULL,
    value character varying(255) NOT NULL,
    label character varying(64),
    is_public boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    notes text,
    is_active boolean DEFAULT true NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.project_members (
    project_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role_id uuid NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    granted_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.project_policies (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    key character varying(64) NOT NULL,
    value jsonb NOT NULL,
    note text,
    updated_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.project_strategies (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    strategy_key character varying(64) NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.projects (
    code character varying(32) NOT NULL,
    name character varying(128) NOT NULL,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    description text,
    timezone character varying(64) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    priority integer DEFAULT 3 NOT NULL,
    business_confirmed_at timestamp with time zone,
    business_confirmed_by uuid,
    organization_id uuid,
    CONSTRAINT ck_projects_priority_range CHECK (((priority >= 1) AND (priority <= 5))),
    CONSTRAINT ck_projects_project_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'paused'::character varying, 'archived'::character varying])::text[])))
);
CREATE TABLE public.public_pages (
    project_id uuid NOT NULL,
    slug character varying(128) NOT NULL,
    title character varying(255) NOT NULL,
    page_type character varying(32) NOT NULL,
    url text NOT NULL,
    canonical_url text,
    publish_status character varying(32) DEFAULT 'draft'::character varying NOT NULL,
    content_item_id uuid,
    last_published_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    robots_allowed boolean,
    in_sitemap boolean,
    canonical_ok boolean,
    http_status integer,
    js_dependent boolean,
    checked_at timestamp with time zone,
    check_error text,
    CONSTRAINT ck_public_pages_page_publish_status CHECK (((publish_status)::text = ANY ((ARRAY['draft'::character varying, 'published'::character varying, 'offline'::character varying])::text[]))),
    CONSTRAINT ck_public_pages_page_type CHECK (((page_type)::text = ANY ((ARRAY['home'::character varying, 'course'::character varying, 'faq'::character varying, 'case'::character varying, 'contact'::character varying, 'other'::character varying, 'admissions'::character varying, 'recruitment'::character varying])::text[])))
);
CREATE TABLE public.publish_accounts (
    project_id uuid NOT NULL,
    channel_id uuid NOT NULL,
    account_name character varying(128) NOT NULL,
    credential_ref character varying(255),
    is_active boolean DEFAULT true NOT NULL,
    notes text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    oauth_connection_id uuid
);
CREATE TABLE public.publish_attempts (
    project_id uuid NOT NULL,
    task_id uuid NOT NULL,
    attempt_no integer NOT NULL,
    mode character varying(32) NOT NULL,
    result character varying(32) NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    error_code character varying(64),
    error_note text,
    operator_id uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_publish_attempts_attempt_mode CHECK (((mode)::text = ANY ((ARRAY['manual'::character varying, 'api'::character varying, 'authorized'::character varying])::text[]))),
    CONSTRAINT ck_publish_attempts_attempt_result CHECK (((result)::text = ANY ((ARRAY['success'::character varying, 'failed'::character varying, 'unknown'::character varying])::text[])))
);
CREATE TABLE public.publish_receipts (
    project_id uuid NOT NULL,
    task_id uuid NOT NULL,
    attempt_id uuid,
    published_url text NOT NULL,
    receipt_payload jsonb,
    received_at timestamp with time zone NOT NULL,
    verified_by uuid,
    verified_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    budget_approval_id uuid,
    page_approval_id uuid,
    last_reachable boolean,
    last_reachability_status integer,
    last_reachability_error character varying(64),
    last_reachability_at timestamp with time zone
);
CREATE TABLE public.publish_tasks (
    project_id uuid NOT NULL,
    version_id uuid NOT NULL,
    channel_id uuid NOT NULL,
    account_id uuid NOT NULL,
    task_key character varying(64) NOT NULL,
    idempotency_key character varying(128) NOT NULL,
    publish_mode character varying(32) DEFAULT 'manual'::character varying NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    scheduled_at timestamp with time zone,
    external_task_id character varying(128),
    created_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    trace_id character varying(32),
    serial_no integer NOT NULL,
    source_batch_id uuid,
    CONSTRAINT ck_publish_tasks_publish_mode CHECK (((publish_mode)::text = ANY ((ARRAY['manual'::character varying, 'api'::character varying, 'authorized'::character varying])::text[]))),
    CONSTRAINT ck_publish_tasks_publish_task_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'publishing'::character varying, 'published'::character varying, 'unknown'::character varying, 'failed'::character varying, 'needs_review'::character varying, 'cancelled'::character varying])::text[])))
);
CREATE SEQUENCE public.publish_tasks_serial_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.publish_tasks_serial_no_seq OWNED BY public.publish_tasks.serial_no;
CREATE TABLE public.publish_visibility_checks (
    project_id uuid NOT NULL,
    receipt_id uuid NOT NULL,
    checked_at timestamp with time zone NOT NULL,
    matched boolean DEFAULT false NOT NULL,
    "position" integer,
    matched_url text,
    query text NOT NULL,
    site character varying(255),
    result_count integer DEFAULT 0 NOT NULL,
    request_id character varying(64),
    error_code character varying(64),
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.question_candidates (
    project_id uuid NOT NULL,
    text text NOT NULL,
    fingerprint character varying(64) NOT NULL,
    bucket character varying(32) NOT NULL,
    question_type character varying(32) NOT NULL,
    audience character varying(128),
    intent character varying(128),
    priority integer NOT NULL,
    source character varying(32) NOT NULL,
    source_ref character varying(255),
    rationale text,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    converted_question_id uuid,
    created_by uuid,
    reviewed_by uuid,
    reviewed_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_question_candidates_question_candidate_bucket CHECK (((bucket)::text = ANY ((ARRAY['category'::character varying, 'purchase'::character varying, 'reputation'::character varying])::text[]))),
    CONSTRAINT ck_question_candidates_question_candidate_source CHECK (((source)::text = ANY ((ARRAY['rule'::character varying, 'import'::character varying])::text[]))),
    CONSTRAINT ck_question_candidates_question_candidate_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'accepted'::character varying, 'rejected'::character varying])::text[]))),
    CONSTRAINT ck_question_candidates_question_candidate_type CHECK (((question_type)::text = ANY ((ARRAY['brand'::character varying, 'general'::character varying])::text[])))
);
CREATE TABLE public.question_keywords (
    project_id uuid NOT NULL,
    question_id uuid NOT NULL,
    keyword_id uuid NOT NULL,
    id uuid NOT NULL
);
CREATE TABLE public.question_version_keywords (
    project_id uuid NOT NULL,
    question_version_id uuid NOT NULL,
    keyword_id uuid NOT NULL,
    id uuid NOT NULL
);
CREATE TABLE public.question_versions (
    project_id uuid NOT NULL,
    question_id uuid NOT NULL,
    version_no integer NOT NULL,
    text text NOT NULL,
    change_note text,
    created_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    import_batch_id uuid,
    question_type character varying(32),
    audience character varying(128),
    intent character varying(128),
    priority integer,
    CONSTRAINT ck_question_versions_question_version_type CHECK (((question_type)::text = ANY ((ARRAY['brand'::character varying, 'general'::character varying])::text[])))
);
CREATE TABLE public.questions (
    project_id uuid NOT NULL,
    code character varying(32) NOT NULL,
    title character varying(255) NOT NULL,
    question_type character varying(32) NOT NULL,
    audience character varying(128),
    intent character varying(128),
    priority integer NOT NULL,
    status character varying(32) DEFAULT 'draft'::character varying NOT NULL,
    current_version_no integer NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    import_batch_id uuid,
    CONSTRAINT ck_questions_question_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_questions_question_type CHECK (((question_type)::text = ANY ((ARRAY['brand'::character varying, 'general'::character varying])::text[])))
);
CREATE TABLE public.report_shares (
    project_id uuid NOT NULL,
    snapshot_id uuid NOT NULL,
    token_hash character varying(64) NOT NULL,
    label character varying(120),
    password_hash character varying(255),
    brand_name character varying(80),
    brand_logo_url character varying(500),
    accent_color character varying(7) NOT NULL,
    contact_text text,
    show_leads boolean DEFAULT false NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    view_count integer DEFAULT 0 NOT NULL,
    last_viewed_at timestamp with time zone,
    created_by uuid,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.role_permissions (
    id uuid NOT NULL,
    role_id uuid NOT NULL,
    permission_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.roles (
    code character varying(32) NOT NULL,
    name character varying(64) NOT NULL,
    description text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_roles_role_code CHECK (((code)::text = ANY ((ARRAY['sys_admin'::character varying, 'project_admin'::character varying, 'editor'::character varying, 'reviewer'::character varying, 'viewer'::character varying, 'lead_ops'::character varying])::text[])))
);
CREATE TABLE public.selling_points (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    label character varying(80) NOT NULL,
    value_text text,
    aliases jsonb NOT NULL,
    required boolean DEFAULT true NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    note text,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.sentiment_labels (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    citation_id uuid NOT NULL,
    polarity character varying(32) NOT NULL,
    grade character varying(32),
    note text,
    labeled_by uuid,
    labeled_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_sentiment_labels_sentiment_polarity CHECK (((polarity)::text = ANY ((ARRAY['positive'::character varying, 'neutral'::character varying, 'negative'::character varying])::text[])))
);
CREATE TABLE public.site_modules (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    site_id uuid NOT NULL,
    module_type character varying(32) NOT NULL,
    title character varying(120) NOT NULL,
    content jsonb DEFAULT '{}'::jsonb NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_site_modules_site_module_type CHECK (((module_type)::text = ANY ((ARRAY['home'::character varying, 'services'::character varying, 'news'::character varying, 'download'::character varying, 'poster'::character varying, 'card'::character varying])::text[])))
);
CREATE TABLE public.site_sites (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    slug character varying(64) NOT NULL,
    title character varying(120) NOT NULL,
    intro text,
    is_published boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.source_domain_evidence (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    site character varying(200) NOT NULL,
    fetched_url character varying(500),
    title character varying(200),
    description text,
    sample_url character varying(500),
    sample_title character varying(200),
    status character varying(20) NOT NULL,
    detail character varying(120),
    fetched_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.stat_snapshots (
    project_id uuid NOT NULL,
    round_id uuid NOT NULL,
    captured_by uuid,
    captured_at timestamp with time zone NOT NULL,
    scope jsonb NOT NULL,
    metrics jsonb NOT NULL,
    definitions jsonb NOT NULL,
    rule_version character varying(32) NOT NULL,
    matcher_version character varying(32) NOT NULL,
    classifier_version character varying(32) NOT NULL,
    snapshot_hash character varying(64) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.traffic_events (
    project_id uuid NOT NULL,
    visitor_session_id character varying(64),
    landing_url text NOT NULL,
    utm_source character varying(128),
    utm_campaign character varying(128),
    referrer text,
    is_bot boolean DEFAULT false NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    import_source character varying(64),
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    visitor_ip_hash character varying(64),
    visitor_region character varying(64)
);
CREATE TABLE public.usage_events (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    organization_id uuid,
    metric character varying(32) NOT NULL,
    quantity integer DEFAULT 1 NOT NULL,
    source_type character varying(48) NOT NULL,
    source_id character varying(64) NOT NULL,
    occurred_on date NOT NULL,
    occurred_at timestamp with time zone,
    actor_id uuid,
    meta jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.users (
    username character varying(64) NOT NULL,
    email character varying(255),
    display_name character varying(64) NOT NULL,
    password_hash character varying(255) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    last_login_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_system_admin boolean DEFAULT false NOT NULL,
    token_version integer DEFAULT 0 NOT NULL,
    phone character varying(64),
    wechat character varying(64),
    job_title character varying(64)
);
ALTER TABLE ONLY public.answer_fact_claims ALTER COLUMN serial_no SET DEFAULT nextval('public.answer_fact_claims_serial_no_seq'::regclass);
ALTER TABLE ONLY public.audit_logs ALTER COLUMN serial_no SET DEFAULT nextval('public.audit_logs_serial_no_seq'::regclass);
ALTER TABLE ONLY public.leads ALTER COLUMN serial_no SET DEFAULT nextval('public.leads_serial_no_seq'::regclass);
ALTER TABLE ONLY public.monitoring_samples ALTER COLUMN serial_no SET DEFAULT nextval('public.monitoring_samples_serial_no_seq'::regclass);
ALTER TABLE ONLY public.monitoring_tasks ALTER COLUMN serial_no SET DEFAULT nextval('public.monitoring_tasks_serial_no_seq'::regclass);
ALTER TABLE ONLY public.publish_tasks ALTER COLUMN serial_no SET DEFAULT nextval('public.publish_tasks_serial_no_seq'::regclass);
ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);
ALTER TABLE ONLY public.ai_engine_entries
    ADD CONSTRAINT pk_ai_engine_entries PRIMARY KEY (id);
ALTER TABLE ONLY public.ai_engines
    ADD CONSTRAINT pk_ai_engines PRIMARY KEY (id);
ALTER TABLE ONLY public.alert_events
    ADD CONSTRAINT pk_alert_events PRIMARY KEY (id);
ALTER TABLE ONLY public.alert_rules
    ADD CONSTRAINT pk_alert_rules PRIMARY KEY (id);
ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT pk_answer_fact_claims PRIMARY KEY (id);
ALTER TABLE ONLY public.answer_snapshots
    ADD CONSTRAINT pk_answer_snapshots PRIMARY KEY (id);
ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT pk_api_keys PRIMARY KEY (id);
ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT pk_audit_logs PRIMARY KEY (id);
ALTER TABLE ONLY public.brand_profiles
    ADD CONSTRAINT pk_brand_profiles PRIMARY KEY (id);
ALTER TABLE ONLY public.brand_search_snapshots
    ADD CONSTRAINT pk_brand_search_snapshots PRIMARY KEY (id);
ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT pk_budget_approvals PRIMARY KEY (id);
ALTER TABLE ONLY public.certifications
    ADD CONSTRAINT pk_certifications PRIMARY KEY (id);
ALTER TABLE ONLY public.channel_aliases
    ADD CONSTRAINT pk_channel_aliases PRIMARY KEY (id);
ALTER TABLE ONLY public.channel_approvals
    ADD CONSTRAINT pk_channel_approvals PRIMARY KEY (id);
ALTER TABLE ONLY public.channels
    ADD CONSTRAINT pk_channels PRIMARY KEY (id);
ALTER TABLE ONLY public.citation_source_reviews
    ADD CONSTRAINT pk_citation_source_reviews PRIMARY KEY (id);
ALTER TABLE ONLY public.company_profiles
    ADD CONSTRAINT pk_company_profiles PRIMARY KEY (id);
ALTER TABLE ONLY public.competitors
    ADD CONSTRAINT pk_competitors PRIMARY KEY (id);
ALTER TABLE ONLY public.content_derivations
    ADD CONSTRAINT pk_content_derivations PRIMARY KEY (id);
ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT pk_content_items PRIMARY KEY (id);
ALTER TABLE ONLY public.content_plans
    ADD CONSTRAINT pk_content_plans PRIMARY KEY (id);
ALTER TABLE ONLY public.content_reviews
    ADD CONSTRAINT pk_content_reviews PRIMARY KEY (id);
ALTER TABLE ONLY public.content_templates
    ADD CONSTRAINT pk_content_templates PRIMARY KEY (id);
ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT pk_content_version_citations PRIMARY KEY (id);
ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT pk_content_version_facts PRIMARY KEY (id);
ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT pk_content_version_keywords PRIMARY KEY (id);
ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT pk_content_version_questions PRIMARY KEY (id);
ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT pk_content_versions PRIMARY KEY (id);
ALTER TABLE ONLY public.correction_tasks
    ADD CONSTRAINT pk_correction_tasks PRIMARY KEY (id);
ALTER TABLE ONLY public.crawler_events
    ADD CONSTRAINT pk_crawler_events PRIMARY KEY (id);
ALTER TABLE ONLY public.distribution_batch_items
    ADD CONSTRAINT pk_distribution_batch_items PRIMARY KEY (id);
ALTER TABLE ONLY public.distribution_batches
    ADD CONSTRAINT pk_distribution_batches PRIMARY KEY (id);
ALTER TABLE ONLY public.distribution_pushes
    ADD CONSTRAINT pk_distribution_pushes PRIMARY KEY (id);
ALTER TABLE ONLY public.encyclopedia_entries
    ADD CONSTRAINT pk_encyclopedia_entries PRIMARY KEY (id);
ALTER TABLE ONLY public.engine_targets
    ADD CONSTRAINT pk_engine_targets PRIMARY KEY (id);
ALTER TABLE ONLY public.evidence_files
    ADD CONSTRAINT pk_evidence_files PRIMARY KEY (id);
ALTER TABLE ONLY public.fact_versions
    ADD CONSTRAINT pk_fact_versions PRIMARY KEY (id);
ALTER TABLE ONLY public.facts
    ADD CONSTRAINT pk_facts PRIMARY KEY (id);
ALTER TABLE ONLY public.faqs
    ADD CONSTRAINT pk_faqs PRIMARY KEY (id);
ALTER TABLE ONLY public.generation_batches
    ADD CONSTRAINT pk_generation_batches PRIMARY KEY (id);
ALTER TABLE ONLY public.generation_gate_results
    ADD CONSTRAINT pk_generation_gate_results PRIMARY KEY (id);
ALTER TABLE ONLY public.generation_items
    ADD CONSTRAINT pk_generation_items PRIMARY KEY (id);
ALTER TABLE ONLY public.health_check_items
    ADD CONSTRAINT pk_health_check_items PRIMARY KEY (id);
ALTER TABLE ONLY public.health_check_runs
    ADD CONSTRAINT pk_health_check_runs PRIMARY KEY (id);
ALTER TABLE ONLY public.import_batches
    ADD CONSTRAINT pk_import_batches PRIMARY KEY (id);
ALTER TABLE ONLY public.industry_presets
    ADD CONSTRAINT pk_industry_presets PRIMARY KEY (id);
ALTER TABLE ONLY public.keywords
    ADD CONSTRAINT pk_keywords PRIMARY KEY (id);
ALTER TABLE ONLY public.knowledge_candidate_facts
    ADD CONSTRAINT pk_knowledge_candidate_facts PRIMARY KEY (id);
ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT pk_knowledge_chunks PRIMARY KEY (id);
ALTER TABLE ONLY public.knowledge_documents
    ADD CONSTRAINT pk_knowledge_documents PRIMARY KEY (id);
ALTER TABLE ONLY public.lead_attributions
    ADD CONSTRAINT pk_lead_attributions PRIMARY KEY (id);
ALTER TABLE ONLY public.lead_messages
    ADD CONSTRAINT pk_lead_messages PRIMARY KEY (id);
ALTER TABLE ONLY public.leads
    ADD CONSTRAINT pk_leads PRIMARY KEY (id);
ALTER TABLE ONLY public.materials
    ADD CONSTRAINT pk_materials PRIMARY KEY (id);
ALTER TABLE ONLY public.media_matrix_configs
    ADD CONSTRAINT pk_media_matrix_configs PRIMARY KEY (id);
ALTER TABLE ONLY public.media_orders
    ADD CONSTRAINT pk_media_orders PRIMARY KEY (id);
ALTER TABLE ONLY public.media_providers
    ADD CONSTRAINT pk_media_providers PRIMARY KEY (id);
ALTER TABLE ONLY public.media_quotes
    ADD CONSTRAINT pk_media_quotes PRIMARY KEY (id);
ALTER TABLE ONLY public.metric_definitions
    ADD CONSTRAINT pk_metric_definitions PRIMARY KEY (id);
ALTER TABLE ONLY public.monitoring_brand_mentions
    ADD CONSTRAINT pk_monitoring_brand_mentions PRIMARY KEY (id);
ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT pk_monitoring_citations PRIMARY KEY (id);
ALTER TABLE ONLY public.monitoring_competitor_mentions
    ADD CONSTRAINT pk_monitoring_competitor_mentions PRIMARY KEY (id);
ALTER TABLE ONLY public.monitoring_execution_attempts
    ADD CONSTRAINT pk_monitoring_execution_attempts PRIMARY KEY (id);
ALTER TABLE ONLY public.monitoring_retest_plans
    ADD CONSTRAINT pk_monitoring_retest_plans PRIMARY KEY (id);
ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT pk_monitoring_rounds PRIMARY KEY (id);
ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT pk_monitoring_samples PRIMARY KEY (id);
ALTER TABLE ONLY public.monitoring_source_profiles
    ADD CONSTRAINT pk_monitoring_source_profiles PRIMARY KEY (id);
ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT pk_monitoring_tasks PRIMARY KEY (id);
ALTER TABLE ONLY public.monthly_report_snapshots
    ADD CONSTRAINT pk_monthly_report_snapshots PRIMARY KEY (id);
ALTER TABLE ONLY public.oauth_authorization_states
    ADD CONSTRAINT pk_oauth_authorization_states PRIMARY KEY (id);
ALTER TABLE ONLY public.oauth_connections
    ADD CONSTRAINT pk_oauth_connections PRIMARY KEY (id);
ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT pk_opportunities PRIMARY KEY (id);
ALTER TABLE ONLY public.opportunity_suggestions
    ADD CONSTRAINT pk_opportunity_suggestions PRIMARY KEY (id);
ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT pk_organization_members PRIMARY KEY (id);
ALTER TABLE ONLY public.organization_usage_snapshots
    ADD CONSTRAINT pk_organization_usage_snapshots PRIMARY KEY (id);
ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT pk_organizations PRIMARY KEY (id);
ALTER TABLE ONLY public.outbox_events
    ADD CONSTRAINT pk_outbox_events PRIMARY KEY (id);
ALTER TABLE ONLY public.page_approvals
    ADD CONSTRAINT pk_page_approvals PRIMARY KEY (id);
ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT pk_permissions PRIMARY KEY (id);
ALTER TABLE ONLY public.project_contacts
    ADD CONSTRAINT pk_project_contacts PRIMARY KEY (id);
ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT pk_project_members PRIMARY KEY (id);
ALTER TABLE ONLY public.project_policies
    ADD CONSTRAINT pk_project_policies PRIMARY KEY (id);
ALTER TABLE ONLY public.project_strategies
    ADD CONSTRAINT pk_project_strategies PRIMARY KEY (id);
ALTER TABLE ONLY public.projects
    ADD CONSTRAINT pk_projects PRIMARY KEY (id);
ALTER TABLE ONLY public.public_pages
    ADD CONSTRAINT pk_public_pages PRIMARY KEY (id);
ALTER TABLE ONLY public.publish_accounts
    ADD CONSTRAINT pk_publish_accounts PRIMARY KEY (id);
ALTER TABLE ONLY public.publish_attempts
    ADD CONSTRAINT pk_publish_attempts PRIMARY KEY (id);
ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT pk_publish_receipts PRIMARY KEY (id);
ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT pk_publish_tasks PRIMARY KEY (id);
ALTER TABLE ONLY public.publish_visibility_checks
    ADD CONSTRAINT pk_publish_visibility_checks PRIMARY KEY (id);
ALTER TABLE ONLY public.question_candidates
    ADD CONSTRAINT pk_question_candidates PRIMARY KEY (id);
ALTER TABLE ONLY public.question_keywords
    ADD CONSTRAINT pk_question_keywords PRIMARY KEY (id);
ALTER TABLE ONLY public.question_version_keywords
    ADD CONSTRAINT pk_question_version_keywords PRIMARY KEY (id);
ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT pk_question_versions PRIMARY KEY (id);
ALTER TABLE ONLY public.questions
    ADD CONSTRAINT pk_questions PRIMARY KEY (id);
ALTER TABLE ONLY public.report_shares
    ADD CONSTRAINT pk_report_shares PRIMARY KEY (id);
ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT pk_role_permissions PRIMARY KEY (id);
ALTER TABLE ONLY public.roles
    ADD CONSTRAINT pk_roles PRIMARY KEY (id);
ALTER TABLE ONLY public.selling_points
    ADD CONSTRAINT pk_selling_points PRIMARY KEY (id);
ALTER TABLE ONLY public.sentiment_labels
    ADD CONSTRAINT pk_sentiment_labels PRIMARY KEY (id);
ALTER TABLE ONLY public.site_modules
    ADD CONSTRAINT pk_site_modules PRIMARY KEY (id);
ALTER TABLE ONLY public.site_sites
    ADD CONSTRAINT pk_site_sites PRIMARY KEY (id);
ALTER TABLE ONLY public.source_domain_evidence
    ADD CONSTRAINT pk_source_domain_evidence PRIMARY KEY (id);
ALTER TABLE ONLY public.stat_snapshots
    ADD CONSTRAINT pk_stat_snapshots PRIMARY KEY (id);
ALTER TABLE ONLY public.traffic_events
    ADD CONSTRAINT pk_traffic_events PRIMARY KEY (id);
ALTER TABLE ONLY public.usage_events
    ADD CONSTRAINT pk_usage_events PRIMARY KEY (id);
ALTER TABLE ONLY public.users
    ADD CONSTRAINT pk_users PRIMARY KEY (id);
ALTER TABLE ONLY public.ai_engine_entries
    ADD CONSTRAINT uq_ai_engine_entries_engine_type_name UNIQUE (engine_id, entry_type, name);
ALTER TABLE ONLY public.ai_engines
    ADD CONSTRAINT uq_ai_engines_code UNIQUE (code);
ALTER TABLE ONLY public.alert_events
    ADD CONSTRAINT uq_alert_events_project_rule_dedupe UNIQUE (project_id, rule_id, dedupe_key);
ALTER TABLE ONLY public.alert_rules
    ADD CONSTRAINT uq_alert_rules_project_code UNIQUE (project_id, code);
ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT uq_answer_fact_claims_serial_no UNIQUE (serial_no);
ALTER TABLE ONLY public.answer_snapshots
    ADD CONSTRAINT uq_answer_snapshots_project_sample UNIQUE (project_id, sample_id);
ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT uq_api_keys_key_hash UNIQUE (key_hash);
ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT uq_audit_logs_serial_no UNIQUE (serial_no);
ALTER TABLE ONLY public.brand_profiles
    ADD CONSTRAINT uq_brand_profiles_project UNIQUE (project_id);
ALTER TABLE ONLY public.brand_search_snapshots
    ADD CONSTRAINT uq_brand_search_project_platform_date UNIQUE (project_id, platform, snapshot_date);
ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT uq_budget_approvals_project_id_id UNIQUE (project_id, id);
ALTER TABLE ONLY public.channel_aliases
    ADD CONSTRAINT uq_channel_aliases_project_domain UNIQUE (project_id, domain);
ALTER TABLE ONLY public.channels
    ADD CONSTRAINT uq_channels_project_code UNIQUE (project_id, code);
ALTER TABLE ONLY public.citation_source_reviews
    ADD CONSTRAINT uq_citation_source_reviews_project_domain UNIQUE (project_id, domain);
ALTER TABLE ONLY public.company_profiles
    ADD CONSTRAINT uq_company_profiles_project UNIQUE (project_id);
ALTER TABLE ONLY public.competitors
    ADD CONSTRAINT uq_competitors_project_name UNIQUE (project_id, name);
ALTER TABLE ONLY public.content_derivations
    ADD CONSTRAINT uq_content_derivations_channel_item UNIQUE (project_id, channel_item_id);
ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT uq_content_version_citations_version_citation UNIQUE (version_id, citation_id);
ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT uq_content_version_facts_version_fact UNIQUE (version_id, fact_id);
ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT uq_content_version_keywords_version_keyword UNIQUE (version_id, keyword_id);
ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT uq_content_version_questions_version_question UNIQUE (version_id, question_id);
ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT uq_content_versions_item_version UNIQUE (item_id, version_no);
ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT uq_content_versions_project_id_id UNIQUE (project_id, id);
ALTER TABLE ONLY public.distribution_pushes
    ADD CONSTRAINT uq_distribution_pushes_fact_target UNIQUE (project_id, fact_id, target_type, target_ref);
ALTER TABLE ONLY public.distribution_pushes
    ADD CONSTRAINT uq_distribution_pushes_idem UNIQUE (project_id, idempotency_key);
ALTER TABLE ONLY public.encyclopedia_entries
    ADD CONSTRAINT uq_encyclopedia_entries_project_slug UNIQUE (project_id, slug);
ALTER TABLE ONLY public.engine_targets
    ADD CONSTRAINT uq_engine_targets_project_channel_engine UNIQUE (project_id, channel_id, engine_id);
ALTER TABLE ONLY public.fact_versions
    ADD CONSTRAINT uq_fact_versions_fact_version UNIQUE (fact_id, version_no);
ALTER TABLE ONLY public.facts
    ADD CONSTRAINT uq_facts_project_id_id UNIQUE (project_id, id);
ALTER TABLE ONLY public.facts
    ADD CONSTRAINT uq_facts_project_type_key UNIQUE (project_id, fact_type, fact_key);
ALTER TABLE ONLY public.industry_presets
    ADD CONSTRAINT uq_industry_presets_code UNIQUE (code);
ALTER TABLE ONLY public.keywords
    ADD CONSTRAINT uq_keywords_project_id_id UNIQUE (project_id, id);
ALTER TABLE ONLY public.keywords
    ADD CONSTRAINT uq_keywords_project_name UNIQUE (project_id, name);
ALTER TABLE ONLY public.knowledge_candidate_facts
    ADD CONSTRAINT uq_knowledge_candidate_facts_project_document_fingerprint UNIQUE (project_id, document_id, fingerprint);
ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT uq_knowledge_chunks_document_chunk UNIQUE (document_id, chunk_no);
ALTER TABLE ONLY public.knowledge_documents
    ADD CONSTRAINT uq_knowledge_documents_project_material UNIQUE (project_id, material_id);
ALTER TABLE ONLY public.lead_attributions
    ADD CONSTRAINT uq_lead_attributions_lead UNIQUE (lead_id);
ALTER TABLE ONLY public.leads
    ADD CONSTRAINT uq_leads_serial_no UNIQUE (serial_no);
ALTER TABLE ONLY public.media_matrix_configs
    ADD CONSTRAINT uq_media_matrix_configs_key UNIQUE (key);
ALTER TABLE ONLY public.media_orders
    ADD CONSTRAINT uq_media_orders_provider_idem UNIQUE (project_id, provider_id, idempotency_key);
ALTER TABLE ONLY public.media_providers
    ADD CONSTRAINT uq_media_providers_project_code UNIQUE (project_id, code);
ALTER TABLE ONLY public.media_quotes
    ADD CONSTRAINT uq_media_quotes_project_id_id UNIQUE (project_id, id);
ALTER TABLE ONLY public.metric_definitions
    ADD CONSTRAINT uq_metric_definitions_project_code_version UNIQUE (project_id, code, rule_version);
ALTER TABLE ONLY public.monitoring_execution_attempts
    ADD CONSTRAINT uq_monitoring_attempts_task_attempt UNIQUE (task_id, attempt_no);
ALTER TABLE ONLY public.monitoring_brand_mentions
    ADD CONSTRAINT uq_monitoring_brand_mentions_sample_term_offset UNIQUE (project_id, sample_id, term, offset_start);
ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT uq_monitoring_citations_project_id_id UNIQUE (project_id, id);
ALTER TABLE ONLY public.monitoring_competitor_mentions
    ADD CONSTRAINT uq_monitoring_competitor_mentions_sample_competitor UNIQUE (sample_id, competitor_id);
ALTER TABLE ONLY public.monitoring_retest_plans
    ADD CONSTRAINT uq_monitoring_retest_plans_project_name UNIQUE (project_id, name);
ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT uq_monitoring_rounds_plan_slot UNIQUE (retest_plan_id, scheduled_for);
ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT uq_monitoring_rounds_project_id_id UNIQUE (project_id, id);
ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT uq_monitoring_rounds_project_seq UNIQUE (project_id, seq);
ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT uq_monitoring_samples_project_conversation UNIQUE (project_id, conversation_id);
ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT uq_monitoring_samples_project_id_id UNIQUE (project_id, id);
ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT uq_monitoring_samples_serial_no UNIQUE (serial_no);
ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT uq_monitoring_samples_task_attempt UNIQUE (task_id, attempt_no);
ALTER TABLE ONLY public.monitoring_source_profiles
    ADD CONSTRAINT uq_monitoring_source_profiles_project_domain UNIQUE (project_id, domain);
ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT uq_monitoring_tasks_project_id_id UNIQUE (project_id, id);
ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT uq_monitoring_tasks_round_question_entry_sampling UNIQUE (round_id, question_version_id, engine_entry_id, sampling_no);
ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT uq_monitoring_tasks_serial_no UNIQUE (serial_no);
ALTER TABLE ONLY public.monthly_report_snapshots
    ADD CONSTRAINT uq_monthly_report_snapshots_project_month UNIQUE (project_id, month);
ALTER TABLE ONLY public.oauth_authorization_states
    ADD CONSTRAINT uq_oauth_authorization_states_state_hash UNIQUE (state_hash);
ALTER TABLE ONLY public.oauth_connections
    ADD CONSTRAINT uq_oauth_connections_project_provider_external UNIQUE (project_id, provider_code, external_account_id);
ALTER TABLE ONLY public.opportunity_suggestions
    ADD CONSTRAINT uq_opportunity_suggestions_project_rule_fingerprint UNIQUE (project_id, rule_code, fingerprint);
ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT uq_organization_members_user UNIQUE (organization_id, user_id);
ALTER TABLE ONLY public.organization_usage_snapshots
    ADD CONSTRAINT uq_organization_usage_snapshots_day UNIQUE (organization_id, captured_on);
ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT uq_organizations_code UNIQUE (code);
ALTER TABLE ONLY public.page_approvals
    ADD CONSTRAINT uq_page_approvals_project_channel_url UNIQUE (project_id, channel_id, url_key);
ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT uq_permissions_code UNIQUE (code);
ALTER TABLE ONLY public.project_contacts
    ADD CONSTRAINT uq_project_contacts_project_channel_value UNIQUE (project_id, channel, value);
ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT uq_project_members_project_user UNIQUE (project_id, user_id);
ALTER TABLE ONLY public.project_policies
    ADD CONSTRAINT uq_project_policies_project_key UNIQUE (project_id, key);
ALTER TABLE ONLY public.project_strategies
    ADD CONSTRAINT uq_project_strategies_key_version UNIQUE (project_id, strategy_key, version);
ALTER TABLE ONLY public.projects
    ADD CONSTRAINT uq_projects_code UNIQUE (code);
ALTER TABLE ONLY public.public_pages
    ADD CONSTRAINT uq_public_pages_project_slug UNIQUE (project_id, slug);
ALTER TABLE ONLY public.publish_accounts
    ADD CONSTRAINT uq_publish_accounts_oauth_connection UNIQUE (oauth_connection_id);
ALTER TABLE ONLY public.publish_accounts
    ADD CONSTRAINT uq_publish_accounts_project_channel_name UNIQUE (project_id, channel_id, account_name);
ALTER TABLE ONLY public.publish_attempts
    ADD CONSTRAINT uq_publish_attempts_task_attempt UNIQUE (task_id, attempt_no);
ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT uq_publish_receipts_project_id_id UNIQUE (project_id, id);
ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT uq_publish_tasks_idempotency UNIQUE (account_id, channel_id, version_id, task_key);
ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT uq_publish_tasks_idempotency_key UNIQUE (idempotency_key);
ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT uq_publish_tasks_serial_no UNIQUE (serial_no);
ALTER TABLE ONLY public.question_candidates
    ADD CONSTRAINT uq_question_candidates_project_fingerprint UNIQUE (project_id, fingerprint);
ALTER TABLE ONLY public.question_keywords
    ADD CONSTRAINT uq_question_keywords_question_keyword UNIQUE (question_id, keyword_id);
ALTER TABLE ONLY public.question_version_keywords
    ADD CONSTRAINT uq_question_version_keywords_version_keyword UNIQUE (question_version_id, keyword_id);
ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT uq_question_versions_project_id_id UNIQUE (project_id, id);
ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT uq_question_versions_question_version UNIQUE (question_id, version_no);
ALTER TABLE ONLY public.questions
    ADD CONSTRAINT uq_questions_project_code UNIQUE (project_id, code);
ALTER TABLE ONLY public.questions
    ADD CONSTRAINT uq_questions_project_id_id UNIQUE (project_id, id);
ALTER TABLE ONLY public.report_shares
    ADD CONSTRAINT uq_report_shares_token_hash UNIQUE (token_hash);
ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT uq_role_permissions_role_permission UNIQUE (role_id, permission_id);
ALTER TABLE ONLY public.roles
    ADD CONSTRAINT uq_roles_code UNIQUE (code);
ALTER TABLE ONLY public.selling_points
    ADD CONSTRAINT uq_selling_points_project_label UNIQUE (project_id, label);
ALTER TABLE ONLY public.sentiment_labels
    ADD CONSTRAINT uq_sentiment_labels_project_citation_labeler UNIQUE (project_id, citation_id, labeled_by);
ALTER TABLE ONLY public.site_modules
    ADD CONSTRAINT uq_site_modules_site_type UNIQUE (site_id, module_type);
ALTER TABLE ONLY public.site_sites
    ADD CONSTRAINT uq_site_sites_project_id UNIQUE (project_id);
ALTER TABLE ONLY public.site_sites
    ADD CONSTRAINT uq_site_sites_slug UNIQUE (slug);
ALTER TABLE ONLY public.source_domain_evidence
    ADD CONSTRAINT uq_source_domain_evidence_project_site UNIQUE (project_id, site);
ALTER TABLE ONLY public.stat_snapshots
    ADD CONSTRAINT uq_stat_snapshots_project_round UNIQUE (project_id, round_id);
ALTER TABLE ONLY public.usage_events
    ADD CONSTRAINT uq_usage_events_project_metric_source UNIQUE (project_id, metric, source_type, source_id);
ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_email UNIQUE (email);
ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_username UNIQUE (username);
CREATE INDEX ix_ai_engine_entries_active ON public.ai_engine_entries USING btree (engine_id, is_active);
CREATE INDEX ix_alert_events_project_status ON public.alert_events USING btree (project_id, status);
CREATE INDEX ix_alert_events_project_triggered ON public.alert_events USING btree (project_id, triggered_at);
CREATE INDEX ix_alert_rules_project_enabled ON public.alert_rules USING btree (project_id, is_enabled);
CREATE INDEX ix_answer_fact_claims_project_sample ON public.answer_fact_claims USING btree (project_id, sample_id);
CREATE INDEX ix_answer_fact_claims_project_verdict ON public.answer_fact_claims USING btree (project_id, verdict);
CREATE UNIQUE INDEX ix_api_keys_hash ON public.api_keys USING btree (key_hash);
CREATE INDEX ix_api_keys_project_active ON public.api_keys USING btree (project_id, is_active);
CREATE INDEX ix_audit_logs_project_created ON public.audit_logs USING btree (project_id, created_at);
CREATE INDEX ix_audit_logs_target ON public.audit_logs USING btree (target_type, target_id);
CREATE INDEX ix_brand_profiles_project_active ON public.brand_profiles USING btree (project_id, is_active);
CREATE INDEX ix_brand_search_project_date ON public.brand_search_snapshots USING btree (project_id, snapshot_date);
CREATE INDEX ix_budget_approvals_media_quote ON public.budget_approvals USING btree (media_quote_id);
CREATE INDEX ix_budget_approvals_project_status_category ON public.budget_approvals USING btree (project_id, status, category);
CREATE INDEX ix_certifications_project_active ON public.certifications USING btree (project_id, is_active);
CREATE INDEX ix_certifications_project_expires ON public.certifications USING btree (project_id, expires_on);
CREATE INDEX ix_channel_aliases_channel ON public.channel_aliases USING btree (channel_id);
CREATE INDEX ix_channel_approvals_project_channel ON public.channel_approvals USING btree (project_id, channel_id);
CREATE INDEX ix_channels_project_category_status ON public.channels USING btree (project_id, category, status);
CREATE INDEX ix_citation_source_reviews_project_status ON public.citation_source_reviews USING btree (project_id, status);
CREATE INDEX ix_company_profiles_project_active ON public.company_profiles USING btree (project_id, is_active);
CREATE INDEX ix_competitors_project_active ON public.competitors USING btree (project_id, is_active);
CREATE INDEX ix_content_derivations_project_master ON public.content_derivations USING btree (project_id, master_item_id);
CREATE INDEX ix_content_items_channel ON public.content_items USING btree (channel_id);
CREATE INDEX ix_content_items_parent ON public.content_items USING btree (parent_id);
CREATE INDEX ix_content_items_project_kind_status ON public.content_items USING btree (project_id, kind, status);
CREATE INDEX ix_content_plans_project_status_scheduled ON public.content_plans USING btree (project_id, status, scheduled_at);
CREATE INDEX ix_content_reviews_project_version ON public.content_reviews USING btree (project_id, version_id);
CREATE INDEX ix_content_reviews_reviewer ON public.content_reviews USING btree (reviewer_id);
CREATE INDEX ix_content_templates_project_active ON public.content_templates USING btree (project_id, is_active);
CREATE INDEX ix_content_versions_project_status ON public.content_versions USING btree (project_id, status);
CREATE INDEX ix_correction_tasks_project_status ON public.correction_tasks USING btree (project_id, status);
CREATE INDEX ix_crawler_events_project_bot ON public.crawler_events USING btree (project_id, verified_bot);
CREATE INDEX ix_crawler_events_project_occurred ON public.crawler_events USING btree (project_id, occurred_at);
CREATE INDEX ix_distribution_batches_project_status ON public.distribution_batches USING btree (project_id, status);
CREATE INDEX ix_distribution_pushes_project_status ON public.distribution_pushes USING btree (project_id, status);
CREATE INDEX ix_encyclopedia_entries_project_status ON public.encyclopedia_entries USING btree (project_id, status);
CREATE INDEX ix_engine_targets_project_channel ON public.engine_targets USING btree (project_id, channel_id);
CREATE INDEX ix_evidence_files_project_sample ON public.evidence_files USING btree (project_id, sample_id);
CREATE INDEX ix_fact_versions_project_fact ON public.fact_versions USING btree (project_id, fact_id);
CREATE INDEX ix_facts_project_type_status ON public.facts USING btree (project_id, fact_type, approval_status);
CREATE INDEX ix_faqs_project_category ON public.faqs USING btree (project_id, category);
CREATE INDEX ix_faqs_project_deleted ON public.faqs USING btree (project_id, deleted_at);
CREATE INDEX ix_faqs_project_status ON public.faqs USING btree (project_id, status);
CREATE INDEX ix_generation_batches_project_created ON public.generation_batches USING btree (project_id, created_at);
CREATE INDEX ix_generation_gate_results_batch_created ON public.generation_gate_results USING btree (batch_id, created_at);
CREATE INDEX ix_generation_gate_results_project_type ON public.generation_gate_results USING btree (project_id, gate_type);
CREATE INDEX ix_generation_items_batch_order ON public.generation_items USING btree (batch_id, sort_order);
CREATE INDEX ix_generation_items_project_status ON public.generation_items USING btree (project_id, status);
CREATE INDEX ix_health_check_items_run_order ON public.health_check_items USING btree (run_id, sort_order);
CREATE INDEX ix_health_check_runs_project_created ON public.health_check_runs USING btree (project_id, created_at);
CREATE INDEX ix_import_batches_project_started ON public.import_batches USING btree (project_id, started_at);
CREATE INDEX ix_keywords_project_status ON public.keywords USING btree (project_id, is_active);
CREATE INDEX ix_knowledge_candidate_facts_project_status ON public.knowledge_candidate_facts USING btree (project_id, status);
CREATE INDEX ix_knowledge_chunks_embedding_hnsw ON public.knowledge_chunks USING hnsw (embedding_vec public.vector_cosine_ops) WITH (m='16', ef_construction='64');
CREATE INDEX ix_knowledge_chunks_project_document ON public.knowledge_chunks USING btree (project_id, document_id);
CREATE INDEX ix_knowledge_documents_project_status ON public.knowledge_documents USING btree (project_id, parse_status);
CREATE INDEX ix_lead_attributions_project_article ON public.lead_attributions USING btree (project_id, content_item_id);
CREATE INDEX ix_lead_attributions_project_engine ON public.lead_attributions USING btree (project_id, engine_id);
CREATE INDEX ix_lead_attributions_project_question ON public.lead_attributions USING btree (project_id, question_id);
CREATE INDEX ix_lead_attributions_project_sample ON public.lead_attributions USING btree (project_id, sample_id);
CREATE INDEX ix_lead_messages_project_lead ON public.lead_messages USING btree (project_id, lead_id, created_at);
CREATE INDEX ix_lead_messages_project_unread ON public.lead_messages USING btree (project_id, is_read);
CREATE INDEX ix_leads_project_created ON public.leads USING btree (project_id, created_at);
CREATE INDEX ix_leads_project_enrollment ON public.leads USING btree (project_id, enrollment_status);
CREATE INDEX ix_leads_project_ip_hash ON public.leads USING btree (project_id, ip_hash);
CREATE INDEX ix_leads_project_session ON public.leads USING btree (project_id, session_id);
CREATE INDEX ix_leads_project_source_channel ON public.leads USING btree (project_id, source_channel_id);
CREATE INDEX ix_leads_project_source_engine ON public.leads USING btree (project_id, source_engine_id);
CREATE INDEX ix_leads_project_source_question ON public.leads USING btree (project_id, source_question_id);
CREATE INDEX ix_materials_project_category ON public.materials USING btree (project_id, category);
CREATE INDEX ix_materials_project_group ON public.materials USING btree (project_id, group_name);
CREATE INDEX ix_media_orders_project_status ON public.media_orders USING btree (project_id, status);
CREATE INDEX ix_media_orders_provider ON public.media_orders USING btree (provider_id);
CREATE INDEX ix_media_providers_project_active ON public.media_providers USING btree (project_id, is_active);
CREATE INDEX ix_media_quotes_project_status ON public.media_quotes USING btree (project_id, status);
CREATE INDEX ix_monitoring_attempts_project_task ON public.monitoring_execution_attempts USING btree (project_id, task_id);
CREATE INDEX ix_monitoring_attempts_status_lease ON public.monitoring_execution_attempts USING btree (status, lease_expires_at);
CREATE INDEX ix_monitoring_brand_mentions_project_sample ON public.monitoring_brand_mentions USING btree (project_id, sample_id);
CREATE INDEX ix_monitoring_citations_channel ON public.monitoring_citations USING btree (channel_id);
CREATE INDEX ix_monitoring_citations_project_competitor ON public.monitoring_citations USING btree (project_id, competitor_id);
CREATE INDEX ix_monitoring_citations_project_domain_review ON public.monitoring_citations USING btree (project_id, domain, review_status);
CREATE INDEX ix_monitoring_citations_project_page_type ON public.monitoring_citations USING btree (project_id, page_type);
CREATE INDEX ix_monitoring_citations_project_sample ON public.monitoring_citations USING btree (project_id, sample_id);
CREATE INDEX ix_monitoring_citations_project_source_category ON public.monitoring_citations USING btree (project_id, source_category);
CREATE INDEX ix_monitoring_citations_project_usage_domain ON public.monitoring_citations USING btree (project_id, citation_usage, domain);
CREATE INDEX ix_monitoring_citations_trace_id ON public.monitoring_citations USING btree (trace_id);
CREATE INDEX ix_monitoring_competitor_mentions_project_competitor ON public.monitoring_competitor_mentions USING btree (project_id, competitor_id);
CREATE INDEX ix_monitoring_competitor_mentions_project_sample ON public.monitoring_competitor_mentions USING btree (project_id, sample_id);
CREATE INDEX ix_monitoring_retest_plans_due ON public.monitoring_retest_plans USING btree (next_run_at, enabled);
CREATE INDEX ix_monitoring_retest_plans_project ON public.monitoring_retest_plans USING btree (project_id);
CREATE INDEX ix_monitoring_rounds_project_status ON public.monitoring_rounds USING btree (project_id, status);
CREATE INDEX ix_monitoring_rounds_retest_plan ON public.monitoring_rounds USING btree (retest_plan_id, scheduled_for);
CREATE INDEX ix_monitoring_samples_project_country_sampled_at ON public.monitoring_samples USING btree (project_id, country_code, sampled_at);
CREATE INDEX ix_monitoring_samples_project_engine_model_sampled_at ON public.monitoring_samples USING btree (project_id, engine_model, sampled_at);
CREATE INDEX ix_monitoring_samples_project_sampled_at ON public.monitoring_samples USING btree (project_id, sampled_at);
CREATE INDEX ix_monitoring_samples_project_status ON public.monitoring_samples USING btree (project_id, status);
CREATE INDEX ix_monitoring_samples_task_status ON public.monitoring_samples USING btree (task_id, status);
CREATE INDEX ix_monitoring_samples_trace_id ON public.monitoring_samples USING btree (trace_id);
CREATE INDEX ix_monitoring_source_profiles_project_domain ON public.monitoring_source_profiles USING btree (project_id, domain);
CREATE INDEX ix_monitoring_tasks_project_round_status ON public.monitoring_tasks USING btree (project_id, round_id, status);
CREATE INDEX ix_monitoring_tasks_project_status ON public.monitoring_tasks USING btree (project_id, status);
CREATE INDEX ix_monitoring_tasks_round ON public.monitoring_tasks USING btree (round_id);
CREATE INDEX ix_monitoring_tasks_trace_id ON public.monitoring_tasks USING btree (trace_id);
CREATE INDEX ix_monthly_report_snapshots_project_captured_at ON public.monthly_report_snapshots USING btree (project_id, captured_at);
CREATE INDEX ix_oauth_authorization_states_expiry ON public.oauth_authorization_states USING btree (expires_at);
CREATE INDEX ix_oauth_connections_channel ON public.oauth_connections USING btree (channel_id);
CREATE INDEX ix_oauth_connections_project_provider ON public.oauth_connections USING btree (project_id, provider_code);
CREATE INDEX ix_opportunities_project_status_score ON public.opportunities USING btree (project_id, status, priority_score);
CREATE INDEX ix_opportunity_suggestions_project_rule ON public.opportunity_suggestions USING btree (project_id, rule_code);
CREATE INDEX ix_opportunity_suggestions_project_status ON public.opportunity_suggestions USING btree (project_id, status);
CREATE INDEX ix_organization_members_org ON public.organization_members USING btree (organization_id, is_active);
CREATE INDEX ix_organization_usage_snapshots_org_day ON public.organization_usage_snapshots USING btree (organization_id, captured_on);
CREATE INDEX ix_outbox_events_project_id ON public.outbox_events USING btree (project_id);
CREATE INDEX ix_outbox_events_status_created ON public.outbox_events USING btree (status, created_at);
CREATE INDEX ix_page_approvals_channel ON public.page_approvals USING btree (channel_id);
CREATE INDEX ix_page_approvals_project_page_type ON public.page_approvals USING btree (project_id, page_type);
CREATE INDEX ix_page_approvals_project_status ON public.page_approvals USING btree (project_id, status);
CREATE INDEX ix_project_contacts_project_channel ON public.project_contacts USING btree (project_id, channel);
CREATE INDEX ix_project_members_project_id ON public.project_members USING btree (project_id);
CREATE INDEX ix_project_members_user ON public.project_members USING btree (user_id, is_active);
CREATE INDEX ix_project_policies_project_key ON public.project_policies USING btree (project_id, key);
CREATE INDEX ix_project_strategies_project_key ON public.project_strategies USING btree (project_id, strategy_key);
CREATE INDEX ix_public_pages_project_status ON public.public_pages USING btree (project_id, publish_status);
CREATE INDEX ix_publish_accounts_project ON public.publish_accounts USING btree (project_id);
CREATE INDEX ix_publish_attempts_project ON public.publish_attempts USING btree (project_id);
CREATE INDEX ix_publish_receipts_budget ON public.publish_receipts USING btree (budget_approval_id);
CREATE INDEX ix_publish_receipts_project_task ON public.publish_receipts USING btree (project_id, task_id);
CREATE INDEX ix_publish_tasks_project_status ON public.publish_tasks USING btree (project_id, status);
CREATE INDEX ix_publish_tasks_scheduled ON public.publish_tasks USING btree (project_id, scheduled_at);
CREATE INDEX ix_publish_tasks_source_batch_id ON public.publish_tasks USING btree (source_batch_id);
CREATE INDEX ix_publish_tasks_trace_id ON public.publish_tasks USING btree (trace_id);
CREATE INDEX ix_publish_visibility_checks_project_checked ON public.publish_visibility_checks USING btree (project_id, checked_at);
CREATE INDEX ix_publish_visibility_checks_receipt ON public.publish_visibility_checks USING btree (receipt_id);
CREATE INDEX ix_question_candidates_project_bucket ON public.question_candidates USING btree (project_id, bucket);
CREATE INDEX ix_question_candidates_project_status ON public.question_candidates USING btree (project_id, status);
CREATE INDEX ix_question_keywords_project ON public.question_keywords USING btree (project_id);
CREATE INDEX ix_question_version_keywords_project ON public.question_version_keywords USING btree (project_id);
CREATE INDEX ix_question_version_keywords_version ON public.question_version_keywords USING btree (question_version_id);
CREATE INDEX ix_question_versions_project ON public.question_versions USING btree (project_id);
CREATE INDEX ix_questions_project_type_status ON public.questions USING btree (project_id, question_type, status);
CREATE INDEX ix_report_shares_project_created ON public.report_shares USING btree (project_id, created_at);
CREATE INDEX ix_report_shares_project_snapshot ON public.report_shares USING btree (project_id, snapshot_id);
CREATE INDEX ix_role_permissions_permission ON public.role_permissions USING btree (permission_id);
CREATE INDEX ix_role_permissions_role ON public.role_permissions USING btree (role_id);
CREATE INDEX ix_selling_points_project_active ON public.selling_points USING btree (project_id, is_active);
CREATE INDEX ix_sentiment_labels_project_polarity ON public.sentiment_labels USING btree (project_id, polarity);
CREATE INDEX ix_site_modules_project_order ON public.site_modules USING btree (project_id, sort_order);
CREATE INDEX ix_source_domain_evidence_project_status ON public.source_domain_evidence USING btree (project_id, status);
CREATE INDEX ix_stat_snapshots_project_captured_at ON public.stat_snapshots USING btree (project_id, captured_at);
CREATE INDEX ix_traffic_events_project_ip_hash ON public.traffic_events USING btree (project_id, visitor_ip_hash);
CREATE INDEX ix_traffic_events_project_occurred ON public.traffic_events USING btree (project_id, occurred_at);
CREATE INDEX ix_traffic_events_project_session ON public.traffic_events USING btree (project_id, visitor_session_id);
CREATE INDEX ix_usage_events_org_metric_day ON public.usage_events USING btree (organization_id, metric, occurred_on);
CREATE INDEX ix_usage_events_project_day ON public.usage_events USING btree (project_id, occurred_on);
CREATE UNIQUE INDEX uq_channels_project_primary_domain ON public.channels USING btree (project_id, primary_domain) WHERE (primary_domain IS NOT NULL);
CREATE UNIQUE INDEX uq_monitoring_rounds_project_baseline ON public.monitoring_rounds USING btree (project_id) WHERE (is_baseline IS TRUE);
ALTER TABLE ONLY public.ai_engine_entries
    ADD CONSTRAINT fk_ai_engine_entries_engine_id_ai_engines FOREIGN KEY (engine_id) REFERENCES public.ai_engines(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.alert_events
    ADD CONSTRAINT fk_alert_events_acknowledged_by_users FOREIGN KEY (acknowledged_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.alert_events
    ADD CONSTRAINT fk_alert_events_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.alert_events
    ADD CONSTRAINT fk_alert_events_rule_id_alert_rules FOREIGN KEY (rule_id) REFERENCES public.alert_rules(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.alert_rules
    ADD CONSTRAINT fk_alert_rules_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_citation_id_monitoring_citations FOREIGN KEY (citation_id) REFERENCES public.monitoring_citations(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_correction FOREIGN KEY (correction_task_id) REFERENCES public.correction_tasks(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_fact_id_facts FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.answer_snapshots
    ADD CONSTRAINT fk_answer_snapshots_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.answer_snapshots
    ADD CONSTRAINT fk_answer_snapshots_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT fk_api_keys_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT fk_api_keys_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT fk_audit_logs_actor_id_users FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT fk_audit_logs_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.brand_profiles
    ADD CONSTRAINT fk_brand_profiles_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.brand_search_snapshots
    ADD CONSTRAINT fk_brand_search_snapshots_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.brand_search_snapshots
    ADD CONSTRAINT fk_brand_search_snapshots_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT fk_budget_approvals_approved_by_users FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT fk_budget_approvals_media_quote FOREIGN KEY (media_quote_id) REFERENCES public.media_quotes(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT fk_budget_approvals_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT fk_budget_approvals_project_media_quote FOREIGN KEY (project_id, media_quote_id) REFERENCES public.media_quotes(project_id, id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT fk_budget_approvals_requested_by_users FOREIGN KEY (requested_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.certifications
    ADD CONSTRAINT fk_certifications_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.certifications
    ADD CONSTRAINT fk_certifications_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.channel_aliases
    ADD CONSTRAINT fk_channel_aliases_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.channel_aliases
    ADD CONSTRAINT fk_channel_aliases_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.channel_approvals
    ADD CONSTRAINT fk_channel_approvals_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.channel_approvals
    ADD CONSTRAINT fk_channel_approvals_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.channel_approvals
    ADD CONSTRAINT fk_channel_approvals_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.channel_approvals
    ADD CONSTRAINT fk_channel_approvals_submitted_by_users FOREIGN KEY (submitted_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.channels
    ADD CONSTRAINT fk_channels_import_batch_id_import_batches FOREIGN KEY (import_batch_id) REFERENCES public.import_batches(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.channels
    ADD CONSTRAINT fk_channels_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.channels
    ADD CONSTRAINT fk_channels_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.channels
    ADD CONSTRAINT fk_channels_submitted_by_users FOREIGN KEY (submitted_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.citation_source_reviews
    ADD CONSTRAINT fk_citation_source_reviews_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.citation_source_reviews
    ADD CONSTRAINT fk_citation_source_reviews_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.company_profiles
    ADD CONSTRAINT fk_company_profiles_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.competitors
    ADD CONSTRAINT fk_competitors_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.content_derivations
    ADD CONSTRAINT fk_content_derivations_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_derivations
    ADD CONSTRAINT fk_content_derivations_channel_item_id_content_items FOREIGN KEY (channel_item_id) REFERENCES public.content_items(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_derivations
    ADD CONSTRAINT fk_content_derivations_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.content_derivations
    ADD CONSTRAINT fk_content_derivations_master_item_id_content_items FOREIGN KEY (master_item_id) REFERENCES public.content_items(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_derivations
    ADD CONSTRAINT fk_content_derivations_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.content_derivations
    ADD CONSTRAINT fk_content_derivations_source_version_id_content_versions FOREIGN KEY (source_version_id) REFERENCES public.content_versions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT fk_content_items_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT fk_content_items_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT fk_content_items_current_version FOREIGN KEY (current_version_id) REFERENCES public.content_versions(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT fk_content_items_import_batch_id_import_batches FOREIGN KEY (import_batch_id) REFERENCES public.import_batches(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT fk_content_items_parent_id_content_items FOREIGN KEY (parent_id) REFERENCES public.content_items(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT fk_content_items_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.content_plans
    ADD CONSTRAINT fk_content_plans_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.content_plans
    ADD CONSTRAINT fk_content_plans_content_item_id_content_items FOREIGN KEY (content_item_id) REFERENCES public.content_items(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.content_plans
    ADD CONSTRAINT fk_content_plans_owner_id_users FOREIGN KEY (owner_id) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.content_plans
    ADD CONSTRAINT fk_content_plans_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.content_plans
    ADD CONSTRAINT fk_content_plans_site_page_id_public_pages FOREIGN KEY (site_page_id) REFERENCES public.public_pages(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.content_reviews
    ADD CONSTRAINT fk_content_reviews_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.content_reviews
    ADD CONSTRAINT fk_content_reviews_reviewer_id_users FOREIGN KEY (reviewer_id) REFERENCES public.users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.content_reviews
    ADD CONSTRAINT fk_content_reviews_version_id_content_versions FOREIGN KEY (version_id) REFERENCES public.content_versions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_templates
    ADD CONSTRAINT fk_content_templates_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.content_templates
    ADD CONSTRAINT fk_content_templates_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT fk_content_version_citations_citation_id_monitoring_citations FOREIGN KEY (citation_id) REFERENCES public.monitoring_citations(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT fk_content_version_citations_project_citation FOREIGN KEY (project_id, citation_id) REFERENCES public.monitoring_citations(project_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT fk_content_version_citations_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT fk_content_version_citations_project_version FOREIGN KEY (project_id, version_id) REFERENCES public.content_versions(project_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT fk_content_version_citations_version_id_content_versions FOREIGN KEY (version_id) REFERENCES public.content_versions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT fk_content_version_facts_fact_id_facts FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT fk_content_version_facts_project_fact FOREIGN KEY (project_id, fact_id) REFERENCES public.facts(project_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT fk_content_version_facts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT fk_content_version_facts_project_version FOREIGN KEY (project_id, version_id) REFERENCES public.content_versions(project_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT fk_content_version_facts_version_id_content_versions FOREIGN KEY (version_id) REFERENCES public.content_versions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT fk_content_version_keywords_keyword_id_keywords FOREIGN KEY (keyword_id) REFERENCES public.keywords(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT fk_content_version_keywords_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT fk_content_version_keywords_project_keyword FOREIGN KEY (project_id, keyword_id) REFERENCES public.keywords(project_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT fk_content_version_keywords_project_version FOREIGN KEY (project_id, version_id) REFERENCES public.content_versions(project_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT fk_content_version_keywords_version_id_content_versions FOREIGN KEY (version_id) REFERENCES public.content_versions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT fk_content_version_questions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT fk_content_version_questions_project_question FOREIGN KEY (project_id, question_id) REFERENCES public.questions(project_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT fk_content_version_questions_project_version FOREIGN KEY (project_id, version_id) REFERENCES public.content_versions(project_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT fk_content_version_questions_question_id_questions FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT fk_content_version_questions_version_id_content_versions FOREIGN KEY (version_id) REFERENCES public.content_versions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT fk_content_versions_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT fk_content_versions_import_batch_id_import_batches FOREIGN KEY (import_batch_id) REFERENCES public.import_batches(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT fk_content_versions_item_id_content_items FOREIGN KEY (item_id) REFERENCES public.content_items(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT fk_content_versions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT fk_content_versions_submitted_by_users FOREIGN KEY (submitted_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.correction_tasks
    ADD CONSTRAINT fk_correction_tasks_claim FOREIGN KEY (claim_id) REFERENCES public.answer_fact_claims(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.correction_tasks
    ADD CONSTRAINT fk_correction_tasks_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.correction_tasks
    ADD CONSTRAINT fk_correction_tasks_fact_id_facts FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.correction_tasks
    ADD CONSTRAINT fk_correction_tasks_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.crawler_events
    ADD CONSTRAINT fk_crawler_events_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.crawler_events
    ADD CONSTRAINT fk_crawler_events_public_page_id_public_pages FOREIGN KEY (public_page_id) REFERENCES public.public_pages(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.distribution_batch_items
    ADD CONSTRAINT fk_distribution_batch_items_batch_id_distribution_batches FOREIGN KEY (batch_id) REFERENCES public.distribution_batches(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.distribution_batch_items
    ADD CONSTRAINT fk_distribution_batch_items_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.distribution_batch_items
    ADD CONSTRAINT fk_distribution_batch_items_version FOREIGN KEY (content_version_id) REFERENCES public.content_versions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.distribution_batches
    ADD CONSTRAINT fk_distribution_batches_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.distribution_batches
    ADD CONSTRAINT fk_distribution_batches_dispatched_by_users FOREIGN KEY (dispatched_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.distribution_batches
    ADD CONSTRAINT fk_distribution_batches_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.distribution_pushes
    ADD CONSTRAINT fk_distribution_pushes_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.distribution_pushes
    ADD CONSTRAINT fk_distribution_pushes_fact_id_facts FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.distribution_pushes
    ADD CONSTRAINT fk_distribution_pushes_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.encyclopedia_entries
    ADD CONSTRAINT fk_encyclopedia_entries_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.encyclopedia_entries
    ADD CONSTRAINT fk_encyclopedia_entries_reviewer_id_users FOREIGN KEY (reviewer_id) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.engine_targets
    ADD CONSTRAINT fk_engine_targets_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.engine_targets
    ADD CONSTRAINT fk_engine_targets_content_plan_id_content_plans FOREIGN KEY (content_plan_id) REFERENCES public.content_plans(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.engine_targets
    ADD CONSTRAINT fk_engine_targets_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.engine_targets
    ADD CONSTRAINT fk_engine_targets_engine_id_ai_engines FOREIGN KEY (engine_id) REFERENCES public.ai_engines(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.engine_targets
    ADD CONSTRAINT fk_engine_targets_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.evidence_files
    ADD CONSTRAINT fk_evidence_files_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.evidence_files
    ADD CONSTRAINT fk_evidence_files_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.fact_versions
    ADD CONSTRAINT fk_fact_versions_actor_id_users FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.fact_versions
    ADD CONSTRAINT fk_fact_versions_fact_id_facts FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.fact_versions
    ADD CONSTRAINT fk_fact_versions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.facts
    ADD CONSTRAINT fk_facts_approved_by_users FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.facts
    ADD CONSTRAINT fk_facts_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.facts
    ADD CONSTRAINT fk_facts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.facts
    ADD CONSTRAINT fk_facts_superseded_by_facts FOREIGN KEY (superseded_by) REFERENCES public.facts(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.faqs
    ADD CONSTRAINT fk_faqs_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.faqs
    ADD CONSTRAINT fk_faqs_deleted_by_users FOREIGN KEY (deleted_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.faqs
    ADD CONSTRAINT fk_faqs_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.faqs
    ADD CONSTRAINT fk_faqs_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.generation_batches
    ADD CONSTRAINT fk_generation_batches_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.generation_batches
    ADD CONSTRAINT fk_generation_batches_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.generation_gate_results
    ADD CONSTRAINT fk_generation_gate_results_batch_id_generation_batches FOREIGN KEY (batch_id) REFERENCES public.generation_batches(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.generation_gate_results
    ADD CONSTRAINT fk_generation_gate_results_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.generation_gate_results
    ADD CONSTRAINT fk_generation_gate_results_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.generation_items
    ADD CONSTRAINT fk_generation_items_batch_id_generation_batches FOREIGN KEY (batch_id) REFERENCES public.generation_batches(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.generation_items
    ADD CONSTRAINT fk_generation_items_opportunity_id_opportunities FOREIGN KEY (opportunity_id) REFERENCES public.opportunities(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.generation_items
    ADD CONSTRAINT fk_generation_items_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.generation_items
    ADD CONSTRAINT fk_generation_items_question_id_questions FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.health_check_items
    ADD CONSTRAINT fk_health_check_items_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.health_check_items
    ADD CONSTRAINT fk_health_check_items_run_id_health_check_runs FOREIGN KEY (run_id) REFERENCES public.health_check_runs(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.health_check_runs
    ADD CONSTRAINT fk_health_check_runs_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.health_check_runs
    ADD CONSTRAINT fk_health_check_runs_triggered_by_users FOREIGN KEY (triggered_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.import_batches
    ADD CONSTRAINT fk_import_batches_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.import_batches
    ADD CONSTRAINT fk_import_batches_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.keywords
    ADD CONSTRAINT fk_keywords_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.knowledge_candidate_facts
    ADD CONSTRAINT fk_knowledge_candidate_facts_chunk_id_knowledge_chunks FOREIGN KEY (chunk_id) REFERENCES public.knowledge_chunks(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.knowledge_candidate_facts
    ADD CONSTRAINT fk_knowledge_candidate_facts_document_id_knowledge_documents FOREIGN KEY (document_id) REFERENCES public.knowledge_documents(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.knowledge_candidate_facts
    ADD CONSTRAINT fk_knowledge_candidate_facts_fact_id_facts FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.knowledge_candidate_facts
    ADD CONSTRAINT fk_knowledge_candidate_facts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.knowledge_candidate_facts
    ADD CONSTRAINT fk_knowledge_candidate_facts_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT fk_knowledge_chunks_document_id_knowledge_documents FOREIGN KEY (document_id) REFERENCES public.knowledge_documents(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT fk_knowledge_chunks_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.knowledge_documents
    ADD CONSTRAINT fk_knowledge_documents_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.knowledge_documents
    ADD CONSTRAINT fk_knowledge_documents_material_id_materials FOREIGN KEY (material_id) REFERENCES public.materials(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.knowledge_documents
    ADD CONSTRAINT fk_knowledge_documents_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.lead_attributions
    ADD CONSTRAINT fk_lead_attributions_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.lead_attributions
    ADD CONSTRAINT fk_lead_attributions_content_item_id_content_items FOREIGN KEY (content_item_id) REFERENCES public.content_items(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.lead_attributions
    ADD CONSTRAINT fk_lead_attributions_engine_id_ai_engines FOREIGN KEY (engine_id) REFERENCES public.ai_engines(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.lead_attributions
    ADD CONSTRAINT fk_lead_attributions_lead_id_leads FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.lead_attributions
    ADD CONSTRAINT fk_lead_attributions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.lead_attributions
    ADD CONSTRAINT fk_lead_attributions_question_id_questions FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.lead_attributions
    ADD CONSTRAINT fk_lead_attributions_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.lead_messages
    ADD CONSTRAINT fk_lead_messages_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.lead_messages
    ADD CONSTRAINT fk_lead_messages_lead_id_leads FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.lead_messages
    ADD CONSTRAINT fk_lead_messages_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.leads
    ADD CONSTRAINT fk_leads_import_batch_id_import_batches FOREIGN KEY (import_batch_id) REFERENCES public.import_batches(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.leads
    ADD CONSTRAINT fk_leads_owner_id_users FOREIGN KEY (owner_id) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.leads
    ADD CONSTRAINT fk_leads_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.leads
    ADD CONSTRAINT fk_leads_source_channel_id_channels FOREIGN KEY (source_channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.leads
    ADD CONSTRAINT fk_leads_source_engine_id_ai_engines FOREIGN KEY (source_engine_id) REFERENCES public.ai_engines(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.leads
    ADD CONSTRAINT fk_leads_source_question_id_questions FOREIGN KEY (source_question_id) REFERENCES public.questions(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.materials
    ADD CONSTRAINT fk_materials_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.materials
    ADD CONSTRAINT fk_materials_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.media_matrix_configs
    ADD CONSTRAINT fk_media_matrix_configs_updated_by_users FOREIGN KEY (updated_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.media_orders
    ADD CONSTRAINT fk_media_orders_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.media_orders
    ADD CONSTRAINT fk_media_orders_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.media_orders
    ADD CONSTRAINT fk_media_orders_provider_id_media_providers FOREIGN KEY (provider_id) REFERENCES public.media_providers(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.media_providers
    ADD CONSTRAINT fk_media_providers_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.media_quotes
    ADD CONSTRAINT fk_media_quotes_approved_by_users FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.media_quotes
    ADD CONSTRAINT fk_media_quotes_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.media_quotes
    ADD CONSTRAINT fk_media_quotes_plan_id_content_plans FOREIGN KEY (plan_id) REFERENCES public.content_plans(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.media_quotes
    ADD CONSTRAINT fk_media_quotes_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.metric_definitions
    ADD CONSTRAINT fk_metric_definitions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_brand_mentions
    ADD CONSTRAINT fk_monitoring_brand_mentions_brand_profile_id_brand_profiles FOREIGN KEY (brand_profile_id) REFERENCES public.brand_profiles(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.monitoring_brand_mentions
    ADD CONSTRAINT fk_monitoring_brand_mentions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_brand_mentions
    ADD CONSTRAINT fk_monitoring_brand_mentions_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_classification_reviewed_by_users FOREIGN KEY (classification_reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_competitor_id_competitors FOREIGN KEY (competitor_id) REFERENCES public.competitors(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_project_sample FOREIGN KEY (project_id, sample_id) REFERENCES public.monitoring_samples(project_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.monitoring_competitor_mentions
    ADD CONSTRAINT fk_monitoring_competitor_mentions_competitor_id_competitors FOREIGN KEY (competitor_id) REFERENCES public.competitors(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.monitoring_competitor_mentions
    ADD CONSTRAINT fk_monitoring_competitor_mentions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_competitor_mentions
    ADD CONSTRAINT fk_monitoring_competitor_mentions_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.monitoring_execution_attempts
    ADD CONSTRAINT fk_monitoring_execution_attempts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_execution_attempts
    ADD CONSTRAINT fk_monitoring_execution_attempts_task_id_monitoring_tasks FOREIGN KEY (task_id) REFERENCES public.monitoring_tasks(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.monitoring_retest_plans
    ADD CONSTRAINT fk_monitoring_retest_plans_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.monitoring_retest_plans
    ADD CONSTRAINT fk_monitoring_retest_plans_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT fk_monitoring_rounds_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT fk_monitoring_rounds_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT fk_monitoring_rounds_retest_plan_id_monitoring_retest_plans FOREIGN KEY (retest_plan_id) REFERENCES public.monitoring_retest_plans(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT fk_monitoring_samples_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT fk_monitoring_samples_project_task FOREIGN KEY (project_id, task_id) REFERENCES public.monitoring_tasks(project_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT fk_monitoring_samples_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT fk_monitoring_samples_task_id_monitoring_tasks FOREIGN KEY (task_id) REFERENCES public.monitoring_tasks(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.monitoring_source_profiles
    ADD CONSTRAINT fk_monitoring_source_profiles_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_source_profiles
    ADD CONSTRAINT fk_monitoring_source_profiles_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_engine_entry_id_ai_engine_entries FOREIGN KEY (engine_entry_id) REFERENCES public.ai_engine_entries(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_project_question_version FOREIGN KEY (project_id, question_version_id) REFERENCES public.question_versions(project_id, id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_project_round FOREIGN KEY (project_id, round_id) REFERENCES public.monitoring_rounds(project_id, id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_question_version_id_question_versions FOREIGN KEY (question_version_id) REFERENCES public.question_versions(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_round_id_monitoring_rounds FOREIGN KEY (round_id) REFERENCES public.monitoring_rounds(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.monthly_report_snapshots
    ADD CONSTRAINT fk_monthly_report_snapshots_captured_by_users FOREIGN KEY (captured_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.monthly_report_snapshots
    ADD CONSTRAINT fk_monthly_report_snapshots_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.oauth_authorization_states
    ADD CONSTRAINT fk_oauth_authorization_states_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.oauth_authorization_states
    ADD CONSTRAINT fk_oauth_authorization_states_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.oauth_authorization_states
    ADD CONSTRAINT fk_oauth_authorization_states_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.oauth_connections
    ADD CONSTRAINT fk_oauth_connections_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.oauth_connections
    ADD CONSTRAINT fk_oauth_connections_connected_by_users FOREIGN KEY (connected_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.oauth_connections
    ADD CONSTRAINT fk_oauth_connections_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_linked_content_item_id_content_items FOREIGN KEY (linked_content_item_id) REFERENCES public.content_items(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_linked_content_plan_id_content_plans FOREIGN KEY (linked_content_plan_id) REFERENCES public.content_plans(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_linked_publish_task_id_publish_tasks FOREIGN KEY (linked_publish_task_id) REFERENCES public.publish_tasks(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_owner_id_users FOREIGN KEY (owner_id) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_question_id_questions FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.opportunity_suggestions
    ADD CONSTRAINT fk_opportunity_suggestions_accepted_opportunity_id_oppo_ce07 FOREIGN KEY (accepted_opportunity_id) REFERENCES public.opportunities(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.opportunity_suggestions
    ADD CONSTRAINT fk_opportunity_suggestions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.opportunity_suggestions
    ADD CONSTRAINT fk_opportunity_suggestions_question_id_questions FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.opportunity_suggestions
    ADD CONSTRAINT fk_opportunity_suggestions_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.opportunity_suggestions
    ADD CONSTRAINT fk_opportunity_suggestions_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT fk_organization_members_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT fk_organization_members_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.organization_usage_snapshots
    ADD CONSTRAINT fk_organization_usage_snapshots_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.outbox_events
    ADD CONSTRAINT fk_outbox_events_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.page_approvals
    ADD CONSTRAINT fk_page_approvals_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.page_approvals
    ADD CONSTRAINT fk_page_approvals_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.page_approvals
    ADD CONSTRAINT fk_page_approvals_requested_by_users FOREIGN KEY (requested_by) REFERENCES public.users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.page_approvals
    ADD CONSTRAINT fk_page_approvals_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.project_contacts
    ADD CONSTRAINT fk_project_contacts_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.project_contacts
    ADD CONSTRAINT fk_project_contacts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT fk_project_members_granted_by_users FOREIGN KEY (granted_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT fk_project_members_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT fk_project_members_role_id_roles FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT fk_project_members_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.project_policies
    ADD CONSTRAINT fk_project_policies_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.project_policies
    ADD CONSTRAINT fk_project_policies_updated_by_users FOREIGN KEY (updated_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.project_strategies
    ADD CONSTRAINT fk_project_strategies_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.projects
    ADD CONSTRAINT fk_projects_business_confirmed_by_users FOREIGN KEY (business_confirmed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.projects
    ADD CONSTRAINT fk_projects_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.public_pages
    ADD CONSTRAINT fk_public_pages_content_item_id_content_items FOREIGN KEY (content_item_id) REFERENCES public.content_items(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.public_pages
    ADD CONSTRAINT fk_public_pages_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.publish_accounts
    ADD CONSTRAINT fk_publish_accounts_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.publish_accounts
    ADD CONSTRAINT fk_publish_accounts_oauth_connection_id FOREIGN KEY (oauth_connection_id) REFERENCES public.oauth_connections(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.publish_accounts
    ADD CONSTRAINT fk_publish_accounts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.publish_attempts
    ADD CONSTRAINT fk_publish_attempts_operator_id_users FOREIGN KEY (operator_id) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.publish_attempts
    ADD CONSTRAINT fk_publish_attempts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.publish_attempts
    ADD CONSTRAINT fk_publish_attempts_task_id_publish_tasks FOREIGN KEY (task_id) REFERENCES public.publish_tasks(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_attempt_id_publish_attempts FOREIGN KEY (attempt_id) REFERENCES public.publish_attempts(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_budget FOREIGN KEY (budget_approval_id) REFERENCES public.budget_approvals(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_page_approval_id FOREIGN KEY (page_approval_id) REFERENCES public.page_approvals(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_project_budget FOREIGN KEY (project_id, budget_approval_id) REFERENCES public.budget_approvals(project_id, id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_task_id_publish_tasks FOREIGN KEY (task_id) REFERENCES public.publish_tasks(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_verified_by_users FOREIGN KEY (verified_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT fk_publish_tasks_account_id_publish_accounts FOREIGN KEY (account_id) REFERENCES public.publish_accounts(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT fk_publish_tasks_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT fk_publish_tasks_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT fk_publish_tasks_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT fk_publish_tasks_source_batch FOREIGN KEY (source_batch_id) REFERENCES public.distribution_batches(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT fk_publish_tasks_version_id_content_versions FOREIGN KEY (version_id) REFERENCES public.content_versions(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.publish_visibility_checks
    ADD CONSTRAINT fk_publish_visibility_checks_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.publish_visibility_checks
    ADD CONSTRAINT fk_publish_visibility_checks_receipt_id_publish_receipts FOREIGN KEY (receipt_id) REFERENCES public.publish_receipts(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.question_candidates
    ADD CONSTRAINT fk_question_candidates_converted_question_id_questions FOREIGN KEY (converted_question_id) REFERENCES public.questions(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.question_candidates
    ADD CONSTRAINT fk_question_candidates_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.question_candidates
    ADD CONSTRAINT fk_question_candidates_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.question_candidates
    ADD CONSTRAINT fk_question_candidates_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.question_keywords
    ADD CONSTRAINT fk_question_keywords_keyword_id_keywords FOREIGN KEY (keyword_id) REFERENCES public.keywords(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.question_keywords
    ADD CONSTRAINT fk_question_keywords_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.question_keywords
    ADD CONSTRAINT fk_question_keywords_question_id_questions FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.question_version_keywords
    ADD CONSTRAINT fk_question_version_keywords_keyword_id_keywords FOREIGN KEY (keyword_id) REFERENCES public.keywords(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.question_version_keywords
    ADD CONSTRAINT fk_question_version_keywords_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.question_version_keywords
    ADD CONSTRAINT fk_question_version_keywords_question_version_id_questi_ed6d FOREIGN KEY (question_version_id) REFERENCES public.question_versions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT fk_question_versions_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT fk_question_versions_import_batch_id_import_batches FOREIGN KEY (import_batch_id) REFERENCES public.import_batches(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT fk_question_versions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT fk_question_versions_question_id_questions FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.questions
    ADD CONSTRAINT fk_questions_import_batch_id_import_batches FOREIGN KEY (import_batch_id) REFERENCES public.import_batches(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.questions
    ADD CONSTRAINT fk_questions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.report_shares
    ADD CONSTRAINT fk_report_shares_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.report_shares
    ADD CONSTRAINT fk_report_shares_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.report_shares
    ADD CONSTRAINT fk_report_shares_snapshot_id_monthly_report_snapshots FOREIGN KEY (snapshot_id) REFERENCES public.monthly_report_snapshots(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT fk_role_permissions_permission FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT fk_role_permissions_role FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.selling_points
    ADD CONSTRAINT fk_selling_points_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.selling_points
    ADD CONSTRAINT fk_selling_points_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.sentiment_labels
    ADD CONSTRAINT fk_sentiment_labels_citation_id_monitoring_citations FOREIGN KEY (citation_id) REFERENCES public.monitoring_citations(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.sentiment_labels
    ADD CONSTRAINT fk_sentiment_labels_labeled_by_users FOREIGN KEY (labeled_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.sentiment_labels
    ADD CONSTRAINT fk_sentiment_labels_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.site_modules
    ADD CONSTRAINT fk_site_modules_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.site_modules
    ADD CONSTRAINT fk_site_modules_site_id_site_sites FOREIGN KEY (site_id) REFERENCES public.site_sites(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.site_sites
    ADD CONSTRAINT fk_site_sites_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.source_domain_evidence
    ADD CONSTRAINT fk_source_domain_evidence_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.stat_snapshots
    ADD CONSTRAINT fk_stat_snapshots_captured_by_users FOREIGN KEY (captured_by) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.stat_snapshots
    ADD CONSTRAINT fk_stat_snapshots_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.stat_snapshots
    ADD CONSTRAINT fk_stat_snapshots_round_id_monitoring_rounds FOREIGN KEY (round_id) REFERENCES public.monitoring_rounds(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.traffic_events
    ADD CONSTRAINT fk_traffic_events_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY public.usage_events
    ADD CONSTRAINT fk_usage_events_actor_id_users FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.usage_events
    ADD CONSTRAINT fk_usage_events_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.usage_events
    ADD CONSTRAINT fk_usage_events_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;
