--
-- PostgreSQL database dump
--

\restrict DiorsyvCwjyeFeB91WdB1WsglHQyNbC3stHOLzqaUFdR4ODBG3tRYCrOglOJdj6

-- Dumped from database version 16.15 (Debian 16.15-1.pgdg13+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg13+2)

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
    CONSTRAINT ck_ai_engine_entries_engine_entry_type CHECK (((entry_type)::text = ANY ((ARRAY['web_user'::character varying, 'app_user'::character varying, 'api'::character varying, 'app_search'::character varying])::text[])))
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
    id uuid NOT NULL
);


--
-- Name: channel_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.channel_aliases (
    project_id uuid NOT NULL,
    channel_id uuid NOT NULL,
    domain character varying(255) NOT NULL,
    alias_name character varying(128),
    notes text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
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
    CONSTRAINT ck_channels_channel_category CHECK (((category)::text = ANY ((ARRAY['own_site'::character varying, 'content_platform'::character varying, 'video'::character varying, 'community'::character varying, 'encyclopedia'::character varying, 'local_media'::character varying, 'industry_media'::character varying, 'institution'::character varying])::text[]))),
    CONSTRAINT ck_channels_channel_status CHECK (((status)::text = ANY ((ARRAY['candidate'::character varying, 'published'::character varying, 'observed'::character varying, 'review_pending'::character varying])::text[])))
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
    CONSTRAINT ck_content_items_content_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'pending_review'::character varying, 'approved'::character varying, 'rejected'::character varying, 'scheduled'::character varying, 'published'::character varying, 'needs_attention'::character varying, 'archived'::character varying])::text[])))
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
    CONSTRAINT ck_content_versions_content_version_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'pending_review'::character varying, 'approved'::character varying, 'rejected'::character varying, 'scheduled'::character varying, 'published'::character varying, 'needs_attention'::character varying, 'archived'::character varying])::text[])))
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
    CONSTRAINT ck_leads_enrollment_status CHECK (((enrollment_status)::text = ANY ((ARRAY['unknown'::character varying, 'contacted'::character varying, 'enrolled'::character varying, 'lost'::character varying])::text[])))
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
    CONSTRAINT ck_media_quotes_quote_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying])::text[])))
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
    CONSTRAINT ck_monitoring_citations_citation_review_status CHECK (((review_status)::text = ANY ((ARRAY['auto'::character varying, 'manual_confirmed'::character varying, 'manual_rejected'::character varying])::text[])))
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
    CONSTRAINT ck_monitoring_samples_failure_code CHECK (((failure_code)::text = ANY ((ARRAY['login_blocked'::character varying, 'timeout'::character varying, 'access_blocked'::character varying, 'captcha'::character varying, 'rate_limited'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_samples_review_result CHECK (((review_result)::text = ANY ((ARRAY['hit'::character varying, 'miss'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_samples_sample_sampling_mode CHECK (((sampling_mode)::text = ANY ((ARRAY['search_on'::character varying, 'search_off'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_samples_sample_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'hit'::character varying, 'miss'::character varying, 'failed'::character varying, 'manual_review'::character varying])::text[])))
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
    CONSTRAINT ck_monitoring_tasks_sampling_mode CHECK (((sampling_mode)::text = ANY ((ARRAY['search_on'::character varying, 'search_off'::character varying])::text[]))),
    CONSTRAINT ck_monitoring_tasks_task_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'done'::character varying, 'failed'::character varying, 'cancelled'::character varying])::text[])))
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
    CONSTRAINT ck_outbox_events_ck_outbox_events_project_or_system CHECK (((project_id IS NOT NULL) OR ((topic)::text ~~ 'system.%'::text))),
    CONSTRAINT ck_outbox_events_outbox_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'dispatched'::character varying, 'failed'::character varying])::text[])))
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
    CONSTRAINT ck_public_pages_page_publish_status CHECK (((publish_status)::text = ANY ((ARRAY['draft'::character varying, 'published'::character varying, 'offline'::character varying])::text[]))),
    CONSTRAINT ck_public_pages_page_type CHECK (((page_type)::text = ANY ((ARRAY['home'::character varying, 'course'::character varying, 'faq'::character varying, 'case'::character varying, 'contact'::character varying, 'other'::character varying])::text[])))
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
    updated_at timestamp with time zone DEFAULT now() NOT NULL
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
    updated_at timestamp with time zone DEFAULT now() NOT NULL
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
    CONSTRAINT ck_publish_tasks_publish_mode CHECK (((publish_mode)::text = ANY ((ARRAY['manual'::character varying, 'api'::character varying, 'authorized'::character varying])::text[]))),
    CONSTRAINT ck_publish_tasks_publish_task_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'publishing'::character varying, 'published'::character varying, 'unknown'::character varying, 'failed'::character varying, 'needs_review'::character varying, 'cancelled'::character varying])::text[])))
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
    import_batch_id uuid
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
    is_system_admin boolean DEFAULT false NOT NULL
);


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
-- Name: audit_logs pk_audit_logs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT pk_audit_logs PRIMARY KEY (id);


