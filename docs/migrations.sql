BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_initial

CREATE TABLE employer_groups (
    canonical_name VARCHAR(255) NOT NULL,
    normalized_name VARCHAR(255) NOT NULL,
    grouping_evidence JSONB NOT NULL,
    pool_tags JSONB NOT NULL,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id)
);

CREATE INDEX ix_employer_groups_normalized_name ON employer_groups (normalized_name);

CREATE TABLE outbox_events (
    event_key VARCHAR(255) NOT NULL,
    event_type VARCHAR(80) NOT NULL,
    payload JSONB NOT NULL,
    state VARCHAR(30) NOT NULL,
    attempts INTEGER NOT NULL,
    next_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL,
    lease_owner VARCHAR(255),
    lease_expires_at TIMESTAMP WITH TIME ZONE,
    dispatched_at TIMESTAMP WITH TIME ZONE,
    last_error TEXT,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (event_key)
);

CREATE INDEX ix_outbox_events_state ON outbox_events (state);

CREATE TABLE people (
    linkedin_url TEXT NOT NULL,
    name VARCHAR(255) NOT NULL,
    headline TEXT NOT NULL,
    company VARCHAR(255) NOT NULL,
    employment_evidence JSONB NOT NULL,
    checked_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (linkedin_url)
);

CREATE TABLE people_search_cache (
    query_hash VARCHAR(64) NOT NULL,
    query_text TEXT NOT NULL,
    result_payload JSONB NOT NULL,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (query_hash)
);

CREATE TABLE users (
    google_subject VARCHAR(255) NOT NULL,
    verified_email VARCHAR(320) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    timezone VARCHAR(80) NOT NULL,
    cycle_anchor DATE,
    is_admin BOOLEAN NOT NULL,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (google_subject)
);

CREATE TABLE work_items (
    task_key VARCHAR(255) NOT NULL,
    task_type VARCHAR(80) NOT NULL,
    payload JSONB NOT NULL,
    state VARCHAR(30) NOT NULL,
    attempts INTEGER NOT NULL,
    next_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL,
    lease_owner VARCHAR(255),
    lease_expires_at TIMESTAMP WITH TIME ZONE,
    result JSONB,
    last_error TEXT,
    completed_at TIMESTAMP WITH TIME ZONE,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (task_key)
);

CREATE INDEX ix_work_items_state ON work_items (state);

