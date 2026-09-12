"""Initial authoritative PostgreSQL schema; frozen DDL, independent of future models."""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE TABLE employer_groups (\n\tcanonical_name VARCHAR(255) NOT NULL, \n\tnormalized_name VARCHAR(255) NOT NULL, \n\tgrouping_evidence JSONB NOT NULL, \n\tpool_tags JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)"
    )
    op.execute("CREATE INDEX ix_employer_groups_normalized_name ON employer_groups (normalized_name)")
    op.execute(
        "CREATE TABLE outbox_events (\n\tevent_key VARCHAR(255) NOT NULL, \n\tevent_type VARCHAR(80) NOT NULL, \n\tpayload JSONB NOT NULL, \n\tstate VARCHAR(30) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tnext_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlease_owner VARCHAR(255), \n\tlease_expires_at TIMESTAMP WITH TIME ZONE, \n\tdispatched_at TIMESTAMP WITH TIME ZONE, \n\tlast_error TEXT, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (event_key)\n)"
    )
    op.execute("CREATE INDEX ix_outbox_events_state ON outbox_events (state)")
    op.execute(
        "CREATE TABLE people (\n\tlinkedin_url TEXT NOT NULL, \n\tname VARCHAR(255) NOT NULL, \n\theadline TEXT NOT NULL, \n\tcompany VARCHAR(255) NOT NULL, \n\temployment_evidence JSONB NOT NULL, \n\tchecked_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (linkedin_url)\n)"
    )
    op.execute(
        "CREATE TABLE people_search_cache (\n\tquery_hash VARCHAR(64) NOT NULL, \n\tquery_text TEXT NOT NULL, \n\tresult_payload JSONB NOT NULL, \n\tobserved_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (query_hash)\n)"
    )
    op.execute(
        "CREATE TABLE users (\n\tgoogle_subject VARCHAR(255) NOT NULL, \n\tverified_email VARCHAR(320) NOT NULL, \n\tdisplay_name VARCHAR(255) NOT NULL, \n\ttimezone VARCHAR(80) NOT NULL, \n\tcycle_anchor DATE, \n\tis_admin BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (google_subject)\n)"
    )
    op.execute(
        "CREATE TABLE work_items (\n\ttask_key VARCHAR(255) NOT NULL, \n\ttask_type VARCHAR(80) NOT NULL, \n\tpayload JSONB NOT NULL, \n\tstate VARCHAR(30) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tnext_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlease_owner VARCHAR(255), \n\tlease_expires_at TIMESTAMP WITH TIME ZONE, \n\tresult JSONB, \n\tlast_error TEXT, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (task_key)\n)"
    )
    op.execute("CREATE INDEX ix_work_items_state ON work_items (state)")
    op.execute(
        "CREATE TABLE company_cycles (\n\tuser_id UUID NOT NULL, \n\tcycle_index INTEGER NOT NULL, \n\tstart_date DATE NOT NULL, \n\tend_date DATE NOT NULL, \n\tanchor_date DATE NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, cycle_index), \n\tCONSTRAINT cycle_interval CHECK (end_date > start_date), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)"
    )
    op.execute(
        "CREATE TABLE devices (\n\tuser_id UUID NOT NULL, \n\tplatform VARCHAR(30) NOT NULL, \n\tapp_version VARCHAR(50) NOT NULL, \n\tdevice_label VARCHAR(255) NOT NULL, \n\tpush_token_encrypted TEXT, \n\tlast_seen TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tsync_cursor BIGINT NOT NULL, \n\trevision INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)"
    )
    op.execute("CREATE INDEX ix_devices_user_id ON devices (user_id)")
    op.execute(
        "CREATE TABLE employer_brands (\n\tgroup_id UUID NOT NULL, \n\tdisplay_name VARCHAR(255) NOT NULL, \n\tcanonical_domain VARCHAR(255), \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(group_id) REFERENCES employer_groups (id)\n)"
    )
    op.execute("CREATE INDEX ix_employer_brands_group_id ON employer_brands (group_id)")
    op.execute(
        "CREATE TABLE gmail_connections (\n\tuser_id UUID NOT NULL, \n\tgoogle_identity VARCHAR(320) NOT NULL, \n\trefresh_token_encrypted TEXT, \n\tgranted_scopes JSONB NOT NULL, \n\tselected_label VARCHAR(255), \n\tsync_health VARCHAR(40) NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)"
    )
    op.execute(
        "CREATE TABLE login_intents (\n\tdevice_id UUID NOT NULL, \n\tpurpose VARCHAR(30) NOT NULL, \n\tselected_label VARCHAR(255), \n\tstate_hash VARCHAR(128) NOT NULL, \n\tchallenge VARCHAR(255) NOT NULL, \n\tnonce VARCHAR(255) NOT NULL, \n\tplatform VARCHAR(30) NOT NULL, \n\tdevice_label VARCHAR(255) NOT NULL, \n\tuser_id UUID, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\tredeemed_at TIMESTAMP WITH TIME ZONE, \n\tcode_verifier_encrypted TEXT, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (state_hash), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)"
    )
    op.execute(
        "CREATE TABLE notifications (\n\tuser_id UUID NOT NULL, \n\tnotification_type VARCHAR(50) NOT NULL, \n\ttarget_type VARCHAR(30) NOT NULL, \n\ttarget_id UUID NOT NULL, \n\ttitle TEXT NOT NULL, \n\tbody TEXT NOT NULL, \n\tevent_dedupe_key VARCHAR(255) NOT NULL, \n\tread_at TIMESTAMP WITH TIME ZONE, \n\trevision INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, event_dedupe_key), \n\tCONSTRAINT notification_target CHECK (target_type IN ('jobs','applications','reviews','reports','search-runs')), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)"
    )
    op.execute("CREATE INDEX ix_notifications_user_id ON notifications (user_id)")
    op.execute("CREATE INDEX ix_unread_notifications ON notifications (user_id, read_at)")
    op.execute(
        "CREATE TABLE processed_operations (\n\tuser_id UUID NOT NULL, \n\toperation_id VARCHAR(128) NOT NULL, \n\trequest_hash VARCHAR(64) NOT NULL, \n\tresponse JSONB NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, operation_id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)"
    )
    op.execute(
        "CREATE TABLE review_items (\n\tuser_id UUID NOT NULL, \n\treview_type VARCHAR(50) NOT NULL, \n\ttarget_id UUID, \n\treason TEXT NOT NULL, \n\tevidence JSONB NOT NULL, \n\tstate VARCHAR(30) NOT NULL, \n\tadmin_only BOOLEAN NOT NULL, \n\tresolved_at TIMESTAMP WITH TIME ZONE, \n\tresolution JSONB NOT NULL, \n\trevision INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)"
    )
    op.execute("CREATE INDEX ix_review_items_user_id ON review_items (user_id)")
    op.execute(
        "CREATE TABLE search_profile_versions (\n\tuser_id UUID NOT NULL, \n\tversion INTEGER NOT NULL, \n\tpayload JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, version), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)"
    )
    op.execute(
        "CREATE TABLE search_profiles (\n\tuser_id UUID NOT NULL, \n\tversion INTEGER NOT NULL, \n\trevision INTEGER NOT NULL, \n\trole_families JSONB NOT NULL, \n\tskills JSONB NOT NULL, \n\taliases JSONB NOT NULL, \n\tgeography JSONB NOT NULL, \n\twork_arrangements JSONB NOT NULL, \n\tsalary_preferences JSONB NOT NULL, \n\truleset_version VARCHAR(80) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)"
    )
    op.execute(
        "CREATE TABLE search_runs (\n\tuser_id UUID, \n\tscheduled_at TIMESTAMP WITH TIME ZONE, \n\tstarted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\tprofile_version INTEGER NOT NULL, \n\tstate VARCHAR(30) NOT NULL, \n\tcounts JSONB NOT NULL, \n\terrors JSONB NOT NULL, \n\tcoverage JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)"
    )
    op.execute("CREATE INDEX ix_search_runs_user_id ON search_runs (user_id)")
    op.execute(
        "CREATE TABLE source_registry (\n\tconnector_type VARCHAR(80) NOT NULL, \n\ttenant VARCHAR(255) NOT NULL, \n\temployer_group_id UUID, \n\tboard_identifier VARCHAR(255), \n\tcareer_url TEXT, \n\tgeography JSONB NOT NULL, \n\tpool_tags JSONB NOT NULL, \n\tconfiguration_state VARCHAR(40) NOT NULL, \n\tcapabilities JSONB NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tlast_success TIMESTAMP WITH TIME ZONE, \n\tlast_error TEXT, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (connector_type, tenant), \n\tCONSTRAINT no_linkedin_source CHECK (connector_type != 'linkedin'), \n\tFOREIGN KEY(employer_group_id) REFERENCES employer_groups (id)\n)"
    )
    op.execute(
        "CREATE TABLE sync_snapshots (\n\tuser_id UUID NOT NULL, \n\tboundary_cursor BIGINT NOT NULL, \n\titems JSONB NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)"
    )
    op.execute("CREATE INDEX ix_sync_snapshots_expires_at ON sync_snapshots (expires_at)")
    op.execute("CREATE INDEX ix_sync_snapshots_user_id ON sync_snapshots (user_id)")
    op.execute(
        "CREATE TABLE user_changes (\n\tcursor BIGINT GENERATED BY DEFAULT AS IDENTITY, \n\tuser_id UUID NOT NULL, \n\tentity_type VARCHAR(50) NOT NULL, \n\tentity_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\ttombstone BOOLEAN NOT NULL, \n\tcommitted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (cursor), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)"
    )
    op.execute("CREATE INDEX ix_user_change_cursor ON user_changes (user_id, cursor)")
    op.execute("CREATE INDEX ix_user_changes_user_id ON user_changes (user_id)")
    op.execute(
        "CREATE TABLE watchlist_entries (\n\tuser_id UUID NOT NULL, \n\temployer_group_id UUID NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\trevision INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, employer_group_id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(employer_group_id) REFERENCES employer_groups (id)\n)"
    )
    op.execute(
        "CREATE TABLE app_sessions (\n\tuser_id UUID NOT NULL, \n\tdevice_id UUID NOT NULL, \n\trefresh_token_hash VARCHAR(128) NOT NULL, \n\taccess_token_hash VARCHAR(128), \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\taccess_expires_at TIMESTAMP WITH TIME ZONE, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tlast_used_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(device_id) REFERENCES devices (id), \n\tUNIQUE (refresh_token_hash), \n\tUNIQUE (access_token_hash)\n)"
    )
    op.execute("CREATE INDEX ix_app_sessions_user_id ON app_sessions (user_id)")
    op.execute(
        "CREATE TABLE connector_runs (\n\tsearch_run_id UUID NOT NULL, \n\tsource_registry_id UUID NOT NULL, \n\tquery JSONB NOT NULL, \n\tpool VARCHAR(80), \n\tstarted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\tcursor TEXT, \n\tcounts JSONB NOT NULL, \n\terrors JSONB NOT NULL, \n\thealth VARCHAR(40) NOT NULL, \n\tcoverage JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(search_run_id) REFERENCES search_runs (id), \n\tFOREIGN KEY(source_registry_id) REFERENCES source_registry (id)\n)"
    )
    op.execute(
        "CREATE TABLE email_messages (\n\tconnection_id UUID NOT NULL, \n\tgmail_message_id VARCHAR(255) NOT NULL, \n\tthread_id VARCHAR(255) NOT NULL, \n\tsender TEXT NOT NULL, \n\tsubject TEXT NOT NULL, \n\texcerpt TEXT NOT NULL, \n\treceived_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tclassification VARCHAR(50) NOT NULL, \n\tevidence JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (connection_id, gmail_message_id), \n\tFOREIGN KEY(connection_id) REFERENCES gmail_connections (id)\n)"
    )
    op.execute("CREATE INDEX ix_email_messages_thread_id ON email_messages (thread_id)")
    op.execute(
        "CREATE TABLE employer_entities (\n\tgroup_id UUID NOT NULL, \n\tbrand_id UUID, \n\tlegal_name VARCHAR(255) NOT NULL, \n\tjurisdiction VARCHAR(255), \n\taddress_evidence JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(group_id) REFERENCES employer_groups (id), \n\tFOREIGN KEY(brand_id) REFERENCES employer_brands (id)\n)"
    )
    op.execute("CREATE INDEX ix_employer_entities_group_id ON employer_entities (group_id)")
    op.execute("CREATE INDEX ix_employer_entities_legal_name ON employer_entities (legal_name)")
    op.execute(
        "CREATE TABLE gmail_sync_state (\n\tconnection_id UUID NOT NULL, \n\thistory_cursor VARCHAR(255), \n\treconciliation_progress JSONB NOT NULL, \n\tlast_success TIMESTAMP WITH TIME ZONE, \n\twatch_expiry TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (connection_id), \n\tFOREIGN KEY(connection_id) REFERENCES gmail_connections (id)\n)"
    )
    op.execute(
        "CREATE TABLE notification_deliveries (\n\tnotification_id UUID NOT NULL, \n\tdevice_id UUID NOT NULL, \n\tchannel VARCHAR(30) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tstate VARCHAR(30) NOT NULL, \n\tlast_attempt TIMESTAMP WITH TIME ZONE, \n\tprovider_reference TEXT, \n\tlast_error TEXT, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (notification_id, device_id, channel), \n\tFOREIGN KEY(notification_id) REFERENCES notifications (id), \n\tFOREIGN KEY(device_id) REFERENCES devices (id)\n)"
    )
    op.execute(
        "CREATE TABLE reports (\n\tuser_id UUID NOT NULL, \n\treport_date DATE NOT NULL, \n\tcycle_id UUID NOT NULL, \n\tintended_release TIMESTAMP WITH TIME ZONE NOT NULL, \n\tactual_release TIMESTAMP WITH TIME ZONE, \n\tstatus VARCHAR(30) NOT NULL, \n\tprofile_version INTEGER NOT NULL, \n\tsummary JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, report_date), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(cycle_id) REFERENCES company_cycles (id)\n)"
    )
    op.execute(
        "CREATE TABLE company_cycle_usage (\n\tuser_id UUID NOT NULL, \n\tcycle_id UUID NOT NULL, \n\temployer_group_id UUID NOT NULL, \n\treport_id UUID NOT NULL, \n\treport_date DATE NOT NULL, \n\tcount INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, cycle_id, employer_group_id), \n\tCONSTRAINT company_daily_limit CHECK (count >= 1 AND count <= 2), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(cycle_id) REFERENCES company_cycles (id), \n\tFOREIGN KEY(employer_group_id) REFERENCES employer_groups (id), \n\tFOREIGN KEY(report_id) REFERENCES reports (id)\n)"
    )
    op.execute(
        "CREATE TABLE employer_aliases (\n\tgroup_id UUID, \n\tentity_id UUID, \n\tnormalized_alias VARCHAR(255) NOT NULL, \n\talias_type VARCHAR(30) NOT NULL, \n\tevidence JSONB NOT NULL, \n\tchecked_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\treviewer VARCHAR(255) NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(group_id) REFERENCES employer_groups (id), \n\tFOREIGN KEY(entity_id) REFERENCES employer_entities (id)\n)"
    )
    op.execute("CREATE INDEX ix_employer_aliases_normalized_alias ON employer_aliases (normalized_alias)")
    op.execute(
        "CREATE TABLE everify_evidence (\n\tentity_id UUID NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tlegal_name_as_found VARCHAR(255) NOT NULL, \n\tsource_reference TEXT NOT NULL, \n\tsnapshot TEXT NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\tchecked_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trecheck_due_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tverification_method VARCHAR(80) NOT NULL, \n\treviewer VARCHAR(255) NOT NULL, \n\tsynthetic BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT everify_status CHECK (status IN ('CONFIRMED','UNKNOWN','CONFLICTING','NO_LONGER_CONFIRMED')), \n\tCONSTRAINT everify_proof CHECK (status != 'CONFIRMED' OR (length(source_reference)>0 AND length(snapshot)>0 AND length(content_hash)=64 AND length(reviewer)>0)), \n\tFOREIGN KEY(entity_id) REFERENCES employer_entities (id)\n)"
    )
    op.execute("CREATE INDEX ix_everify_evidence_entity_id ON everify_evidence (entity_id)")
    op.execute("CREATE INDEX ix_everify_evidence_recheck_due_at ON everify_evidence (recheck_due_at)")
    op.execute(
        "CREATE TABLE jobs (\n\temployer_group_id UUID NOT NULL, \n\tentity_id UUID, \n\ttitle TEXT NOT NULL, \n\tlocations JSONB NOT NULL, \n\twork_arrangement VARCHAR(30), \n\trequisition_id VARCHAR(255), \n\tpublished_at TIMESTAMP WITH TIME ZONE, \n\tpublished_earliest TIMESTAMP WITH TIME ZONE, \n\tpublished_latest TIMESTAMP WITH TIME ZONE, \n\tpublication_precision VARCHAR(40) NOT NULL, \n\tsource_updated_at TIMESTAMP WITH TIME ZONE, \n\tlast_published_at TIMESTAMP WITH TIME ZONE, \n\tfirst_seen TIMESTAMP WITH TIME ZONE NOT NULL, \n\tavailability VARCHAR(30) NOT NULL, \n\tcurrent_snapshot_id UUID, \n\tcanonical_redirect_id UUID, \n\tsalary_min NUMERIC(14, 2), \n\tsalary_max NUMERIC(14, 2), \n\tsalary_currency VARCHAR(5), \n\tsalary_interval VARCHAR(30), \n\tpriority_reasons JSONB NOT NULL, \n\trole_family VARCHAR(100), \n\tsynthetic BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT job_availability CHECK (availability IN ('ACTIVE','CLOSED','UNKNOWN')), \n\tCONSTRAINT no_self_redirect CHECK (canonical_redirect_id IS NULL OR canonical_redirect_id != id), \n\tFOREIGN KEY(employer_group_id) REFERENCES employer_groups (id), \n\tFOREIGN KEY(entity_id) REFERENCES employer_entities (id), \n\tFOREIGN KEY(canonical_redirect_id) REFERENCES jobs (id)\n)"
    )
    op.execute("CREATE INDEX ix_jobs_employer_group_id ON jobs (employer_group_id)")
    op.execute("CREATE INDEX ix_jobs_published_at ON jobs (published_at)")
    op.execute(
        "CREATE TABLE duplicate_links (\n\tcandidate_id UUID NOT NULL, \n\tcanonical_id UUID NOT NULL, \n\tlink_type VARCHAR(40) NOT NULL, \n\tevidence JSONB NOT NULL, \n\tmechanism VARCHAR(255) NOT NULL, \n\treversed_by_id UUID, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT no_self_duplicate CHECK (candidate_id != canonical_id), \n\tFOREIGN KEY(candidate_id) REFERENCES jobs (id), \n\tFOREIGN KEY(canonical_id) REFERENCES jobs (id), \n\tFOREIGN KEY(reversed_by_id) REFERENCES duplicate_links (id)\n)"
    )
    op.execute(
        "CREATE TABLE enrichment_runs (\n\tstarted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tjob_id UUID NOT NULL, \n\tstate VARCHAR(40) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tquery_count INTEGER NOT NULL, \n\tdiscovered_count INTEGER NOT NULL, \n\tapproved_count INTEGER NOT NULL, \n\tcost_units NUMERIC(14, 4) NOT NULL, \n\tlast_error TEXT, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id)\n)"
    )
    op.execute("CREATE INDEX ix_enrichment_runs_job_id ON enrichment_runs (job_id)")
    op.execute(
        "CREATE TABLE job_identity_tombstones (\n\tjob_id UUID NOT NULL, \n\tidentity_type VARCHAR(40) NOT NULL, \n\tidentity_key TEXT NOT NULL, \n\tevidence JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id), \n\tUNIQUE (identity_key)\n)"
    )
    op.execute(
        "CREATE TABLE job_people (\n\tjob_id UUID NOT NULL, \n\tperson_id UUID NOT NULL, \n\trelationship_group VARCHAR(80) NOT NULL, \n\tevidence_classification VARCHAR(30) NOT NULL, \n\tsupporting_references JSONB NOT NULL, \n\texplanation TEXT NOT NULL, \n\tchecked_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (job_id, person_id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id), \n\tFOREIGN KEY(person_id) REFERENCES people (id)\n)"
    )
    op.execute(
        "CREATE TABLE job_sources (\n\tjob_id UUID NOT NULL, \n\tsource_registry_id UUID NOT NULL, \n\texternal_id VARCHAR(255), \n\tsource_url TEXT NOT NULL, \n\temployer_url TEXT, \n\tapplication_url TEXT, \n\tfinal_observed_url TEXT, \n\tlast_seen TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_verified TIMESTAMP WITH TIME ZONE, \n\tavailability VARCHAR(30) NOT NULL, \n\tlink_evidence JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (source_registry_id, external_id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id), \n\tFOREIGN KEY(source_registry_id) REFERENCES source_registry (id)\n)"
    )
    op.execute("CREATE INDEX ix_job_sources_job_id ON job_sources (job_id)")
    op.execute(
        "CREATE TABLE user_job_events (\n\tuser_id UUID NOT NULL, \n\tjob_id UUID NOT NULL, \n\tevent_type VARCHAR(50) NOT NULL, \n\tbefore JSONB NOT NULL, \n\tafter JSONB NOT NULL, \n\trecorded_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\toperation_id VARCHAR(128) NOT NULL, \n\tactor VARCHAR(40) NOT NULL, \n\tcorrection_of_event_id UUID, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id), \n\tFOREIGN KEY(correction_of_event_id) REFERENCES user_job_events (id)\n)"
    )
    op.execute(
        "CREATE TABLE user_job_state (\n\tuser_id UUID NOT NULL, \n\tjob_id UUID NOT NULL, \n\tviewed_at TIMESTAMP WITH TIME ZONE, \n\tis_saved BOOLEAN NOT NULL, \n\tsaved_at TIMESTAMP WITH TIME ZONE, \n\tdismissed_at TIMESTAMP WITH TIME ZONE, \n\trevision INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, job_id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id)\n)"
    )
    op.execute("CREATE INDEX ix_saved_user ON user_job_state (user_id, is_saved)")
    op.execute(
        "CREATE TABLE job_snapshots (\n\tjob_id UUID NOT NULL, \n\tsource_id UUID, \n\tfetched_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tstructured_fields JSONB NOT NULL, \n\tdescription TEXT NOT NULL, \n\traw_evidence_reference TEXT, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\tcontent_complete BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id), \n\tFOREIGN KEY(source_id) REFERENCES job_sources (id)\n)"
    )
    op.execute("CREATE INDEX ix_job_snapshots_job_id ON job_snapshots (job_id)")
    op.execute(
        "CREATE TABLE applications (\n\tuser_id UUID NOT NULL, \n\tjob_id UUID, \n\ttitle TEXT NOT NULL, \n\tcompany TEXT NOT NULL, \n\tapplication_url TEXT, \n\tsource_url TEXT, \n\texternal_identity TEXT, \n\tapplied_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tapplied_date_source VARCHAR(30) NOT NULL, \n\tcurrent_status VARCHAR(30) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tvoided_at TIMESTAMP WITH TIME ZONE, \n\tselected_snapshot_id UUID, \n\tmanual_description TEXT, \n\tnotes TEXT NOT NULL, \n\tadded_by_user BOOLEAN NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT application_status CHECK (current_status IN ('APPLIED','ASSESSMENT','INTERVIEWING','OFFER','REJECTED','WITHDRAWN','POSITION_CLOSED')), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id), \n\tFOREIGN KEY(selected_snapshot_id) REFERENCES job_snapshots (id)\n)"
    )
    op.execute("CREATE INDEX ix_applications_applied_at ON applications (applied_at)")
    op.execute("CREATE INDEX ix_applications_user_id ON applications (user_id)")
    op.execute(
        "CREATE UNIQUE INDEX uq_active_application_external ON applications (user_id, external_identity) WHERE voided_at IS NULL AND external_identity IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_active_application_job ON applications (user_id, job_id) WHERE voided_at IS NULL AND job_id IS NOT NULL"
    )
    op.execute(
        "CREATE TABLE initial_deliveries (\n\tuser_id UUID NOT NULL, \n\tjob_id UUID NOT NULL, \n\tchannel VARCHAR(15) NOT NULL, \n\treport_id UUID, \n\tsnapshot_id UUID, \n\talert_reference VARCHAR(255), \n\tdelivered_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, job_id), \n\tCONSTRAINT delivery_channel CHECK (channel IN ('DAILY','PRIORITY')), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id), \n\tFOREIGN KEY(report_id) REFERENCES reports (id), \n\tFOREIGN KEY(snapshot_id) REFERENCES job_snapshots (id)\n)"
    )
    op.execute(
        "CREATE TABLE job_evaluations (\n\tjob_id UUID NOT NULL, \n\tsnapshot_id UUID NOT NULL, \n\tuser_id UUID, \n\tprofile_version INTEGER NOT NULL, \n\truleset_version VARCHAR(80) NOT NULL, \n\tevaluated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdecision VARCHAR(30) NOT NULL, \n\tvalid_until TIMESTAMP WITH TIME ZONE, \n\tevidence JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT evaluation_decision CHECK (decision IN ('ELIGIBLE','INELIGIBLE','NEEDS_REVIEW')), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id), \n\tFOREIGN KEY(snapshot_id) REFERENCES job_snapshots (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)"
    )
    op.execute("CREATE INDEX ix_job_evaluations_job_id ON job_evaluations (job_id)")
    op.execute("CREATE INDEX ix_job_evaluations_user_id ON job_evaluations (user_id)")
    op.execute("CREATE INDEX ix_job_evaluations_valid_until ON job_evaluations (valid_until)")
    op.execute(
        "CREATE TABLE job_facts (\n\tsnapshot_id UUID NOT NULL, \n\tfield VARCHAR(80) NOT NULL, \n\tvalue JSONB NOT NULL, \n\tfact_state VARCHAR(30) NOT NULL, \n\trequiredness VARCHAR(40), \n\tpolarity VARCHAR(30), \n\tevidence JSONB NOT NULL, \n\textractor_version VARCHAR(80) NOT NULL, \n\tobserved_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(snapshot_id) REFERENCES job_snapshots (id)\n)"
    )
    op.execute("CREATE INDEX ix_job_facts_snapshot_id ON job_facts (snapshot_id)")
    op.execute(
        "CREATE TABLE saved_job_versions (\n\tuser_id UUID NOT NULL, \n\tjob_id UUID NOT NULL, \n\tsnapshot_id UUID NOT NULL, \n\tsaved_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tended_at TIMESTAMP WITH TIME ZONE, \n\tevent_id UUID, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id), \n\tFOREIGN KEY(snapshot_id) REFERENCES job_snapshots (id), \n\tFOREIGN KEY(event_id) REFERENCES user_job_events (id)\n)"
    )
    op.execute(
        "CREATE TABLE application_events (\n\tapplication_id UUID NOT NULL, \n\tevent_type VARCHAR(50) NOT NULL, \n\tstatus VARCHAR(30), \n\teffective_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trecorded_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tactor VARCHAR(30) NOT NULL, \n\tsource_reference TEXT, \n\tevidence JSONB NOT NULL, \n\toperation_id VARCHAR(128) NOT NULL, \n\tcorrection_of_event_id UUID, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (application_id, operation_id), \n\tFOREIGN KEY(application_id) REFERENCES applications (id), \n\tFOREIGN KEY(correction_of_event_id) REFERENCES application_events (id)\n)"
    )
    op.execute("CREATE INDEX ix_application_events_application_id ON application_events (application_id)")
    op.execute(
        "CREATE TABLE report_jobs (\n\treport_id UUID NOT NULL, \n\tjob_id UUID NOT NULL, \n\tsnapshot_id UUID NOT NULL, \n\tselection_band VARCHAR(1) NOT NULL, \n\tselection_order INTEGER NOT NULL, \n\tevaluation_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (report_id, job_id), \n\tUNIQUE (report_id, selection_order), \n\tCONSTRAINT report_slot_limit CHECK (selection_order >= 0 AND selection_order < 50), \n\tFOREIGN KEY(report_id) REFERENCES reports (id), \n\tFOREIGN KEY(job_id) REFERENCES jobs (id), \n\tFOREIGN KEY(snapshot_id) REFERENCES job_snapshots (id), \n\tFOREIGN KEY(evaluation_id) REFERENCES job_evaluations (id)\n)"
    )
    op.execute(
        "CREATE TABLE rule_results (\n\tevaluation_id UUID NOT NULL, \n\trule_code VARCHAR(80) NOT NULL, \n\trule_version VARCHAR(80) NOT NULL, \n\tdecision VARCHAR(30) NOT NULL, \n\treason_code VARCHAR(100) NOT NULL, \n\tevidence JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT rule_decision CHECK (decision IN ('PASS','FAIL','UNKNOWN','REVIEW')), \n\tFOREIGN KEY(evaluation_id) REFERENCES job_evaluations (id)\n)"
    )
    op.execute("CREATE INDEX ix_rule_results_evaluation_id ON rule_results (evaluation_id)")
    op.execute(
        "CREATE TABLE email_application_links (\n\temail_id UUID NOT NULL, \n\tapplication_id UUID NOT NULL, \n\tmatch_state VARCHAR(40) NOT NULL, \n\tevidence JSONB NOT NULL, \n\tevent_id UUID, \n\tcorrected_at TIMESTAMP WITH TIME ZONE, \n\treviewed_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (email_id, application_id), \n\tFOREIGN KEY(email_id) REFERENCES email_messages (id), \n\tFOREIGN KEY(application_id) REFERENCES applications (id), \n\tFOREIGN KEY(event_id) REFERENCES application_events (id)\n)"
    )
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT fk_job_current_snapshot FOREIGN KEY(current_snapshot_id) REFERENCES job_snapshots (id)"
    )


