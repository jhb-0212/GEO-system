--
-- PostgreSQL database dump
--

-- Dumped from database version 16.15
-- Dumped by pg_dump version 16.15

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: ai_engine_entries; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: ai_engines; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);

--
-- Name: answer_fact_claims; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: answer_fact_claims_serial_no_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.answer_fact_claims_serial_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: answer_fact_claims_serial_no_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.answer_fact_claims_serial_no_seq OWNED BY public.answer_fact_claims.serial_no;

--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: audit_logs_serial_no_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_logs_serial_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: audit_logs_serial_no_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_logs_serial_no_seq OWNED BY public.audit_logs.serial_no;

--
-- Name: brand_profiles; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: budget_approvals; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: channel_aliases; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: channel_approvals; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: channels; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: citation_source_reviews; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: competitors; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: content_items; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_content_items_content_kind CHECK (((kind)::text = ANY ((ARRAY['master'::character varying, 'channel'::character varying])::text[]))),
    CONSTRAINT ck_content_items_content_links CHECK (((((kind)::text = 'master'::text) AND (parent_id IS NULL) AND (channel_id IS NULL)) OR (((kind)::text = 'channel'::text) AND (((status)::text = 'archived'::text) OR ((parent_id IS NOT NULL) AND (channel_id IS NOT NULL)))))),
    CONSTRAINT ck_content_items_content_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'pending_review'::character varying, 'approved'::character varying, 'rejected'::character varying, 'pending_publish'::character varying, 'published'::character varying, 'needs_attention'::character varying, 'archived'::character varying])::text[])))
);

--
-- Name: content_plans; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_content_plans_content_plan_status CHECK (((status)::text = ANY ((ARRAY['proposed'::character varying, 'scheduled'::character varying, 'in_production'::character varying, 'pending_review'::character varying, 'published'::character varying, 'cancelled'::character varying])::text[]))),
    CONSTRAINT ck_content_plans_plan_type CHECK (((plan_type)::text = ANY ((ARRAY['article'::character varying, 'video'::character varying])::text[])))
);

--
-- Name: content_reviews; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: content_version_citations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.content_version_citations (
    project_id uuid NOT NULL,
    version_id uuid NOT NULL,
    citation_id uuid NOT NULL,
    id uuid NOT NULL
);

--
-- Name: content_version_facts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.content_version_facts (
    project_id uuid NOT NULL,
    version_id uuid NOT NULL,
    fact_id uuid NOT NULL,
    fact_version_no integer NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: content_version_keywords; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.content_version_keywords (
    project_id uuid NOT NULL,
    version_id uuid NOT NULL,
    keyword_id uuid NOT NULL,
    id uuid NOT NULL
);

--
-- Name: content_version_questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.content_version_questions (
    project_id uuid NOT NULL,
    version_id uuid NOT NULL,
    question_id uuid NOT NULL,
    id uuid NOT NULL
);

--
-- Name: content_versions; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: correction_tasks; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: crawler_events; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: evidence_files; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: fact_versions; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: facts; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: faqs; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: import_batches; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: keywords; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: leads; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_leads_enrollment_status CHECK (((enrollment_status)::text = ANY ((ARRAY['unknown'::character varying, 'contacted'::character varying, 'enrolled'::character varying, 'lost'::character varying])::text[])))
);

--
-- Name: leads_serial_no_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.leads_serial_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: leads_serial_no_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.leads_serial_no_seq OWNED BY public.leads.serial_no;

--
-- Name: materials; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_materials_material_category CHECK (((category)::text = ANY ((ARRAY['image'::character varying, 'document'::character varying, 'case'::character varying])::text[])))
);