CREATE TABLE company_cycles (
    user_id UUID NOT NULL,
    cycle_index INTEGER NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    anchor_date DATE NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (user_id, cycle_index),
    CONSTRAINT cycle_interval CHECK (end_date > start_date),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE devices (
    user_id UUID NOT NULL,
    platform VARCHAR(30) NOT NULL,
    app_version VARCHAR(50) NOT NULL,
    device_label VARCHAR(255) NOT NULL,
    push_token_encrypted TEXT,
    last_seen TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    sync_cursor BIGINT NOT NULL,
    revision INTEGER NOT NULL,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_devices_user_id ON devices (user_id);

CREATE TABLE employer_brands (
    group_id UUID NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    canonical_domain VARCHAR(255),
    id UUID NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(group_id) REFERENCES employer_groups (id)
);

CREATE INDEX ix_employer_brands_group_id ON employer_brands (group_id);

CREATE TABLE gmail_connections (
    user_id UUID NOT NULL,
    google_identity VARCHAR(320) NOT NULL,
    refresh_token_encrypted TEXT,
    granted_scopes JSONB NOT NULL,
    selected_label VARCHAR(255),
    sync_health VARCHAR(40) NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (user_id),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE login_intents (
    device_id UUID NOT NULL,
    purpose VARCHAR(30) NOT NULL,
    selected_label VARCHAR(255),
    state_hash VARCHAR(128) NOT NULL,
    challenge VARCHAR(255) NOT NULL,
    nonce VARCHAR(255) NOT NULL,
    platform VARCHAR(30) NOT NULL,
    device_label VARCHAR(255) NOT NULL,
    user_id UUID,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    redeemed_at TIMESTAMP WITH TIME ZONE,
    code_verifier_encrypted TEXT,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (state_hash),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE notifications (
    user_id UUID NOT NULL,
    notification_type VARCHAR(50) NOT NULL,
    target_type VARCHAR(30) NOT NULL,
    target_id UUID NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    event_dedupe_key VARCHAR(255) NOT NULL,
    read_at TIMESTAMP WITH TIME ZONE,
    revision INTEGER NOT NULL,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (user_id, event_dedupe_key),
    CONSTRAINT notification_target CHECK (target_type IN ('jobs','applications','reviews','reports','search-runs')),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_notifications_user_id ON notifications (user_id);

CREATE INDEX ix_unread_notifications ON notifications (user_id, read_at);

CREATE TABLE processed_operations (
    user_id UUID NOT NULL,
    operation_id VARCHAR(128) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    response JSONB NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (user_id, operation_id),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE review_items (
    user_id UUID NOT NULL,
    review_type VARCHAR(50) NOT NULL,
    target_id UUID,
    reason TEXT NOT NULL,
    evidence JSONB NOT NULL,
    state VARCHAR(30) NOT NULL,
    admin_only BOOLEAN NOT NULL,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolution JSONB NOT NULL,
    revision INTEGER NOT NULL,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_review_items_user_id ON review_items (user_id);

CREATE TABLE search_profile_versions (
    user_id UUID NOT NULL,
    version INTEGER NOT NULL,
    payload JSONB NOT NULL,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (user_id, version),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE search_profiles (
    user_id UUID NOT NULL,
    version INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    role_families JSONB NOT NULL,
    skills JSONB NOT NULL,
    aliases JSONB NOT NULL,
    geography JSONB NOT NULL,
    work_arrangements JSONB NOT NULL,
    salary_preferences JSONB NOT NULL,
    ruleset_version VARCHAR(80) NOT NULL,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (user_id),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE search_runs (
    user_id UUID,
    scheduled_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    finished_at TIMESTAMP WITH TIME ZONE,
    profile_version INTEGER NOT NULL,
    state VARCHAR(30) NOT NULL,
    counts JSONB NOT NULL,
    errors JSONB NOT NULL,
    coverage JSONB NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_search_runs_user_id ON search_runs (user_id);

CREATE TABLE source_registry (
    connector_type VARCHAR(80) NOT NULL,
    tenant VARCHAR(255) NOT NULL,
    employer_group_id UUID,
    board_identifier VARCHAR(255),
    career_url TEXT,
    geography JSONB NOT NULL,
    pool_tags JSONB NOT NULL,
    configuration_state VARCHAR(40) NOT NULL,
    capabilities JSONB NOT NULL,
    enabled BOOLEAN NOT NULL,
    last_success TIMESTAMP WITH TIME ZONE,
    last_error TEXT,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (connector_type, tenant),
    CONSTRAINT no_linkedin_source CHECK (connector_type != 'linkedin'),
    FOREIGN KEY(employer_group_id) REFERENCES employer_groups (id)
);

CREATE TABLE sync_snapshots (
    user_id UUID NOT NULL,
    boundary_cursor BIGINT NOT NULL,
    items JSONB NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_sync_snapshots_expires_at ON sync_snapshots (expires_at);

CREATE INDEX ix_sync_snapshots_user_id ON sync_snapshots (user_id);

CREATE TABLE user_changes (
    cursor BIGINT GENERATED BY DEFAULT AS IDENTITY,
    user_id UUID NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    tombstone BOOLEAN NOT NULL,
    committed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (cursor),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_user_change_cursor ON user_changes (user_id, cursor);

CREATE INDEX ix_user_changes_user_id ON user_changes (user_id);

CREATE TABLE watchlist_entries (
    user_id UUID NOT NULL,
    employer_group_id UUID NOT NULL,
    enabled BOOLEAN NOT NULL,
    revision INTEGER NOT NULL,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (user_id, employer_group_id),
    FOREIGN KEY(user_id) REFERENCES users (id),
    FOREIGN KEY(employer_group_id) REFERENCES employer_groups (id)
);

CREATE TABLE app_sessions (
    user_id UUID NOT NULL,
    device_id UUID NOT NULL,
    refresh_token_hash VARCHAR(128) NOT NULL,
    access_token_hash VARCHAR(128),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    access_expires_at TIMESTAMP WITH TIME ZONE,
    revoked_at TIMESTAMP WITH TIME ZONE,
    last_used_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id),
    FOREIGN KEY(device_id) REFERENCES devices (id),
    UNIQUE (refresh_token_hash),
    UNIQUE (access_token_hash)
);

CREATE INDEX ix_app_sessions_user_id ON app_sessions (user_id);

CREATE TABLE connector_runs (
    search_run_id UUID NOT NULL,
    source_registry_id UUID NOT NULL,
    query JSONB NOT NULL,
    pool VARCHAR(80),
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    finished_at TIMESTAMP WITH TIME ZONE,
    cursor TEXT,
    counts JSONB NOT NULL,
    errors JSONB NOT NULL,
    health VARCHAR(40) NOT NULL,
    coverage JSONB NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(search_run_id) REFERENCES search_runs (id),
    FOREIGN KEY(source_registry_id) REFERENCES source_registry (id)
);

CREATE TABLE email_messages (
    connection_id UUID NOT NULL,
    gmail_message_id VARCHAR(255) NOT NULL,
    thread_id VARCHAR(255) NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    received_at TIMESTAMP WITH TIME ZONE NOT NULL,
    classification VARCHAR(50) NOT NULL,
    evidence JSONB NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (connection_id, gmail_message_id),
    FOREIGN KEY(connection_id) REFERENCES gmail_connections (id)
);

CREATE INDEX ix_email_messages_thread_id ON email_messages (thread_id);

CREATE TABLE employer_entities (
    group_id UUID NOT NULL,
    brand_id UUID,
    legal_name VARCHAR(255) NOT NULL,
    jurisdiction VARCHAR(255),
    address_evidence JSONB NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(group_id) REFERENCES employer_groups (id),
    FOREIGN KEY(brand_id) REFERENCES employer_brands (id)
);

CREATE INDEX ix_employer_entities_group_id ON employer_entities (group_id);

CREATE INDEX ix_employer_entities_legal_name ON employer_entities (legal_name);

CREATE TABLE gmail_sync_state (
    connection_id UUID NOT NULL,
    history_cursor VARCHAR(255),
    reconciliation_progress JSONB NOT NULL,
    last_success TIMESTAMP WITH TIME ZONE,
    watch_expiry TIMESTAMP WITH TIME ZONE,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (connection_id),
    FOREIGN KEY(connection_id) REFERENCES gmail_connections (id)
);

CREATE TABLE notification_deliveries (
    notification_id UUID NOT NULL,
    device_id UUID NOT NULL,
    channel VARCHAR(30) NOT NULL,
    attempts INTEGER NOT NULL,
    state VARCHAR(30) NOT NULL,
    last_attempt TIMESTAMP WITH TIME ZONE,
    provider_reference TEXT,
    last_error TEXT,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (notification_id, device_id, channel),
    FOREIGN KEY(notification_id) REFERENCES notifications (id),
    FOREIGN KEY(device_id) REFERENCES devices (id)
);

CREATE TABLE reports (
    user_id UUID NOT NULL,
    report_date DATE NOT NULL,
    cycle_id UUID NOT NULL,
    intended_release TIMESTAMP WITH TIME ZONE NOT NULL,
    actual_release TIMESTAMP WITH TIME ZONE,
    status VARCHAR(30) NOT NULL,
    profile_version INTEGER NOT NULL,
    summary JSONB NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (user_id, report_date),
    FOREIGN KEY(user_id) REFERENCES users (id),
    FOREIGN KEY(cycle_id) REFERENCES company_cycles (id)
);

CREATE TABLE company_cycle_usage (
    user_id UUID NOT NULL,
    cycle_id UUID NOT NULL,
    employer_group_id UUID NOT NULL,
    report_id UUID NOT NULL,
    report_date DATE NOT NULL,
    count INTEGER NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (user_id, cycle_id, employer_group_id),
    CONSTRAINT company_daily_limit CHECK (count >= 1 AND count <= 2),
    FOREIGN KEY(user_id) REFERENCES users (id),
    FOREIGN KEY(cycle_id) REFERENCES company_cycles (id),
    FOREIGN KEY(employer_group_id) REFERENCES employer_groups (id),
    FOREIGN KEY(report_id) REFERENCES reports (id)
);

CREATE TABLE employer_aliases (
    group_id UUID,
    entity_id UUID,
    normalized_alias VARCHAR(255) NOT NULL,
    alias_type VARCHAR(30) NOT NULL,
    evidence JSONB NOT NULL,
    checked_at TIMESTAMP WITH TIME ZONE NOT NULL,
    reviewer VARCHAR(255) NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(group_id) REFERENCES employer_groups (id),
    FOREIGN KEY(entity_id) REFERENCES employer_entities (id)
);

CREATE INDEX ix_employer_aliases_normalized_alias ON employer_aliases (normalized_alias);

CREATE TABLE everify_evidence (
    entity_id UUID NOT NULL,
    status VARCHAR(30) NOT NULL,
    legal_name_as_found VARCHAR(255) NOT NULL,
    source_reference TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    checked_at TIMESTAMP WITH TIME ZONE NOT NULL,
    recheck_due_at TIMESTAMP WITH TIME ZONE NOT NULL,
    verification_method VARCHAR(80) NOT NULL,
    reviewer VARCHAR(255) NOT NULL,
    synthetic BOOLEAN NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT everify_status CHECK (status IN ('CONFIRMED','UNKNOWN','CONFLICTING','NO_LONGER_CONFIRMED')),
    CONSTRAINT everify_proof CHECK (status != 'CONFIRMED' OR (length(source_reference)>0 AND length(snapshot)>0 AND length(content_hash)=64 AND length(reviewer)>0)),
    FOREIGN KEY(entity_id) REFERENCES employer_entities (id)
);

CREATE INDEX ix_everify_evidence_entity_id ON everify_evidence (entity_id);

CREATE INDEX ix_everify_evidence_recheck_due_at ON everify_evidence (recheck_due_at);

CREATE TABLE jobs (
    employer_group_id UUID NOT NULL,
    entity_id UUID,
    title TEXT NOT NULL,
    locations JSONB NOT NULL,
    work_arrangement VARCHAR(30),
    requisition_id VARCHAR(255),
    published_at TIMESTAMP WITH TIME ZONE,
    published_earliest TIMESTAMP WITH TIME ZONE,
    published_latest TIMESTAMP WITH TIME ZONE,
    publication_precision VARCHAR(40) NOT NULL,
    source_updated_at TIMESTAMP WITH TIME ZONE,
    last_published_at TIMESTAMP WITH TIME ZONE,
    first_seen TIMESTAMP WITH TIME ZONE NOT NULL,
    availability VARCHAR(30) NOT NULL,
    current_snapshot_id UUID,
    canonical_redirect_id UUID,
    salary_min NUMERIC(14, 2),
    salary_max NUMERIC(14, 2),
    salary_currency VARCHAR(5),
    salary_interval VARCHAR(30),
    priority_reasons JSONB NOT NULL,
    role_family VARCHAR(100),
    synthetic BOOLEAN NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT job_availability CHECK (availability IN ('ACTIVE','CLOSED','UNKNOWN')),
    CONSTRAINT no_self_redirect CHECK (canonical_redirect_id IS NULL OR canonical_redirect_id != id),
    FOREIGN KEY(employer_group_id) REFERENCES employer_groups (id),
    FOREIGN KEY(entity_id) REFERENCES employer_entities (id),
    FOREIGN KEY(canonical_redirect_id) REFERENCES jobs (id)
);

CREATE INDEX ix_jobs_employer_group_id ON jobs (employer_group_id);

CREATE INDEX ix_jobs_published_at ON jobs (published_at);

CREATE TABLE duplicate_links (
    candidate_id UUID NOT NULL,
    canonical_id UUID NOT NULL,
    link_type VARCHAR(40) NOT NULL,
    evidence JSONB NOT NULL,
    mechanism VARCHAR(255) NOT NULL,
    reversed_by_id UUID,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT no_self_duplicate CHECK (candidate_id != canonical_id),
    FOREIGN KEY(candidate_id) REFERENCES jobs (id),
    FOREIGN KEY(canonical_id) REFERENCES jobs (id),
    FOREIGN KEY(reversed_by_id) REFERENCES duplicate_links (id)
);

CREATE TABLE enrichment_runs (
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    job_id UUID NOT NULL,
    state VARCHAR(40) NOT NULL,
    attempts INTEGER NOT NULL,
    query_count INTEGER NOT NULL,
    discovered_count INTEGER NOT NULL,
    approved_count INTEGER NOT NULL,
    cost_units NUMERIC(14, 4) NOT NULL,
    last_error TEXT,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(job_id) REFERENCES jobs (id)
);

CREATE INDEX ix_enrichment_runs_job_id ON enrichment_runs (job_id);

CREATE TABLE job_identity_tombstones (
    job_id UUID NOT NULL,
    identity_type VARCHAR(40) NOT NULL,
    identity_key TEXT NOT NULL,
    evidence JSONB NOT NULL,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(job_id) REFERENCES jobs (id),
    UNIQUE (identity_key)
);

CREATE TABLE job_people (
    job_id UUID NOT NULL,
    person_id UUID NOT NULL,
    relationship_group VARCHAR(80) NOT NULL,
    evidence_classification VARCHAR(30) NOT NULL,
    supporting_references JSONB NOT NULL,
    explanation TEXT NOT NULL,
    checked_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (job_id, person_id),
    FOREIGN KEY(job_id) REFERENCES jobs (id),
    FOREIGN KEY(person_id) REFERENCES people (id)
);

CREATE TABLE job_sources (
    job_id UUID NOT NULL,
    source_registry_id UUID NOT NULL,
    external_id VARCHAR(255),
    source_url TEXT NOT NULL,
    employer_url TEXT,
    application_url TEXT,
    final_observed_url TEXT,
    last_seen TIMESTAMP WITH TIME ZONE NOT NULL,
    last_verified TIMESTAMP WITH TIME ZONE,
    availability VARCHAR(30) NOT NULL,
    link_evidence JSONB NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (source_registry_id, external_id),
    FOREIGN KEY(job_id) REFERENCES jobs (id),
    FOREIGN KEY(source_registry_id) REFERENCES source_registry (id)
);

CREATE INDEX ix_job_sources_job_id ON job_sources (job_id);

CREATE TABLE user_job_events (
    user_id UUID NOT NULL,
    job_id UUID NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    before JSONB NOT NULL,
    after JSONB NOT NULL,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
    operation_id VARCHAR(128) NOT NULL,
    actor VARCHAR(40) NOT NULL,
    correction_of_event_id UUID,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id),
    FOREIGN KEY(job_id) REFERENCES jobs (id),
    FOREIGN KEY(correction_of_event_id) REFERENCES user_job_events (id)
);

CREATE TABLE user_job_state (
    user_id UUID NOT NULL,
    job_id UUID NOT NULL,
    viewed_at TIMESTAMP WITH TIME ZONE,
    is_saved BOOLEAN NOT NULL,
    saved_at TIMESTAMP WITH TIME ZONE,
    dismissed_at TIMESTAMP WITH TIME ZONE,
    revision INTEGER NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (user_id, job_id),
    FOREIGN KEY(user_id) REFERENCES users (id),
    FOREIGN KEY(job_id) REFERENCES jobs (id)
);

CREATE INDEX ix_saved_user ON user_job_state (user_id, is_saved);

CREATE TABLE job_snapshots (
    job_id UUID NOT NULL,
    source_id UUID,
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
    structured_fields JSONB NOT NULL,
    description TEXT NOT NULL,
    raw_evidence_reference TEXT,
    content_hash VARCHAR(64) NOT NULL,
    content_complete BOOLEAN NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(job_id) REFERENCES jobs (id),
    FOREIGN KEY(source_id) REFERENCES job_sources (id)
);

CREATE INDEX ix_job_snapshots_job_id ON job_snapshots (job_id);

CREATE TABLE applications (
    user_id UUID NOT NULL,
    job_id UUID,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    application_url TEXT,
    source_url TEXT,
    external_identity TEXT,
    applied_at TIMESTAMP WITH TIME ZONE NOT NULL,
    applied_date_source VARCHAR(30) NOT NULL,
    current_status VARCHAR(30) NOT NULL,
    revision INTEGER NOT NULL,
    voided_at TIMESTAMP WITH TIME ZONE,
    selected_snapshot_id UUID,
    manual_description TEXT,
    notes TEXT NOT NULL,
    added_by_user BOOLEAN NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT application_status CHECK (current_status IN ('APPLIED','ASSESSMENT','INTERVIEWING','OFFER','REJECTED','WITHDRAWN','POSITION_CLOSED')),
    FOREIGN KEY(user_id) REFERENCES users (id),
    FOREIGN KEY(job_id) REFERENCES jobs (id),
    FOREIGN KEY(selected_snapshot_id) REFERENCES job_snapshots (id)
);

CREATE INDEX ix_applications_applied_at ON applications (applied_at);

CREATE INDEX ix_applications_user_id ON applications (user_id);

CREATE UNIQUE INDEX uq_active_application_external ON applications (user_id, external_identity) WHERE voided_at IS NULL AND external_identity IS NOT NULL;

CREATE UNIQUE INDEX uq_active_application_job ON applications (user_id, job_id) WHERE voided_at IS NULL AND job_id IS NOT NULL;

CREATE TABLE initial_deliveries (
    user_id UUID NOT NULL,
    job_id UUID NOT NULL,
    channel VARCHAR(15) NOT NULL,
    report_id UUID,
    snapshot_id UUID,
    alert_reference VARCHAR(255),
    delivered_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (user_id, job_id),
    CONSTRAINT delivery_channel CHECK (channel IN ('DAILY','PRIORITY')),
    FOREIGN KEY(user_id) REFERENCES users (id),
    FOREIGN KEY(job_id) REFERENCES jobs (id),
    FOREIGN KEY(report_id) REFERENCES reports (id),
    FOREIGN KEY(snapshot_id) REFERENCES job_snapshots (id)
);

CREATE TABLE job_evaluations (
    job_id UUID NOT NULL,
    snapshot_id UUID NOT NULL,
    user_id UUID,
    profile_version INTEGER NOT NULL,
    ruleset_version VARCHAR(80) NOT NULL,
    evaluated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    decision VARCHAR(30) NOT NULL,
    valid_until TIMESTAMP WITH TIME ZONE,
    evidence JSONB NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT evaluation_decision CHECK (decision IN ('ELIGIBLE','INELIGIBLE','NEEDS_REVIEW')),
    FOREIGN KEY(job_id) REFERENCES jobs (id),
    FOREIGN KEY(snapshot_id) REFERENCES job_snapshots (id),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_job_evaluations_job_id ON job_evaluations (job_id);

CREATE INDEX ix_job_evaluations_user_id ON job_evaluations (user_id);

CREATE INDEX ix_job_evaluations_valid_until ON job_evaluations (valid_until);

CREATE TABLE job_facts (
    snapshot_id UUID NOT NULL,
    field VARCHAR(80) NOT NULL,
    value JSONB NOT NULL,
    fact_state VARCHAR(30) NOT NULL,
    requiredness VARCHAR(40),
    polarity VARCHAR(30),
    evidence JSONB NOT NULL,
    extractor_version VARCHAR(80) NOT NULL,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(snapshot_id) REFERENCES job_snapshots (id)
);

CREATE INDEX ix_job_facts_snapshot_id ON job_facts (snapshot_id);

CREATE TABLE saved_job_versions (
    user_id UUID NOT NULL,
    job_id UUID NOT NULL,
    snapshot_id UUID NOT NULL,
    saved_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ended_at TIMESTAMP WITH TIME ZONE,
    event_id UUID,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id),
    FOREIGN KEY(job_id) REFERENCES jobs (id),
    FOREIGN KEY(snapshot_id) REFERENCES job_snapshots (id),
    FOREIGN KEY(event_id) REFERENCES user_job_events (id)
);

CREATE TABLE application_events (
    application_id UUID NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    status VARCHAR(30),
    effective_at TIMESTAMP WITH TIME ZONE NOT NULL,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
    actor VARCHAR(30) NOT NULL,
    source_reference TEXT,
    evidence JSONB NOT NULL,
    operation_id VARCHAR(128) NOT NULL,
    correction_of_event_id UUID,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (application_id, operation_id),
    FOREIGN KEY(application_id) REFERENCES applications (id),
    FOREIGN KEY(correction_of_event_id) REFERENCES application_events (id)
);

CREATE INDEX ix_application_events_application_id ON application_events (application_id);

CREATE TABLE report_jobs (
    report_id UUID NOT NULL,
    job_id UUID NOT NULL,
    snapshot_id UUID NOT NULL,
    selection_band VARCHAR(1) NOT NULL,
    selection_order INTEGER NOT NULL,
    evaluation_id UUID NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (report_id, job_id),
    UNIQUE (report_id, selection_order),
    CONSTRAINT report_slot_limit CHECK (selection_order >= 0 AND selection_order < 50),
    FOREIGN KEY(report_id) REFERENCES reports (id),
    FOREIGN KEY(job_id) REFERENCES jobs (id),
    FOREIGN KEY(snapshot_id) REFERENCES job_snapshots (id),
    FOREIGN KEY(evaluation_id) REFERENCES job_evaluations (id)
);

CREATE TABLE rule_results (
    evaluation_id UUID NOT NULL,
    rule_code VARCHAR(80) NOT NULL,
    rule_version VARCHAR(80) NOT NULL,
    decision VARCHAR(30) NOT NULL,
    reason_code VARCHAR(100) NOT NULL,
    evidence JSONB NOT NULL,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT rule_decision CHECK (decision IN ('PASS','FAIL','UNKNOWN','REVIEW')),
    FOREIGN KEY(evaluation_id) REFERENCES job_evaluations (id)
);

CREATE INDEX ix_rule_results_evaluation_id ON rule_results (evaluation_id);

CREATE TABLE email_application_links (
    email_id UUID NOT NULL,
    application_id UUID NOT NULL,
    match_state VARCHAR(40) NOT NULL,
    evidence JSONB NOT NULL,
    event_id UUID,
    corrected_at TIMESTAMP WITH TIME ZONE,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    id UUID NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (email_id, application_id),
    FOREIGN KEY(email_id) REFERENCES email_messages (id),
    FOREIGN KEY(application_id) REFERENCES applications (id),
    FOREIGN KEY(event_id) REFERENCES application_events (id)
);

ALTER TABLE jobs ADD CONSTRAINT fk_job_current_snapshot FOREIGN KEY(current_snapshot_id) REFERENCES job_snapshots (id);

INSERT INTO alembic_version (version_num) VALUES ('0001_initial') RETURNING alembic_version.version_num;

-- Running upgrade 0001_initial -> 0002_history_guards

CREATE FUNCTION staffer_reject_history_update() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Retained evidence and event history are immutable' USING ERRCODE = '23514'; END;
    $$;

CREATE TRIGGER immutable_job_snapshots BEFORE UPDATE ON job_snapshots FOR EACH ROW EXECUTE FUNCTION staffer_reject_history_update();

CREATE TRIGGER immutable_job_facts BEFORE UPDATE ON job_facts FOR EACH ROW EXECUTE FUNCTION staffer_reject_history_update();

CREATE TRIGGER immutable_job_evaluations BEFORE UPDATE ON job_evaluations FOR EACH ROW EXECUTE FUNCTION staffer_reject_history_update();

CREATE TRIGGER immutable_rule_results BEFORE UPDATE ON rule_results FOR EACH ROW EXECUTE FUNCTION staffer_reject_history_update();

CREATE TRIGGER immutable_application_events BEFORE UPDATE ON application_events FOR EACH ROW EXECUTE FUNCTION staffer_reject_history_update();

CREATE TRIGGER immutable_user_job_events BEFORE UPDATE ON user_job_events FOR EACH ROW EXECUTE FUNCTION staffer_reject_history_update();

CREATE TRIGGER immutable_search_profile_versions BEFORE UPDATE ON search_profile_versions FOR EACH ROW EXECUTE FUNCTION staffer_reject_history_update();

CREATE TRIGGER immutable_initial_deliveries BEFORE UPDATE ON initial_deliveries FOR EACH ROW EXECUTE FUNCTION staffer_reject_history_update();

CREATE TRIGGER immutable_job_identity_tombstones BEFORE UPDATE ON job_identity_tombstones FOR EACH ROW EXECUTE FUNCTION staffer_reject_history_update();

CREATE FUNCTION staffer_report_membership_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE report_state text; group_identifier uuid; group_count int;
    BEGIN
      IF TG_OP != 'INSERT' THEN
        RAISE EXCEPTION 'Report membership is immutable' USING ERRCODE = '23514';
      END IF;
      SELECT status INTO report_state FROM reports WHERE id = NEW.report_id FOR UPDATE;
      IF report_state != 'BUILDING' THEN
        RAISE EXCEPTION 'Cannot add to a finalized report' USING ERRCODE = '23514';
      END IF;
      SELECT employer_group_id INTO group_identifier FROM jobs WHERE id=NEW.job_id;
      SELECT count(*) INTO group_count FROM report_jobs r JOIN jobs j ON j.id=r.job_id
        WHERE r.report_id=NEW.report_id AND j.employer_group_id=group_identifier;
      IF group_count >= 2 THEN
        RAISE EXCEPTION 'Two jobs per employer per report maximum' USING ERRCODE = '23514';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM job_snapshots WHERE id=NEW.snapshot_id AND job_id=NEW.job_id) THEN
        RAISE EXCEPTION 'Report snapshot must belong to job' USING ERRCODE = '23514';
      END IF;
      RETURN NEW;
    END; $$;

CREATE TRIGGER report_membership_guard BEFORE INSERT OR UPDATE OR DELETE ON report_jobs FOR EACH ROW EXECUTE FUNCTION staffer_report_membership_guard();

CREATE FUNCTION staffer_no_redirect_cycle() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE found_cycle boolean;
    BEGIN
      IF NEW.canonical_redirect_id IS NULL THEN RETURN NEW; END IF;
      -- Serialize identity edits across all canonical jobs, including concurrent two-node cycles.
      PERFORM pg_advisory_xact_lock(713824901);
      WITH RECURSIVE ancestors(id, path) AS (
        SELECT NEW.canonical_redirect_id, ARRAY[NEW.id]
        UNION ALL
        SELECT j.canonical_redirect_id, a.path || a.id FROM ancestors a JOIN jobs j ON j.id=a.id
          WHERE j.canonical_redirect_id IS NOT NULL AND NOT a.id=ANY(a.path)
      ) SELECT EXISTS(SELECT 1 FROM ancestors WHERE id=NEW.id) INTO found_cycle;
      IF found_cycle THEN RAISE EXCEPTION 'Canonical redirect cycle' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END; $$;

CREATE TRIGGER no_redirect_cycle BEFORE INSERT OR UPDATE OF canonical_redirect_id ON jobs FOR EACH ROW EXECUTE FUNCTION staffer_no_redirect_cycle();

UPDATE alembic_version SET version_num='0002_history_guards' WHERE alembic_version.version_num = '0001_initial';

-- Running upgrade 0002_history_guards -> 0003_pending_watchlist

ALTER TABLE watchlist_entries ADD COLUMN requested_name VARCHAR(255);

ALTER TABLE watchlist_entries ALTER COLUMN employer_group_id DROP NOT NULL;

ALTER TABLE watchlist_entries ADD CONSTRAINT watchlist_resolvable_identity CHECK (employer_group_id IS NOT NULL OR (requested_name IS NOT NULL AND length(requested_name) > 0));

UPDATE alembic_version SET version_num='0003_pending_watchlist' WHERE alembic_version.version_num = '0002_history_guards';

COMMIT;