--
-- Name: channel_aliases pk_channel_aliases; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_aliases
    ADD CONSTRAINT pk_channel_aliases PRIMARY KEY (id);


--
-- Name: channels pk_channels; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channels
    ADD CONSTRAINT pk_channels PRIMARY KEY (id);


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
-- Name: evidence_files pk_evidence_files; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence_files
    ADD CONSTRAINT pk_evidence_files PRIMARY KEY (id);


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
-- Name: monitoring_citations pk_monitoring_citations; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT pk_monitoring_citations PRIMARY KEY (id);


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
-- Name: monitoring_tasks pk_monitoring_tasks; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT pk_monitoring_tasks PRIMARY KEY (id);


--
-- Name: outbox_events pk_outbox_events; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_events
    ADD CONSTRAINT pk_outbox_events PRIMARY KEY (id);


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
-- Name: content_version_citations uq_content_version_citations_version_citation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT uq_content_version_citations_version_citation UNIQUE (version_id, citation_id);


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
-- Name: keywords uq_keywords_project_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.keywords
    ADD CONSTRAINT uq_keywords_project_name UNIQUE (project_id, name);


--
-- Name: metric_definitions uq_metric_definitions_project_code_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metric_definitions
    ADD CONSTRAINT uq_metric_definitions_project_code_version UNIQUE (project_id, code, rule_version);


--
-- Name: monitoring_rounds uq_monitoring_rounds_project_seq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_rounds
    ADD CONSTRAINT uq_monitoring_rounds_project_seq UNIQUE (project_id, seq);


--
-- Name: monitoring_samples uq_monitoring_samples_task_attempt; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT uq_monitoring_samples_task_attempt UNIQUE (task_id, attempt_no);


--
-- Name: monitoring_tasks uq_monitoring_tasks_round_question_entry_sampling; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_tasks
    ADD CONSTRAINT uq_monitoring_tasks_round_question_entry_sampling UNIQUE (round_id, question_version_id, engine_entry_id, sampling_no);


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
-- Name: ix_audit_logs_project_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_project_created ON public.audit_logs USING btree (project_id, created_at);


--
-- Name: ix_audit_logs_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_target ON public.audit_logs USING btree (target_type, target_id);


--
-- Name: ix_channel_aliases_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_channel_aliases_channel ON public.channel_aliases USING btree (channel_id);


--
-- Name: ix_channels_project_category_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_channels_project_category_status ON public.channels USING btree (project_id, category, status);


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
-- Name: ix_evidence_files_project_sample; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_evidence_files_project_sample ON public.evidence_files USING btree (project_id, sample_id);


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
-- Name: ix_media_quotes_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_media_quotes_project_status ON public.media_quotes USING btree (project_id, status);


--
-- Name: ix_monitoring_citations_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_citations_channel ON public.monitoring_citations USING btree (channel_id);


--
-- Name: ix_monitoring_citations_project_domain_review; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_citations_project_domain_review ON public.monitoring_citations USING btree (project_id, domain, review_status);


--
-- Name: ix_monitoring_citations_project_sample; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_citations_project_sample ON public.monitoring_citations USING btree (project_id, sample_id);


--
-- Name: ix_monitoring_rounds_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_monitoring_rounds_project_status ON public.monitoring_rounds USING btree (project_id, status);


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
-- Name: ix_outbox_events_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbox_events_project_id ON public.outbox_events USING btree (project_id);


--
-- Name: ix_outbox_events_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbox_events_status_created ON public.outbox_events USING btree (status, created_at);


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
-- Name: ai_engine_entries fk_ai_engine_entries_engine_id_ai_engines; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_engine_entries
    ADD CONSTRAINT fk_ai_engine_entries_engine_id_ai_engines FOREIGN KEY (engine_id) REFERENCES public.ai_engines(id) ON DELETE CASCADE;


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
-- Name: content_version_citations fk_content_version_citations_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT fk_content_version_citations_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;


--
-- Name: content_version_citations fk_content_version_citations_version_id_content_versions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.content_version_citations
    ADD CONSTRAINT fk_content_version_citations_version_id_content_versions FOREIGN KEY (version_id) REFERENCES public.content_versions(id) ON DELETE CASCADE;


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
-- Name: monitoring_citations fk_monitoring_citations_channel_id_channels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_channel_id_channels FOREIGN KEY (channel_id) REFERENCES public.channels(id) ON DELETE SET NULL;


--
-- Name: monitoring_citations fk_monitoring_citations_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_citations
    ADD CONSTRAINT fk_monitoring_citations_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;


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
-- Name: monitoring_samples fk_monitoring_samples_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_samples
    ADD CONSTRAINT fk_monitoring_samples_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;


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
-- Name: outbox_events fk_outbox_events_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_events
    ADD CONSTRAINT fk_outbox_events_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT;


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
-- PostgreSQL database dump complete
--

\unrestrict DiorsyvCwjyeFeB91WdB1WsglHQyNbC3stHOLzqaUFdR4ODBG3tRYCrOglOJdj6