--
-- Name: media_quotes; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: metric_definitions; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: monitoring_brand_mentions; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: monitoring_citations; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: monitoring_competitor_mentions; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: monitoring_execution_attempts; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: monitoring_retest_plans; Type: TABLE; Schema: public; Owner: -
--

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
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: monitoring_rounds; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: monitoring_samples; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_monitoring_samples_answer_kind CHECK (((answer_kind)::text = ANY ((ARRAY['answer'::character varying, 'search_result'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_samples_ck_monitoring_samples_conversation_mode CHECK (((conversation_mode)::text = ANY ((ARRAY['stateless'::character varying, 'fresh'::character varying, 'manual'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_samples_failure_code CHECK (((failure_code)::text = ANY ((ARRAY['login_blocked'::character varying, 'timeout'::character varying, 'access_blocked'::character varying, 'captcha'::character varying, 'rate_limited'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_samples_review_result CHECK (((review_result)::text = ANY ((ARRAY['hit'::character varying, 'miss'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_samples_sample_sampling_mode CHECK (((sampling_mode)::text = ANY ((ARRAY['search_on'::character varying, 'search_off'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_samples_sample_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'hit'::character varying, 'miss'::character varying, 'no_answer_surface'::character varying, 'failed'::character varying, 'manual_review'::character varying])::text[])))
);

--
-- Name: monitoring_samples_serial_no_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.monitoring_samples_serial_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: monitoring_samples_serial_no_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.monitoring_samples_serial_no_seq OWNED BY public.monitoring_samples.serial_no;

--
-- Name: monitoring_source_profiles; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: monitoring_tasks; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: monitoring_tasks_serial_no_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.monitoring_tasks_serial_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: monitoring_tasks_serial_no_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.monitoring_tasks_serial_no_seq OWNED BY public.monitoring_tasks.serial_no;

--
-- Name: monthly_report_snapshots; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: oauth_authorization_states; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: oauth_connections; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: opportunities; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: outbox_events; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: page_approvals; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: permissions; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: project_members; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: projects; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_projects_priority_range CHECK (((priority >= 1) AND (priority <= 5))),
    CONSTRAINT ck_projects_project_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'paused'::character varying, 'archived'::character varying])::text[])))
);

--
-- Name: public_pages; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: publish_accounts; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: publish_attempts; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: publish_receipts; Type: TABLE; Schema: public; Owner: -
--

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
    page_approval_id uuid
);

--
-- Name: publish_tasks; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT ck_publish_tasks_publish_mode CHECK (((publish_mode)::text = ANY ((ARRAY['manual'::character varying, 'api'::character varying, 'authorized'::character varying])::text[]))),
    CONSTRAINT ck_publish_tasks_publish_task_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'publishing'::character varying, 'published'::character varying, 'unknown'::character varying, 'failed'::character varying, 'needs_review'::character varying, 'cancelled'::character varying])::text[])))
);

--
-- Name: publish_tasks_serial_no_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.publish_tasks_serial_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: publish_tasks_serial_no_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.publish_tasks_serial_no_seq OWNED BY public.publish_tasks.serial_no;

--
-- Name: publish_visibility_checks; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: question_keywords; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.question_keywords (
    project_id uuid NOT NULL,
    question_id uuid NOT NULL,
    keyword_id uuid NOT NULL,
    id uuid NOT NULL
);

--
-- Name: question_version_keywords; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.question_version_keywords (
    project_id uuid NOT NULL,
    question_version_id uuid NOT NULL,
    keyword_id uuid NOT NULL,
    id uuid NOT NULL
);

--
-- Name: question_versions; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: questions; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: role_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_permissions (
    id uuid NOT NULL,
    role_id uuid NOT NULL,
    permission_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    code character varying(32) NOT NULL,
    name character varying(64) NOT NULL,
    description text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_roles_role_code CHECK (((code)::text = ANY ((ARRAY['sys_admin'::character varying, 'project_admin'::character varying, 'editor'::character varying, 'reviewer'::character varying, 'viewer'::character varying, 'lead_ops'::character varying])::text[])))
);

--
-- Name: stat_snapshots; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: traffic_events; Type: TABLE; Schema: public; Owner: -
--

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
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

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
    token_version integer DEFAULT 0 NOT NULL
);

--
-- Name: answer_fact_claims serial_no; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_fact_claims ALTER COLUMN serial_no SET DEFAULT nextval('public.answer_fact_claims_serial_no_seq'::regclass);

--
-- Name: audit_logs serial_no; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN serial_no SET DEFAULT nextval('public.audit_logs_serial_no_seq'::regclass);

--
-- Name: leads serial_no; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leads ALTER COLUMN serial_no SET DEFAULT nextval('public.leads_serial_no_seq'::regclass);

--
-- Name: monitoring_samples serial_no; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_samples ALTER COLUMN serial_no SET DEFAULT nextval('public.monitoring_samples_serial_no_seq'::regclass);

--
-- Name: monitoring_tasks serial_no; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks ALTER COLUMN serial_no SET DEFAULT nextval('public.monitoring_tasks_serial_no_seq'::regclass);

--
-- Name: publish_tasks serial_no; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_tasks ALTER COLUMN serial_no SET DEFAULT nextval('public.publish_tasks_serial_no_seq'::regclass);

--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);

--
-- Name: ai_engine_entries pk_ai_engine_entries; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_engine_entries
    ADD CONSTRAINT pk_ai_engine_entries PRIMARY KEY (id);

--
-- Name: ai_engines pk_ai_engines; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_engines
    ADD CONSTRAINT pk_ai_engines PRIMARY KEY (id);

--
-- Name: answer_fact_claims pk_answer_fact_claims; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT pk_answer_fact_claims PRIMARY KEY (id);

--
-- Name: audit_logs pk_audit_logs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT pk_audit_logs PRIMARY KEY (id);

--
-- Name: brand_profiles pk_brand_profiles; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.brand_profiles
    ADD CONSTRAINT pk_brand_profiles PRIMARY KEY (id);

--
-- Name: budget_approvals pk_budget_approvals; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT pk_budget_approvals PRIMARY KEY (id);

--
-- Name: channel_aliases pk_channel_aliases; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_aliases
    ADD CONSTRAINT pk_channel_aliases PRIMARY KEY (id);

--
-- Name: channel_approvals pk_channel_approvals; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_approvals
    ADD CONSTRAINT pk_channel_approvals PRIMARY KEY (id);

--
-- Name: channels pk_channels; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channels
    ADD CONSTRAINT pk_channels PRIMARY KEY (id);

--
-- Name: citation_source_reviews pk_citation_source_reviews; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.citation_source_reviews
    ADD CONSTRAINT pk_citation_source_reviews PRIMARY KEY (id);

--
-- Name: competitors pk_competitors; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competitors
    ADD CONSTRAINT pk_competitors PRIMARY KEY (id);

--
-- Name: content_items pk_content_items; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT pk_content_items PRIMARY KEY (id);

--
-- Name: content_plans pk_content_plans; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_plans
    ADD CONSTRAINT pk_content_plans PRIMARY KEY (id);

--
-- Name: content_reviews pk_content_reviews; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_reviews
    ADD CONSTRAINT pk_content_reviews PRIMARY KEY (id);

--
-- Name: content_version_citations pk_content_version_citations; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT pk_content_version_citations PRIMARY KEY (id);

--
-- Name: content_version_facts pk_content_version_facts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT pk_content_version_facts PRIMARY KEY (id);

--
-- Name: content_version_keywords pk_content_version_keywords; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT pk_content_version_keywords PRIMARY KEY (id);

--
-- Name: content_version_questions pk_content_version_questions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT pk_content_version_questions PRIMARY KEY (id);

--
-- Name: content_versions pk_content_versions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT pk_content_versions PRIMARY KEY (id);

--
-- Name: correction_tasks pk_correction_tasks; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.correction_tasks
    ADD CONSTRAINT pk_correction_tasks PRIMARY KEY (id);

--
-- Name: crawler_events pk_crawler_events; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crawler_events
    ADD CONSTRAINT pk_crawler_events PRIMARY KEY (id);

--
-- Name: evidence_files pk_evidence_files; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence_files
    ADD CONSTRAINT pk_evidence_files PRIMARY KEY (id);

--
-- Name: fact_versions pk_fact_versions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_versions
    ADD CONSTRAINT pk_fact_versions PRIMARY KEY (id);

--
-- Name: facts pk_facts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT pk_facts PRIMARY KEY (id);

--
-- Name: faqs pk_faqs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.faqs
    ADD CONSTRAINT pk_faqs PRIMARY KEY (id);

--
-- Name: import_batches pk_import_batches; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_batches
    ADD CONSTRAINT pk_import_batches PRIMARY KEY (id);

--
-- Name: keywords pk_keywords; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.keywords
    ADD CONSTRAINT pk_keywords PRIMARY KEY (id);

--
-- Name: leads pk_leads; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leads
    ADD CONSTRAINT pk_leads PRIMARY KEY (id);

--
-- Name: materials pk_materials; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.materials
    ADD CONSTRAINT pk_materials PRIMARY KEY (id);

--
-- Name: media_quotes pk_media_quotes; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.media_quotes
    ADD CONSTRAINT pk_media_quotes PRIMARY KEY (id);

--
-- Name: metric_definitions pk_metric_definitions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metric_definitions
    ADD CONSTRAINT pk_metric_definitions PRIMARY KEY (id);

--
-- Name: monitoring_brand_mentions pk_monitoring_brand_mentions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_brand_mentions
    ADD CONSTRAINT pk_monitoring_brand_mentions PRIMARY KEY (id);

--
-- Name: monitoring_citations pk_monitoring_citations; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT pk_monitoring_citations PRIMARY KEY (id);

--
-- Name: monitoring_competitor_mentions pk_monitoring_competitor_mentions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_competitor_mentions
    ADD CONSTRAINT pk_monitoring_competitor_mentions PRIMARY KEY (id);

--
-- Name: monitoring_execution_attempts pk_monitoring_execution_attempts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_execution_attempts
    ADD CONSTRAINT pk_monitoring_execution_attempts PRIMARY KEY (id);

--
-- Name: monitoring_retest_plans pk_monitoring_retest_plans; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_retest_plans
    ADD CONSTRAINT pk_monitoring_retest_plans PRIMARY KEY (id);

--
-- Name: monitoring_rounds pk_monitoring_rounds; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT pk_monitoring_rounds PRIMARY KEY (id);

--
-- Name: monitoring_samples pk_monitoring_samples; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT pk_monitoring_samples PRIMARY KEY (id);

--
-- Name: monitoring_source_profiles pk_monitoring_source_profiles; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_source_profiles
    ADD CONSTRAINT pk_monitoring_source_profiles PRIMARY KEY (id);

--
-- Name: monitoring_tasks pk_monitoring_tasks; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT pk_monitoring_tasks PRIMARY KEY (id);

--
-- Name: monthly_report_snapshots pk_monthly_report_snapshots; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monthly_report_snapshots
    ADD CONSTRAINT pk_monthly_report_snapshots PRIMARY KEY (id);

--
-- Name: oauth_authorization_states pk_oauth_authorization_states; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_authorization_states
    ADD CONSTRAINT pk_oauth_authorization_states PRIMARY KEY (id);

--
-- Name: oauth_connections pk_oauth_connections; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_connections
    ADD CONSTRAINT pk_oauth_connections PRIMARY KEY (id);

--
-- Name: opportunities pk_opportunities; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT pk_opportunities PRIMARY KEY (id);

--
-- Name: outbox_events pk_outbox_events; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_events
    ADD CONSTRAINT pk_outbox_events PRIMARY KEY (id);

--
-- Name: page_approvals pk_page_approvals; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_approvals
    ADD CONSTRAINT pk_page_approvals PRIMARY KEY (id);

--
-- Name: permissions pk_permissions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT pk_permissions PRIMARY KEY (id);

--
-- Name: project_members pk_project_members; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT pk_project_members PRIMARY KEY (id);

--
-- Name: projects pk_projects; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT pk_projects PRIMARY KEY (id);

--
-- Name: public_pages pk_public_pages; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_pages
    ADD CONSTRAINT pk_public_pages PRIMARY KEY (id);

--
-- Name: publish_accounts pk_publish_accounts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_accounts
    ADD CONSTRAINT pk_publish_accounts PRIMARY KEY (id);

--
-- Name: publish_attempts pk_publish_attempts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_attempts
    ADD CONSTRAINT pk_publish_attempts PRIMARY KEY (id);

--
-- Name: publish_receipts pk_publish_receipts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT pk_publish_receipts PRIMARY KEY (id);

--
-- Name: publish_tasks pk_publish_tasks; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT pk_publish_tasks PRIMARY KEY (id);

--
-- Name: publish_visibility_checks pk_publish_visibility_checks; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_visibility_checks
    ADD CONSTRAINT pk_publish_visibility_checks PRIMARY KEY (id);

--
-- Name: question_keywords pk_question_keywords; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_keywords
    ADD CONSTRAINT pk_question_keywords PRIMARY KEY (id);

--
-- Name: question_version_keywords pk_question_version_keywords; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_version_keywords
    ADD CONSTRAINT pk_question_version_keywords PRIMARY KEY (id);

--
-- Name: question_versions pk_question_versions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT pk_question_versions PRIMARY KEY (id);

--
-- Name: questions pk_questions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questions
    ADD CONSTRAINT pk_questions PRIMARY KEY (id);

--
-- Name: role_permissions pk_role_permissions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT pk_role_permissions PRIMARY KEY (id);

--
-- Name: roles pk_roles; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT pk_roles PRIMARY KEY (id);

--
-- Name: stat_snapshots pk_stat_snapshots; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stat_snapshots
    ADD CONSTRAINT pk_stat_snapshots PRIMARY KEY (id);

--
-- Name: traffic_events pk_traffic_events; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.traffic_events
    ADD CONSTRAINT pk_traffic_events PRIMARY KEY (id);

--
-- Name: users pk_users; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT pk_users PRIMARY KEY (id);

--
-- Name: ai_engine_entries uq_ai_engine_entries_engine_type_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_engine_entries
    ADD CONSTRAINT uq_ai_engine_entries_engine_type_name UNIQUE (engine_id, entry_type, name);

--
-- Name: ai_engines uq_ai_engines_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_engines
    ADD CONSTRAINT uq_ai_engines_code UNIQUE (code);

--
-- Name: answer_fact_claims uq_answer_fact_claims_serial_no; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT uq_answer_fact_claims_serial_no UNIQUE (serial_no);

--
-- Name: audit_logs uq_audit_logs_serial_no; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT uq_audit_logs_serial_no UNIQUE (serial_no);

--
-- Name: brand_profiles uq_brand_profiles_project; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.brand_profiles
    ADD CONSTRAINT uq_brand_profiles_project UNIQUE (project_id);

--
-- Name: budget_approvals uq_budget_approvals_project_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT uq_budget_approvals_project_id_id UNIQUE (project_id, id);

--
-- Name: channel_aliases uq_channel_aliases_project_domain; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_aliases
    ADD CONSTRAINT uq_channel_aliases_project_domain UNIQUE (project_id, domain);

--
-- Name: channels uq_channels_project_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channels
    ADD CONSTRAINT uq_channels_project_code UNIQUE (project_id, code);

--
-- Name: citation_source_reviews uq_citation_source_reviews_project_domain; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.citation_source_reviews
    ADD CONSTRAINT uq_citation_source_reviews_project_domain UNIQUE (project_id, domain);

--
-- Name: competitors uq_competitors_project_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competitors
    ADD CONSTRAINT uq_competitors_project_name UNIQUE (project_id, name);

--
-- Name: content_version_citations uq_content_version_citations_version_citation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT uq_content_version_citations_version_citation UNIQUE (version_id, citation_id);

--
-- Name: content_version_facts uq_content_version_facts_version_fact; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT uq_content_version_facts_version_fact UNIQUE (version_id, fact_id);

--
-- Name: content_version_keywords uq_content_version_keywords_version_keyword; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT uq_content_version_keywords_version_keyword UNIQUE (version_id, keyword_id);

--
-- Name: content_version_questions uq_content_version_questions_version_question; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT uq_content_version_questions_version_question UNIQUE (version_id, question_id);

--
-- Name: content_versions uq_content_versions_item_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT uq_content_versions_item_version UNIQUE (item_id, version_no);

--
-- Name: content_versions uq_content_versions_project_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT uq_content_versions_project_id_id UNIQUE (project_id, id);

--
-- Name: fact_versions uq_fact_versions_fact_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_versions
    ADD CONSTRAINT uq_fact_versions_fact_version UNIQUE (fact_id, version_no);

--
-- Name: facts uq_facts_project_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT uq_facts_project_id_id UNIQUE (project_id, id);

--
-- Name: facts uq_facts_project_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT uq_facts_project_type_key UNIQUE (project_id, fact_type, fact_key);

--
-- Name: keywords uq_keywords_project_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.keywords
    ADD CONSTRAINT uq_keywords_project_id_id UNIQUE (project_id, id);

--
-- Name: keywords uq_keywords_project_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.keywords
    ADD CONSTRAINT uq_keywords_project_name UNIQUE (project_id, name);

--
-- Name: leads uq_leads_serial_no; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leads
    ADD CONSTRAINT uq_leads_serial_no UNIQUE (serial_no);

--
-- Name: media_quotes uq_media_quotes_project_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.media_quotes
    ADD CONSTRAINT uq_media_quotes_project_id_id UNIQUE (project_id, id);

--
-- Name: metric_definitions uq_metric_definitions_project_code_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metric_definitions
    ADD CONSTRAINT uq_metric_definitions_project_code_version UNIQUE (project_id, code, rule_version);

--
-- Name: monitoring_execution_attempts uq_monitoring_attempts_task_attempt; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_execution_attempts
    ADD CONSTRAINT uq_monitoring_attempts_task_attempt UNIQUE (task_id, attempt_no);

--
-- Name: monitoring_brand_mentions uq_monitoring_brand_mentions_sample_term_offset; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_brand_mentions
    ADD CONSTRAINT uq_monitoring_brand_mentions_sample_term_offset UNIQUE (project_id, sample_id, term, offset_start);

--
-- Name: monitoring_citations uq_monitoring_citations_project_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT uq_monitoring_citations_project_id_id UNIQUE (project_id, id);

--
-- Name: monitoring_competitor_mentions uq_monitoring_competitor_mentions_sample_competitor; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_competitor_mentions
    ADD CONSTRAINT uq_monitoring_competitor_mentions_sample_competitor UNIQUE (sample_id, competitor_id);

--
-- Name: monitoring_retest_plans uq_monitoring_retest_plans_project_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_retest_plans
    ADD CONSTRAINT uq_monitoring_retest_plans_project_name UNIQUE (project_id, name);

--
-- Name: monitoring_rounds uq_monitoring_rounds_plan_slot; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT uq_monitoring_rounds_plan_slot UNIQUE (retest_plan_id, scheduled_for);

--
-- Name: monitoring_rounds uq_monitoring_rounds_project_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT uq_monitoring_rounds_project_id_id UNIQUE (project_id, id);

--
-- Name: monitoring_rounds uq_monitoring_rounds_project_seq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT uq_monitoring_rounds_project_seq UNIQUE (project_id, seq);

--
-- Name: monitoring_samples uq_monitoring_samples_project_conversation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT uq_monitoring_samples_project_conversation UNIQUE (project_id, conversation_id);

--
-- Name: monitoring_samples uq_monitoring_samples_project_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT uq_monitoring_samples_project_id_id UNIQUE (project_id, id);

--
-- Name: monitoring_samples uq_monitoring_samples_serial_no; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT uq_monitoring_samples_serial_no UNIQUE (serial_no);

--
-- Name: monitoring_samples uq_monitoring_samples_task_attempt; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT uq_monitoring_samples_task_attempt UNIQUE (task_id, attempt_no);

--
-- Name: monitoring_source_profiles uq_monitoring_source_profiles_project_domain; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_source_profiles
    ADD CONSTRAINT uq_monitoring_source_profiles_project_domain UNIQUE (project_id, domain);

--
-- Name: monitoring_tasks uq_monitoring_tasks_project_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT uq_monitoring_tasks_project_id_id UNIQUE (project_id, id);

--
-- Name: monitoring_tasks uq_monitoring_tasks_round_question_entry_sampling; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT uq_monitoring_tasks_round_question_entry_sampling UNIQUE (round_id, question_version_id, engine_entry_id, sampling_no);

--
-- Name: monitoring_tasks uq_monitoring_tasks_serial_no; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT uq_monitoring_tasks_serial_no UNIQUE (serial_no);

--
-- Name: monthly_report_snapshots uq_monthly_report_snapshots_project_month; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monthly_report_snapshots
    ADD CONSTRAINT uq_monthly_report_snapshots_project_month UNIQUE (project_id, month);

--
-- Name: oauth_authorization_states uq_oauth_authorization_states_state_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_authorization_states
    ADD CONSTRAINT uq_oauth_authorization_states_state_hash UNIQUE (state_hash);

--
-- Name: oauth_connections uq_oauth_connections_project_provider_external; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_connections
    ADD CONSTRAINT uq_oauth_connections_project_provider_external UNIQUE (project_id, provider_code, external_account_id);

--
-- Name: page_approvals uq_page_approvals_project_channel_url; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_approvals
    ADD CONSTRAINT uq_page_approvals_project_channel_url UNIQUE (project_id, channel_id, url_key);

--
-- Name: permissions uq_permissions_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT uq_permissions_code UNIQUE (code);

--
-- Name: project_members uq_project_members_project_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT uq_project_members_project_user UNIQUE (project_id, user_id);

--
-- Name: projects uq_projects_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT uq_projects_code UNIQUE (code);

--
-- Name: public_pages uq_public_pages_project_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_pages
    ADD CONSTRAINT uq_public_pages_project_slug UNIQUE (project_id, slug);

--
-- Name: publish_accounts uq_publish_accounts_oauth_connection; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_accounts
    ADD CONSTRAINT uq_publish_accounts_oauth_connection UNIQUE (oauth_connection_id);

--
-- Name: publish_accounts uq_publish_accounts_project_channel_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_accounts
    ADD CONSTRAINT uq_publish_accounts_project_channel_name UNIQUE (project_id, channel_id, account_name);

--
-- Name: publish_attempts uq_publish_attempts_task_attempt; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_attempts
    ADD CONSTRAINT uq_publish_attempts_task_attempt UNIQUE (task_id, attempt_no);

--
-- Name: publish_receipts uq_publish_receipts_project_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT uq_publish_receipts_project_id_id UNIQUE (project_id, id);

--
-- Name: publish_tasks uq_publish_tasks_idempotency; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT uq_publish_tasks_idempotency UNIQUE (account_id, channel_id, version_id, task_key);

--
-- Name: publish_tasks uq_publish_tasks_idempotency_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT uq_publish_tasks_idempotency_key UNIQUE (idempotency_key);

--
-- Name: publish_tasks uq_publish_tasks_serial_no; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT uq_publish_tasks_serial_no UNIQUE (serial_no);

--
-- Name: question_keywords uq_question_keywords_question_keyword; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_keywords
    ADD CONSTRAINT uq_question_keywords_question_keyword UNIQUE (question_id, keyword_id);

--
-- Name: question_version_keywords uq_question_version_keywords_version_keyword; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_version_keywords
    ADD CONSTRAINT uq_question_version_keywords_version_keyword UNIQUE (question_version_id, keyword_id);

--
-- Name: question_versions uq_question_versions_project_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT uq_question_versions_project_id_id UNIQUE (project_id, id);

--
-- Name: question_versions uq_question_versions_question_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT uq_question_versions_question_version UNIQUE (question_id, version_no);

--
-- Name: questions uq_questions_project_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questions
    ADD CONSTRAINT uq_questions_project_code UNIQUE (project_id, code);

--
-- Name: questions uq_questions_project_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questions
    ADD CONSTRAINT uq_questions_project_id_id UNIQUE (project_id, id);

--
-- Name: role_permissions uq_role_permissions_role_permission; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT uq_role_permissions_role_permission UNIQUE (role_id, permission_id);

--
-- Name: roles uq_roles_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT uq_roles_code UNIQUE (code);

--
-- Name: stat_snapshots uq_stat_snapshots_project_round; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stat_snapshots
    ADD CONSTRAINT uq_stat_snapshots_project_round UNIQUE (project_id, round_id);

--
-- Name: users uq_users_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_email UNIQUE (email);

--
-- Name: users uq_users_username; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_username UNIQUE (username);

--
-- Name: ix_ai_engine_entries_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ai_engine_entries_active ON public.ai_engine_entries USING btree (engine_id, is_active);

--
-- Name: ix_answer_fact_claims_project_sample; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_answer_fact_claims_project_sample ON public.answer_fact_claims USING btree (project_id, sample_id);

--
-- Name: ix_answer_fact_claims_project_verdict; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_answer_fact_claims_project_verdict ON public.answer_fact_claims USING btree (project_id, verdict);

--
-- Name: ix_audit_logs_project_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_project_created ON public.audit_logs USING btree (project_id, created_at);

--
-- Name: ix_audit_logs_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_target ON public.audit_logs USING btree (target_type, target_id);

--
-- Name: ix_brand_profiles_project_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_brand_profiles_project_active ON public.brand_profiles USING btree (project_id, is_active);

--
-- Name: ix_budget_approvals_media_quote; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_budget_approvals_media_quote ON public.budget_approvals USING btree (media_quote_id);

--
-- Name: ix_budget_approvals_project_status_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_budget_approvals_project_status_category ON public.budget_approvals USING btree (project_id, status, category);

--
-- Name: ix_channel_aliases_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_channel_aliases_channel ON public.channel_aliases USING btree (channel_id);

--
-- Name: ix_channel_approvals_project_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_channel_approvals_project_channel ON public.channel_approvals USING btree (project_id, channel_id);

--
-- Name: ix_channels_project_category_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_channels_project_category_status ON public.channels USING btree (project_id, category, status);

--
-- Name: ix_citation_source_reviews_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_citation_source_reviews_project_status ON public.citation_source_reviews USING btree (project_id, status);

--
-- Name: ix_competitors_project_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_competitors_project_active ON public.competitors USING btree (project_id, is_active);

--
-- Name: ix_content_items_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_content_items_channel ON public.content_items USING btree (channel_id);

--
-- Name: ix_content_items_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_content_items_parent ON public.content_items USING btree (parent_id);

--
-- Name: ix_content_items_project_kind_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_content_items_project_kind_status ON public.content_items USING btree (project_id, kind, status);

--
-- Name: ix_content_plans_project_status_scheduled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_content_plans_project_status_scheduled ON public.content_plans USING btree (project_id, status, scheduled_at);

--
-- Name: ix_content_reviews_project_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_content_reviews_project_version ON public.content_reviews USING btree (project_id, version_id);

--
-- Name: ix_content_reviews_reviewer; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_content_reviews_reviewer ON public.content_reviews USING btree (reviewer_id);

--
-- Name: ix_content_versions_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_content_versions_project_status ON public.content_versions USING btree (project_id, status);

--
-- Name: ix_correction_tasks_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_correction_tasks_project_status ON public.correction_tasks USING btree (project_id, status);

--
-- Name: ix_crawler_events_project_bot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_crawler_events_project_bot ON public.crawler_events USING btree (project_id, verified_bot);

--
-- Name: ix_crawler_events_project_occurred; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_crawler_events_project_occurred ON public.crawler_events USING btree (project_id, occurred_at);

--
-- Name: ix_evidence_files_project_sample; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evidence_files_project_sample ON public.evidence_files USING btree (project_id, sample_id);

--
-- Name: ix_fact_versions_project_fact; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_fact_versions_project_fact ON public.fact_versions USING btree (project_id, fact_id);

--
-- Name: ix_facts_project_type_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_facts_project_type_status ON public.facts USING btree (project_id, fact_type, approval_status);

--
-- Name: ix_faqs_project_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_faqs_project_category ON public.faqs USING btree (project_id, category);

--
-- Name: ix_faqs_project_deleted; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_faqs_project_deleted ON public.faqs USING btree (project_id, deleted_at);

--
-- Name: ix_faqs_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_faqs_project_status ON public.faqs USING btree (project_id, status);

--
-- Name: ix_import_batches_project_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_batches_project_started ON public.import_batches USING btree (project_id, started_at);

--
-- Name: ix_keywords_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_keywords_project_status ON public.keywords USING btree (project_id, is_active);

--
-- Name: ix_leads_project_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_leads_project_created ON public.leads USING btree (project_id, created_at);

--
-- Name: ix_leads_project_enrollment; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_leads_project_enrollment ON public.leads USING btree (project_id, enrollment_status);

--
-- Name: ix_leads_project_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_leads_project_session ON public.leads USING btree (project_id, session_id);

--
-- Name: ix_leads_project_source_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_leads_project_source_channel ON public.leads USING btree (project_id, source_channel_id);

--
-- Name: ix_leads_project_source_engine; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_leads_project_source_engine ON public.leads USING btree (project_id, source_engine_id);

--
-- Name: ix_leads_project_source_question; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_leads_project_source_question ON public.leads USING btree (project_id, source_question_id);

--
-- Name: ix_materials_project_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_materials_project_category ON public.materials USING btree (project_id, category);

--
-- Name: ix_media_quotes_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_media_quotes_project_status ON public.media_quotes USING btree (project_id, status);

--
-- Name: ix_monitoring_attempts_project_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_attempts_project_task ON public.monitoring_execution_attempts USING btree (project_id, task_id);

--
-- Name: ix_monitoring_attempts_status_lease; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_attempts_status_lease ON public.monitoring_execution_attempts USING btree (status, lease_expires_at);

--
-- Name: ix_monitoring_brand_mentions_project_sample; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_brand_mentions_project_sample ON public.monitoring_brand_mentions USING btree (project_id, sample_id);

--
-- Name: ix_monitoring_citations_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_citations_channel ON public.monitoring_citations USING btree (channel_id);

--
-- Name: ix_monitoring_citations_project_competitor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_citations_project_competitor ON public.monitoring_citations USING btree (project_id, competitor_id);

--
-- Name: ix_monitoring_citations_project_domain_review; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_citations_project_domain_review ON public.monitoring_citations USING btree (project_id, domain, review_status);

--
-- Name: ix_monitoring_citations_project_page_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_citations_project_page_type ON public.monitoring_citations USING btree (project_id, page_type);

--
-- Name: ix_monitoring_citations_project_sample; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_citations_project_sample ON public.monitoring_citations USING btree (project_id, sample_id);

--
-- Name: ix_monitoring_citations_project_source_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_citations_project_source_category ON public.monitoring_citations USING btree (project_id, source_category);

--
-- Name: ix_monitoring_citations_project_usage_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_citations_project_usage_domain ON public.monitoring_citations USING btree (project_id, citation_usage, domain);

--
-- Name: ix_monitoring_citations_trace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_citations_trace_id ON public.monitoring_citations USING btree (trace_id);

--
-- Name: ix_monitoring_competitor_mentions_project_competitor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_competitor_mentions_project_competitor ON public.monitoring_competitor_mentions USING btree (project_id, competitor_id);

--
-- Name: ix_monitoring_competitor_mentions_project_sample; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_competitor_mentions_project_sample ON public.monitoring_competitor_mentions USING btree (project_id, sample_id);

--
-- Name: ix_monitoring_retest_plans_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_retest_plans_due ON public.monitoring_retest_plans USING btree (next_run_at, enabled);

--
-- Name: ix_monitoring_retest_plans_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_retest_plans_project ON public.monitoring_retest_plans USING btree (project_id);

--
-- Name: ix_monitoring_rounds_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_rounds_project_status ON public.monitoring_rounds USING btree (project_id, status);

--
-- Name: ix_monitoring_rounds_retest_plan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_rounds_retest_plan ON public.monitoring_rounds USING btree (retest_plan_id, scheduled_for);

--
-- Name: ix_monitoring_samples_project_country_sampled_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_samples_project_country_sampled_at ON public.monitoring_samples USING btree (project_id, country_code, sampled_at);

--
-- Name: ix_monitoring_samples_project_engine_model_sampled_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_samples_project_engine_model_sampled_at ON public.monitoring_samples USING btree (project_id, engine_model, sampled_at);

--
-- Name: ix_monitoring_samples_project_sampled_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_samples_project_sampled_at ON public.monitoring_samples USING btree (project_id, sampled_at);

--
-- Name: ix_monitoring_samples_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_samples_project_status ON public.monitoring_samples USING btree (project_id, status);

--
-- Name: ix_monitoring_samples_task_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_samples_task_status ON public.monitoring_samples USING btree (task_id, status);

--
-- Name: ix_monitoring_samples_trace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_samples_trace_id ON public.monitoring_samples USING btree (trace_id);

--
-- Name: ix_monitoring_source_profiles_project_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_source_profiles_project_domain ON public.monitoring_source_profiles USING btree (project_id, domain);

--
-- Name: ix_monitoring_tasks_project_round_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_tasks_project_round_status ON public.monitoring_tasks USING btree (project_id, round_id, status);

--
-- Name: ix_monitoring_tasks_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_tasks_project_status ON public.monitoring_tasks USING btree (project_id, status);

--
-- Name: ix_monitoring_tasks_round; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_tasks_round ON public.monitoring_tasks USING btree (round_id);

--
-- Name: ix_monitoring_tasks_trace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_tasks_trace_id ON public.monitoring_tasks USING btree (trace_id);

--
-- Name: ix_monthly_report_snapshots_project_captured_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monthly_report_snapshots_project_captured_at ON public.monthly_report_snapshots USING btree (project_id, captured_at);

--
-- Name: ix_oauth_authorization_states_expiry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oauth_authorization_states_expiry ON public.oauth_authorization_states USING btree (expires_at);

--
-- Name: ix_oauth_connections_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oauth_connections_channel ON public.oauth_connections USING btree (channel_id);

--
-- Name: ix_oauth_connections_project_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oauth_connections_project_provider ON public.oauth_connections USING btree (project_id, provider_code);

--
-- Name: ix_opportunities_project_status_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_opportunities_project_status_score ON public.opportunities USING btree (project_id, status, priority_score);

--
-- Name: ix_outbox_events_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbox_events_project_id ON public.outbox_events USING btree (project_id);

--
-- Name: ix_outbox_events_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbox_events_status_created ON public.outbox_events USING btree (status, created_at);

--
-- Name: ix_page_approvals_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_page_approvals_channel ON public.page_approvals USING btree (channel_id);

--
-- Name: ix_page_approvals_project_page_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_page_approvals_project_page_type ON public.page_approvals USING btree (project_id, page_type);

--
-- Name: ix_page_approvals_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_page_approvals_project_status ON public.page_approvals USING btree (project_id, status);

--
-- Name: ix_project_members_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_members_project_id ON public.project_members USING btree (project_id);

--
-- Name: ix_project_members_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_members_user ON public.project_members USING btree (user_id, is_active);

--
-- Name: ix_public_pages_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_public_pages_project_status ON public.public_pages USING btree (project_id, publish_status);

--
-- Name: ix_publish_accounts_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_publish_accounts_project ON public.publish_accounts USING btree (project_id);

--
-- Name: ix_publish_attempts_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_publish_attempts_project ON public.publish_attempts USING btree (project_id);

--
-- Name: ix_publish_receipts_budget; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_publish_receipts_budget ON public.publish_receipts USING btree (budget_approval_id);

--
-- Name: ix_publish_receipts_project_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_publish_receipts_project_task ON public.publish_receipts USING btree (project_id, task_id);

--
-- Name: ix_publish_tasks_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_publish_tasks_project_status ON public.publish_tasks USING btree (project_id, status);

--
-- Name: ix_publish_tasks_scheduled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_publish_tasks_scheduled ON public.publish_tasks USING btree (project_id, scheduled_at);

--
-- Name: ix_publish_tasks_trace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_publish_tasks_trace_id ON public.publish_tasks USING btree (trace_id);

--
-- Name: ix_publish_visibility_checks_project_checked; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_publish_visibility_checks_project_checked ON public.publish_visibility_checks USING btree (project_id, checked_at);

--
-- Name: ix_publish_visibility_checks_receipt; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_publish_visibility_checks_receipt ON public.publish_visibility_checks USING btree (receipt_id);

--
-- Name: ix_question_keywords_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_keywords_project ON public.question_keywords USING btree (project_id);

--
-- Name: ix_question_version_keywords_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_version_keywords_project ON public.question_version_keywords USING btree (project_id);

--
-- Name: ix_question_version_keywords_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_version_keywords_version ON public.question_version_keywords USING btree (question_version_id);

--
-- Name: ix_question_versions_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_question_versions_project ON public.question_versions USING btree (project_id);

--
-- Name: ix_questions_project_type_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_questions_project_type_status ON public.questions USING btree (project_id, question_type, status);

--
-- Name: ix_role_permissions_permission; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_permissions_permission ON public.role_permissions USING btree (permission_id);

--
-- Name: ix_role_permissions_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_permissions_role ON public.role_permissions USING btree (role_id);

--
-- Name: ix_stat_snapshots_project_captured_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_stat_snapshots_project_captured_at ON public.stat_snapshots USING btree (project_id, captured_at);

--
-- Name: ix_traffic_events_project_occurred; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_traffic_events_project_occurred ON public.traffic_events USING btree (project_id, occurred_at);

--
-- Name: ix_traffic_events_project_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_traffic_events_project_session ON public.traffic_events USING btree (project_id, visitor_session_id);

--
-- Name: uq_channels_project_primary_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_channels_project_primary_domain ON public.channels USING btree (project_id, primary_domain) WHERE (primary_domain IS NOT NULL);

--
-- Name: uq_monitoring_rounds_project_baseline; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_monitoring_rounds_project_baseline ON public.monitoring_rounds USING btree (project_id) WHERE (is_baseline IS TRUE);

--
-- Name: ai_engine_entries fk_ai_engine_entries_engine_id_ai_engines; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_engine_entries
    ADD CONSTRAINT fk_ai_engine_entries_engine_id_ai_engines FOREIGN KEY (engine_id) REFERENCES public.ai_engines(id) ON DELETE CASCADE;

--
-- Name: answer_fact_claims fk_answer_fact_claims_citation_id_monitoring_citations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_citation_id_monitoring_citations FOREIGN KEY (citation_id) REFERENCES public.monitoring_citations(id) ON DELETE SET NULL;

--
-- Name: answer_fact_claims fk_answer_fact_claims_correction; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_correction FOREIGN KEY (correction_task_id) REFERENCES public.correction_tasks(id) ON DELETE SET NULL;

--
-- Name: answer_fact_claims fk_answer_fact_claims_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: answer_fact_claims fk_answer_fact_claims_fact_id_facts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_fact_id_facts FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE SET NULL;

--
-- Name: answer_fact_claims fk_answer_fact_claims_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: answer_fact_claims fk_answer_fact_claims_reviewed_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: answer_fact_claims fk_answer_fact_claims_sample_id_monitoring_samples; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.answer_fact_claims
    ADD CONSTRAINT fk_answer_fact_claims_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE CASCADE;

--
-- Name: audit_logs fk_audit_logs_actor_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT fk_audit_logs_actor_id_users FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: audit_logs fk_audit_logs_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT fk_audit_logs_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;

--
-- Name: brand_profiles fk_brand_profiles_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.brand_profiles
    ADD CONSTRAINT fk_brand_profiles_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: budget_approvals fk_budget_approvals_approved_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT fk_budget_approvals_approved_by_users FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: budget_approvals fk_budget_approvals_media_quote; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT fk_budget_approvals_media_quote FOREIGN KEY (media_quote_id) REFERENCES public.media_quotes(id) ON DELETE RESTRICT;

--
-- Name: budget_approvals fk_budget_approvals_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT fk_budget_approvals_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: budget_approvals fk_budget_approvals_project_media_quote; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT fk_budget_approvals_project_media_quote FOREIGN KEY (project_id, media_quote_id) REFERENCES public.media_quotes(project_id, id) ON DELETE RESTRICT;

--
-- Name: budget_approvals fk_budget_approvals_requested_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_approvals
    ADD CONSTRAINT fk_budget_approvals_requested_by_users FOREIGN KEY (requested_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: channel_aliases fk_channel_aliases_channel_id_channels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_aliases
    ADD CONSTRAINT fk_channel_aliases_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE CASCADE;

--
-- Name: channel_aliases fk_channel_aliases_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_aliases
    ADD CONSTRAINT fk_channel_aliases_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: channel_approvals fk_channel_approvals_channel_id_channels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_approvals
    ADD CONSTRAINT fk_channel_approvals_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE CASCADE;

--
-- Name: channel_approvals fk_channel_approvals_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_approvals
    ADD CONSTRAINT fk_channel_approvals_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: channel_approvals fk_channel_approvals_reviewed_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_approvals
    ADD CONSTRAINT fk_channel_approvals_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: channel_approvals fk_channel_approvals_submitted_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_approvals
    ADD CONSTRAINT fk_channel_approvals_submitted_by_users FOREIGN KEY (submitted_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: channels fk_channels_import_batch_id_import_batches; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channels
    ADD CONSTRAINT fk_channels_import_batch_id_import_batches FOREIGN KEY (import_batch_id) REFERENCES public.import_batches(id) ON DELETE SET NULL;

--
-- Name: channels fk_channels_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channels
    ADD CONSTRAINT fk_channels_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: channels fk_channels_reviewed_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channels
    ADD CONSTRAINT fk_channels_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: channels fk_channels_submitted_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channels
    ADD CONSTRAINT fk_channels_submitted_by_users FOREIGN KEY (submitted_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: citation_source_reviews fk_citation_source_reviews_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.citation_source_reviews
    ADD CONSTRAINT fk_citation_source_reviews_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: citation_source_reviews fk_citation_source_reviews_reviewed_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.citation_source_reviews
    ADD CONSTRAINT fk_citation_source_reviews_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: competitors fk_competitors_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competitors
    ADD CONSTRAINT fk_competitors_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: content_items fk_content_items_channel_id_channels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT fk_content_items_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;

--
-- Name: content_items fk_content_items_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT fk_content_items_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: content_items fk_content_items_current_version; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT fk_content_items_current_version FOREIGN KEY (current_version_id) REFERENCES public.content_versions(id) ON DELETE SET NULL;

--
-- Name: content_items fk_content_items_import_batch_id_import_batches; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT fk_content_items_import_batch_id_import_batches FOREIGN KEY (import_batch_id) REFERENCES public.import_batches(id) ON DELETE SET NULL;

--
-- Name: content_items fk_content_items_parent_id_content_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT fk_content_items_parent_id_content_items FOREIGN KEY (parent_id) REFERENCES public.content_items(id) ON DELETE RESTRICT;

--
-- Name: content_items fk_content_items_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_items
    ADD CONSTRAINT fk_content_items_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: content_plans fk_content_plans_channel_id_channels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_plans
    ADD CONSTRAINT fk_content_plans_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;

--
-- Name: content_plans fk_content_plans_content_item_id_content_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_plans
    ADD CONSTRAINT fk_content_plans_content_item_id_content_items FOREIGN KEY (content_item_id) REFERENCES public.content_items(id) ON DELETE SET NULL;

--
-- Name: content_plans fk_content_plans_owner_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_plans
    ADD CONSTRAINT fk_content_plans_owner_id_users FOREIGN KEY (owner_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: content_plans fk_content_plans_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_plans
    ADD CONSTRAINT fk_content_plans_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: content_plans fk_content_plans_site_page_id_public_pages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_plans
    ADD CONSTRAINT fk_content_plans_site_page_id_public_pages FOREIGN KEY (site_page_id) REFERENCES public.public_pages(id) ON DELETE SET NULL;

--
-- Name: content_reviews fk_content_reviews_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_reviews
    ADD CONSTRAINT fk_content_reviews_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: content_reviews fk_content_reviews_reviewer_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_reviews
    ADD CONSTRAINT fk_content_reviews_reviewer_id_users FOREIGN KEY (reviewer_id) REFERENCES public.users(id) ON DELETE RESTRICT;

--
-- Name: content_reviews fk_content_reviews_version_id_content_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_reviews
    ADD CONSTRAINT fk_content_reviews_version_id_content_versions FOREIGN KEY (version_id) REFERENCES public.content_versions(id) ON DELETE CASCADE;

--
-- Name: content_version_citations fk_content_version_citations_citation_id_monitoring_citations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT fk_content_version_citations_citation_id_monitoring_citations FOREIGN KEY (citation_id) REFERENCES public.monitoring_citations(id) ON DELETE CASCADE;

--
-- Name: content_version_citations fk_content_version_citations_project_citation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT fk_content_version_citations_project_citation FOREIGN KEY (project_id, citation_id) REFERENCES public.monitoring_citations(project_id, id) ON DELETE CASCADE;

--
-- Name: content_version_citations fk_content_version_citations_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT fk_content_version_citations_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: content_version_citations fk_content_version_citations_project_version; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT fk_content_version_citations_project_version FOREIGN KEY (project_id, version_id) REFERENCES public.content_versions(project_id, id) ON DELETE CASCADE;

--
-- Name: content_version_citations fk_content_version_citations_version_id_content_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT fk_content_version_citations_version_id_content_versions FOREIGN KEY (version_id) REFERENCES public.content_versions(id) ON DELETE CASCADE;

--
-- Name: content_version_facts fk_content_version_facts_fact_id_facts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT fk_content_version_facts_fact_id_facts FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE CASCADE;

--
-- Name: content_version_facts fk_content_version_facts_project_fact; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT fk_content_version_facts_project_fact FOREIGN KEY (project_id, fact_id) REFERENCES public.facts(project_id, id) ON DELETE CASCADE;

--
-- Name: content_version_facts fk_content_version_facts_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT fk_content_version_facts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: content_version_facts fk_content_version_facts_project_version; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT fk_content_version_facts_project_version FOREIGN KEY (project_id, version_id) REFERENCES public.content_versions(project_id, id) ON DELETE CASCADE;

--
-- Name: content_version_facts fk_content_version_facts_version_id_content_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_facts
    ADD CONSTRAINT fk_content_version_facts_version_id_content_versions FOREIGN KEY (version_id) REFERENCES public.content_versions(id) ON DELETE CASCADE;

--
-- Name: content_version_keywords fk_content_version_keywords_keyword_id_keywords; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT fk_content_version_keywords_keyword_id_keywords FOREIGN KEY (keyword_id) REFERENCES public.keywords(id) ON DELETE CASCADE;

--
-- Name: content_version_keywords fk_content_version_keywords_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT fk_content_version_keywords_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: content_version_keywords fk_content_version_keywords_project_keyword; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT fk_content_version_keywords_project_keyword FOREIGN KEY (project_id, keyword_id) REFERENCES public.keywords(project_id, id) ON DELETE CASCADE;

--
-- Name: content_version_keywords fk_content_version_keywords_project_version; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT fk_content_version_keywords_project_version FOREIGN KEY (project_id, version_id) REFERENCES public.content_versions(project_id, id) ON DELETE CASCADE;

--
-- Name: content_version_keywords fk_content_version_keywords_version_id_content_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_keywords
    ADD CONSTRAINT fk_content_version_keywords_version_id_content_versions FOREIGN KEY (version_id) REFERENCES public.content_versions(id) ON DELETE CASCADE;

--
-- Name: content_version_questions fk_content_version_questions_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT fk_content_version_questions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: content_version_questions fk_content_version_questions_project_question; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT fk_content_version_questions_project_question FOREIGN KEY (project_id, question_id) REFERENCES public.questions(project_id, id) ON DELETE CASCADE;

--
-- Name: content_version_questions fk_content_version_questions_project_version; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT fk_content_version_questions_project_version FOREIGN KEY (project_id, version_id) REFERENCES public.content_versions(project_id, id) ON DELETE CASCADE;

--
-- Name: content_version_questions fk_content_version_questions_question_id_questions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT fk_content_version_questions_question_id_questions FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE CASCADE;

--
-- Name: content_version_questions fk_content_version_questions_version_id_content_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_questions
    ADD CONSTRAINT fk_content_version_questions_version_id_content_versions FOREIGN KEY (version_id) REFERENCES public.content_versions(id) ON DELETE CASCADE;

--
-- Name: content_versions fk_content_versions_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT fk_content_versions_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: content_versions fk_content_versions_import_batch_id_import_batches; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT fk_content_versions_import_batch_id_import_batches FOREIGN KEY (import_batch_id) REFERENCES public.import_batches(id) ON DELETE SET NULL;

--
-- Name: content_versions fk_content_versions_item_id_content_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT fk_content_versions_item_id_content_items FOREIGN KEY (item_id) REFERENCES public.content_items(id) ON DELETE CASCADE;

--
-- Name: content_versions fk_content_versions_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT fk_content_versions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: content_versions fk_content_versions_submitted_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_versions
    ADD CONSTRAINT fk_content_versions_submitted_by_users FOREIGN KEY (submitted_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: correction_tasks fk_correction_tasks_claim; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.correction_tasks
    ADD CONSTRAINT fk_correction_tasks_claim FOREIGN KEY (claim_id) REFERENCES public.answer_fact_claims(id) ON DELETE SET NULL;

--
-- Name: correction_tasks fk_correction_tasks_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.correction_tasks
    ADD CONSTRAINT fk_correction_tasks_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: correction_tasks fk_correction_tasks_fact_id_facts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.correction_tasks
    ADD CONSTRAINT fk_correction_tasks_fact_id_facts FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE SET NULL;

--
-- Name: correction_tasks fk_correction_tasks_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.correction_tasks
    ADD CONSTRAINT fk_correction_tasks_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: crawler_events fk_crawler_events_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crawler_events
    ADD CONSTRAINT fk_crawler_events_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: crawler_events fk_crawler_events_public_page_id_public_pages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crawler_events
    ADD CONSTRAINT fk_crawler_events_public_page_id_public_pages FOREIGN KEY (public_page_id) REFERENCES public.public_pages(id) ON DELETE SET NULL;

--
-- Name: evidence_files fk_evidence_files_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence_files
    ADD CONSTRAINT fk_evidence_files_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: evidence_files fk_evidence_files_sample_id_monitoring_samples; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence_files
    ADD CONSTRAINT fk_evidence_files_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE CASCADE;

--
-- Name: fact_versions fk_fact_versions_actor_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_versions
    ADD CONSTRAINT fk_fact_versions_actor_id_users FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: fact_versions fk_fact_versions_fact_id_facts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_versions
    ADD CONSTRAINT fk_fact_versions_fact_id_facts FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE CASCADE;

--
-- Name: fact_versions fk_fact_versions_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_versions
    ADD CONSTRAINT fk_fact_versions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: facts fk_facts_approved_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT fk_facts_approved_by_users FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: facts fk_facts_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT fk_facts_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: facts fk_facts_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT fk_facts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: facts fk_facts_superseded_by_facts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT fk_facts_superseded_by_facts FOREIGN KEY (superseded_by) REFERENCES public.facts(id) ON DELETE SET NULL;

--
-- Name: faqs fk_faqs_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.faqs
    ADD CONSTRAINT fk_faqs_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: faqs fk_faqs_deleted_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.faqs
    ADD CONSTRAINT fk_faqs_deleted_by_users FOREIGN KEY (deleted_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: faqs fk_faqs_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.faqs
    ADD CONSTRAINT fk_faqs_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: faqs fk_faqs_reviewed_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.faqs
    ADD CONSTRAINT fk_faqs_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: import_batches fk_import_batches_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_batches
    ADD CONSTRAINT fk_import_batches_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: import_batches fk_import_batches_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_batches
    ADD CONSTRAINT fk_import_batches_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: keywords fk_keywords_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.keywords
    ADD CONSTRAINT fk_keywords_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: leads fk_leads_import_batch_id_import_batches; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leads
    ADD CONSTRAINT fk_leads_import_batch_id_import_batches FOREIGN KEY (import_batch_id) REFERENCES public.import_batches(id) ON DELETE SET NULL;

--
-- Name: leads fk_leads_owner_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leads
    ADD CONSTRAINT fk_leads_owner_id_users FOREIGN KEY (owner_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: leads fk_leads_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leads
    ADD CONSTRAINT fk_leads_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: leads fk_leads_source_channel_id_channels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leads
    ADD CONSTRAINT fk_leads_source_channel_id_channels FOREIGN KEY (source_channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;

--
-- Name: leads fk_leads_source_engine_id_ai_engines; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leads
    ADD CONSTRAINT fk_leads_source_engine_id_ai_engines FOREIGN KEY (source_engine_id) REFERENCES public.ai_engines(id) ON DELETE SET NULL;

--
-- Name: leads fk_leads_source_question_id_questions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leads
    ADD CONSTRAINT fk_leads_source_question_id_questions FOREIGN KEY (source_question_id) REFERENCES public.questions(id) ON DELETE SET NULL;

--
-- Name: materials fk_materials_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.materials
    ADD CONSTRAINT fk_materials_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: materials fk_materials_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.materials
    ADD CONSTRAINT fk_materials_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: media_quotes fk_media_quotes_approved_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.media_quotes
    ADD CONSTRAINT fk_media_quotes_approved_by_users FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: media_quotes fk_media_quotes_channel_id_channels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.media_quotes
    ADD CONSTRAINT fk_media_quotes_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;

--
-- Name: media_quotes fk_media_quotes_plan_id_content_plans; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.media_quotes
    ADD CONSTRAINT fk_media_quotes_plan_id_content_plans FOREIGN KEY (plan_id) REFERENCES public.content_plans(id) ON DELETE CASCADE;

--
-- Name: media_quotes fk_media_quotes_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.media_quotes
    ADD CONSTRAINT fk_media_quotes_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: metric_definitions fk_metric_definitions_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metric_definitions
    ADD CONSTRAINT fk_metric_definitions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: monitoring_brand_mentions fk_monitoring_brand_mentions_brand_profile_id_brand_profiles; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_brand_mentions
    ADD CONSTRAINT fk_monitoring_brand_mentions_brand_profile_id_brand_profiles FOREIGN KEY (brand_profile_id) REFERENCES public.brand_profiles(id) ON DELETE SET NULL;

--
-- Name: monitoring_brand_mentions fk_monitoring_brand_mentions_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_brand_mentions
    ADD CONSTRAINT fk_monitoring_brand_mentions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: monitoring_brand_mentions fk_monitoring_brand_mentions_sample_id_monitoring_samples; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_brand_mentions
    ADD CONSTRAINT fk_monitoring_brand_mentions_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE CASCADE;

--
-- Name: monitoring_citations fk_monitoring_citations_channel_id_channels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;

--
-- Name: monitoring_citations fk_monitoring_citations_classification_reviewed_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_classification_reviewed_by_users FOREIGN KEY (classification_reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: monitoring_citations fk_monitoring_citations_competitor_id_competitors; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_competitor_id_competitors FOREIGN KEY (competitor_id) REFERENCES public.competitors(id) ON DELETE SET NULL;

--
-- Name: monitoring_citations fk_monitoring_citations_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: monitoring_citations fk_monitoring_citations_project_sample; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_project_sample FOREIGN KEY (project_id, sample_id) REFERENCES public.monitoring_samples(project_id, id) ON DELETE CASCADE;

--
-- Name: monitoring_citations fk_monitoring_citations_reviewed_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: monitoring_citations fk_monitoring_citations_sample_id_monitoring_samples; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE CASCADE;

--
-- Name: monitoring_competitor_mentions fk_monitoring_competitor_mentions_competitor_id_competitors; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_competitor_mentions
    ADD CONSTRAINT fk_monitoring_competitor_mentions_competitor_id_competitors FOREIGN KEY (competitor_id) REFERENCES public.competitors(id) ON DELETE CASCADE;

--
-- Name: monitoring_competitor_mentions fk_monitoring_competitor_mentions_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_competitor_mentions
    ADD CONSTRAINT fk_monitoring_competitor_mentions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: monitoring_competitor_mentions fk_monitoring_competitor_mentions_sample_id_monitoring_samples; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_competitor_mentions
    ADD CONSTRAINT fk_monitoring_competitor_mentions_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE CASCADE;

--
-- Name: monitoring_execution_attempts fk_monitoring_execution_attempts_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_execution_attempts
    ADD CONSTRAINT fk_monitoring_execution_attempts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: monitoring_execution_attempts fk_monitoring_execution_attempts_task_id_monitoring_tasks; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_execution_attempts
    ADD CONSTRAINT fk_monitoring_execution_attempts_task_id_monitoring_tasks FOREIGN KEY (task_id) REFERENCES public.monitoring_tasks(id) ON DELETE CASCADE;

--
-- Name: monitoring_retest_plans fk_monitoring_retest_plans_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_retest_plans
    ADD CONSTRAINT fk_monitoring_retest_plans_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: monitoring_retest_plans fk_monitoring_retest_plans_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_retest_plans
    ADD CONSTRAINT fk_monitoring_retest_plans_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: monitoring_rounds fk_monitoring_rounds_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT fk_monitoring_rounds_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: monitoring_rounds fk_monitoring_rounds_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT fk_monitoring_rounds_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: monitoring_rounds fk_monitoring_rounds_retest_plan_id_monitoring_retest_plans; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT fk_monitoring_rounds_retest_plan_id_monitoring_retest_plans FOREIGN KEY (retest_plan_id) REFERENCES public.monitoring_retest_plans(id) ON DELETE SET NULL;

--
-- Name: monitoring_samples fk_monitoring_samples_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT fk_monitoring_samples_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: monitoring_samples fk_monitoring_samples_project_task; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT fk_monitoring_samples_project_task FOREIGN KEY (project_id, task_id) REFERENCES public.monitoring_tasks(project_id, id) ON DELETE CASCADE;

--
-- Name: monitoring_samples fk_monitoring_samples_reviewed_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT fk_monitoring_samples_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: monitoring_samples fk_monitoring_samples_task_id_monitoring_tasks; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT fk_monitoring_samples_task_id_monitoring_tasks FOREIGN KEY (task_id) REFERENCES public.monitoring_tasks(id) ON DELETE CASCADE;

--
-- Name: monitoring_source_profiles fk_monitoring_source_profiles_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_source_profiles
    ADD CONSTRAINT fk_monitoring_source_profiles_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: monitoring_source_profiles fk_monitoring_source_profiles_reviewed_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_source_profiles
    ADD CONSTRAINT fk_monitoring_source_profiles_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: monitoring_tasks fk_monitoring_tasks_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: monitoring_tasks fk_monitoring_tasks_engine_entry_id_ai_engine_entries; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_engine_entry_id_ai_engine_entries FOREIGN KEY (engine_entry_id) REFERENCES public.ai_engine_entries(id) ON DELETE RESTRICT;

--
-- Name: monitoring_tasks fk_monitoring_tasks_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: monitoring_tasks fk_monitoring_tasks_project_question_version; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_project_question_version FOREIGN KEY (project_id, question_version_id) REFERENCES public.question_versions(project_id, id) ON DELETE RESTRICT;

--
-- Name: monitoring_tasks fk_monitoring_tasks_project_round; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_project_round FOREIGN KEY (project_id, round_id) REFERENCES public.monitoring_rounds(project_id, id) ON DELETE RESTRICT;

--
-- Name: monitoring_tasks fk_monitoring_tasks_question_version_id_question_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_question_version_id_question_versions FOREIGN KEY (question_version_id) REFERENCES public.question_versions(id) ON DELETE RESTRICT;

--
-- Name: monitoring_tasks fk_monitoring_tasks_round_id_monitoring_rounds; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT fk_monitoring_tasks_round_id_monitoring_rounds FOREIGN KEY (round_id) REFERENCES public.monitoring_rounds(id) ON DELETE RESTRICT;

--
-- Name: monthly_report_snapshots fk_monthly_report_snapshots_captured_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monthly_report_snapshots
    ADD CONSTRAINT fk_monthly_report_snapshots_captured_by_users FOREIGN KEY (captured_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: monthly_report_snapshots fk_monthly_report_snapshots_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monthly_report_snapshots
    ADD CONSTRAINT fk_monthly_report_snapshots_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: oauth_authorization_states fk_oauth_authorization_states_channel_id_channels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_authorization_states
    ADD CONSTRAINT fk_oauth_authorization_states_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;

--
-- Name: oauth_authorization_states fk_oauth_authorization_states_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_authorization_states
    ADD CONSTRAINT fk_oauth_authorization_states_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: oauth_authorization_states fk_oauth_authorization_states_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_authorization_states
    ADD CONSTRAINT fk_oauth_authorization_states_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: oauth_connections fk_oauth_connections_channel_id_channels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_connections
    ADD CONSTRAINT fk_oauth_connections_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;

--
-- Name: oauth_connections fk_oauth_connections_connected_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_connections
    ADD CONSTRAINT fk_oauth_connections_connected_by_users FOREIGN KEY (connected_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: oauth_connections fk_oauth_connections_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_connections
    ADD CONSTRAINT fk_oauth_connections_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: opportunities fk_opportunities_linked_content_item_id_content_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_linked_content_item_id_content_items FOREIGN KEY (linked_content_item_id) REFERENCES public.content_items(id) ON DELETE SET NULL;

--
-- Name: opportunities fk_opportunities_linked_content_plan_id_content_plans; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_linked_content_plan_id_content_plans FOREIGN KEY (linked_content_plan_id) REFERENCES public.content_plans(id) ON DELETE SET NULL;

--
-- Name: opportunities fk_opportunities_linked_publish_task_id_publish_tasks; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_linked_publish_task_id_publish_tasks FOREIGN KEY (linked_publish_task_id) REFERENCES public.publish_tasks(id) ON DELETE SET NULL;

--
-- Name: opportunities fk_opportunities_owner_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_owner_id_users FOREIGN KEY (owner_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: opportunities fk_opportunities_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: opportunities fk_opportunities_question_id_questions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_question_id_questions FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE SET NULL;

--
-- Name: opportunities fk_opportunities_sample_id_monitoring_samples; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.opportunities
    ADD CONSTRAINT fk_opportunities_sample_id_monitoring_samples FOREIGN KEY (sample_id) REFERENCES public.monitoring_samples(id) ON DELETE SET NULL;

--
-- Name: outbox_events fk_outbox_events_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_events
    ADD CONSTRAINT fk_outbox_events_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: page_approvals fk_page_approvals_channel_id_channels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_approvals
    ADD CONSTRAINT fk_page_approvals_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE CASCADE;

--
-- Name: page_approvals fk_page_approvals_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_approvals
    ADD CONSTRAINT fk_page_approvals_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: page_approvals fk_page_approvals_requested_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_approvals
    ADD CONSTRAINT fk_page_approvals_requested_by_users FOREIGN KEY (requested_by) REFERENCES public.users(id) ON DELETE RESTRICT;

--
-- Name: page_approvals fk_page_approvals_reviewed_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_approvals
    ADD CONSTRAINT fk_page_approvals_reviewed_by_users FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: project_members fk_project_members_granted_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT fk_project_members_granted_by_users FOREIGN KEY (granted_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: project_members fk_project_members_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT fk_project_members_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: project_members fk_project_members_role_id_roles; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT fk_project_members_role_id_roles FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE RESTRICT;

--
-- Name: project_members fk_project_members_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT fk_project_members_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;

--
-- Name: projects fk_projects_business_confirmed_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT fk_projects_business_confirmed_by_users FOREIGN KEY (business_confirmed_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: public_pages fk_public_pages_content_item_id_content_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_pages
    ADD CONSTRAINT fk_public_pages_content_item_id_content_items FOREIGN KEY (content_item_id) REFERENCES public.content_items(id) ON DELETE SET NULL;

--
-- Name: public_pages fk_public_pages_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.public_pages
    ADD CONSTRAINT fk_public_pages_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: publish_accounts fk_publish_accounts_channel_id_channels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_accounts
    ADD CONSTRAINT fk_publish_accounts_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE RESTRICT;

--
-- Name: publish_accounts fk_publish_accounts_oauth_connection_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_accounts
    ADD CONSTRAINT fk_publish_accounts_oauth_connection_id FOREIGN KEY (oauth_connection_id) REFERENCES public.oauth_connections(id) ON DELETE SET NULL;

--
-- Name: publish_accounts fk_publish_accounts_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_accounts
    ADD CONSTRAINT fk_publish_accounts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: publish_attempts fk_publish_attempts_operator_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_attempts
    ADD CONSTRAINT fk_publish_attempts_operator_id_users FOREIGN KEY (operator_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: publish_attempts fk_publish_attempts_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_attempts
    ADD CONSTRAINT fk_publish_attempts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: publish_attempts fk_publish_attempts_task_id_publish_tasks; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_attempts
    ADD CONSTRAINT fk_publish_attempts_task_id_publish_tasks FOREIGN KEY (task_id) REFERENCES public.publish_tasks(id) ON DELETE CASCADE;

--
-- Name: publish_receipts fk_publish_receipts_attempt_id_publish_attempts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_attempt_id_publish_attempts FOREIGN KEY (attempt_id) REFERENCES public.publish_attempts(id) ON DELETE SET NULL;

--
-- Name: publish_receipts fk_publish_receipts_budget; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_budget FOREIGN KEY (budget_approval_id) REFERENCES public.budget_approvals(id) ON DELETE RESTRICT;

--
-- Name: publish_receipts fk_publish_receipts_page_approval_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_page_approval_id FOREIGN KEY (page_approval_id) REFERENCES public.page_approvals(id) ON DELETE SET NULL;

--
-- Name: publish_receipts fk_publish_receipts_project_budget; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_project_budget FOREIGN KEY (project_id, budget_approval_id) REFERENCES public.budget_approvals(project_id, id) ON DELETE RESTRICT;

--
-- Name: publish_receipts fk_publish_receipts_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: publish_receipts fk_publish_receipts_task_id_publish_tasks; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_task_id_publish_tasks FOREIGN KEY (task_id) REFERENCES public.publish_tasks(id) ON DELETE CASCADE;

--
-- Name: publish_receipts fk_publish_receipts_verified_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_receipts
    ADD CONSTRAINT fk_publish_receipts_verified_by_users FOREIGN KEY (verified_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: publish_tasks fk_publish_tasks_account_id_publish_accounts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT fk_publish_tasks_account_id_publish_accounts FOREIGN KEY (account_id) REFERENCES public.publish_accounts(id) ON DELETE RESTRICT;

--
-- Name: publish_tasks fk_publish_tasks_channel_id_channels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT fk_publish_tasks_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE RESTRICT;

--
-- Name: publish_tasks fk_publish_tasks_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT fk_publish_tasks_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: publish_tasks fk_publish_tasks_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT fk_publish_tasks_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: publish_tasks fk_publish_tasks_version_id_content_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_tasks
    ADD CONSTRAINT fk_publish_tasks_version_id_content_versions FOREIGN KEY (version_id) REFERENCES public.content_versions(id) ON DELETE RESTRICT;

--
-- Name: publish_visibility_checks fk_publish_visibility_checks_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_visibility_checks
    ADD CONSTRAINT fk_publish_visibility_checks_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: publish_visibility_checks fk_publish_visibility_checks_receipt_id_publish_receipts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publish_visibility_checks
    ADD CONSTRAINT fk_publish_visibility_checks_receipt_id_publish_receipts FOREIGN KEY (receipt_id) REFERENCES public.publish_receipts(id) ON DELETE CASCADE;

--
-- Name: question_keywords fk_question_keywords_keyword_id_keywords; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_keywords
    ADD CONSTRAINT fk_question_keywords_keyword_id_keywords FOREIGN KEY (keyword_id) REFERENCES public.keywords(id) ON DELETE CASCADE;

--
-- Name: question_keywords fk_question_keywords_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_keywords
    ADD CONSTRAINT fk_question_keywords_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: question_keywords fk_question_keywords_question_id_questions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_keywords
    ADD CONSTRAINT fk_question_keywords_question_id_questions FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE CASCADE;

--
-- Name: question_version_keywords fk_question_version_keywords_keyword_id_keywords; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_version_keywords
    ADD CONSTRAINT fk_question_version_keywords_keyword_id_keywords FOREIGN KEY (keyword_id) REFERENCES public.keywords(id) ON DELETE CASCADE;

--
-- Name: question_version_keywords fk_question_version_keywords_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_version_keywords
    ADD CONSTRAINT fk_question_version_keywords_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: question_version_keywords fk_question_version_keywords_question_version_id_questi_ed6d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_version_keywords
    ADD CONSTRAINT fk_question_version_keywords_question_version_id_questi_ed6d FOREIGN KEY (question_version_id) REFERENCES public.question_versions(id) ON DELETE CASCADE;

--
-- Name: question_versions fk_question_versions_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT fk_question_versions_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: question_versions fk_question_versions_import_batch_id_import_batches; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT fk_question_versions_import_batch_id_import_batches FOREIGN KEY (import_batch_id) REFERENCES public.import_batches(id) ON DELETE SET NULL;

--
-- Name: question_versions fk_question_versions_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT fk_question_versions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: question_versions fk_question_versions_question_id_questions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.question_versions
    ADD CONSTRAINT fk_question_versions_question_id_questions FOREIGN KEY (question_id) REFERENCES public.questions(id) ON DELETE CASCADE;

--
-- Name: questions fk_questions_import_batch_id_import_batches; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questions
    ADD CONSTRAINT fk_questions_import_batch_id_import_batches FOREIGN KEY (import_batch_id) REFERENCES public.import_batches(id) ON DELETE SET NULL;

--
-- Name: questions fk_questions_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questions
    ADD CONSTRAINT fk_questions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: role_permissions fk_role_permissions_permission; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT fk_role_permissions_permission FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE CASCADE;

--
-- Name: role_permissions fk_role_permissions_role; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT fk_role_permissions_role FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;

--
-- Name: stat_snapshots fk_stat_snapshots_captured_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stat_snapshots
    ADD CONSTRAINT fk_stat_snapshots_captured_by_users FOREIGN KEY (captured_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: stat_snapshots fk_stat_snapshots_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stat_snapshots
    ADD CONSTRAINT fk_stat_snapshots_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- Name: stat_snapshots fk_stat_snapshots_round_id_monitoring_rounds; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stat_snapshots
    ADD CONSTRAINT fk_stat_snapshots_round_id_monitoring_rounds FOREIGN KEY (round_id) REFERENCES public.monitoring_rounds(id) ON DELETE CASCADE;

--
-- Name: traffic_events fk_traffic_events_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.traffic_events
    ADD CONSTRAINT fk_traffic_events_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;

--
-- PostgreSQL database dump complete
--