def downgrade():
    op.drop_constraint("fk_job_current_snapshot", "jobs", type_="foreignkey")
    op.drop_table("email_application_links")
    op.drop_table("rule_results")
    op.drop_table("report_jobs")
    op.drop_table("application_events")
    op.drop_table("saved_job_versions")
    op.drop_table("job_facts")
    op.drop_table("job_evaluations")
    op.drop_table("initial_deliveries")
    op.drop_table("applications")
    op.drop_table("job_snapshots")
    op.drop_table("user_job_state")
    op.drop_table("user_job_events")
    op.drop_table("job_sources")
    op.drop_table("job_people")
    op.drop_table("job_identity_tombstones")
    op.drop_table("enrichment_runs")
    op.drop_table("duplicate_links")
    op.drop_table("jobs")
    op.drop_table("everify_evidence")
    op.drop_table("employer_aliases")
    op.drop_table("company_cycle_usage")
    op.drop_table("reports")
    op.drop_table("notification_deliveries")
    op.drop_table("gmail_sync_state")
    op.drop_table("employer_entities")
    op.drop_table("email_messages")
    op.drop_table("connector_runs")
    op.drop_table("app_sessions")
    op.drop_table("watchlist_entries")
    op.drop_table("user_changes")
    op.drop_table("sync_snapshots")
    op.drop_table("source_registry")
    op.drop_table("search_runs")
    op.drop_table("search_profiles")
    op.drop_table("search_profile_versions")
    op.drop_table("review_items")
    op.drop_table("processed_operations")
    op.drop_table("notifications")
    op.drop_table("login_intents")
    op.drop_table("gmail_connections")
    op.drop_table("employer_brands")
    op.drop_table("devices")
    op.drop_table("company_cycles")
    op.drop_table("work_items")
    op.drop_table("users")
    op.drop_table("people_search_cache")
    op.drop_table("people")
    op.drop_table("outbox_events")
    op.drop_table("employer_groups")
