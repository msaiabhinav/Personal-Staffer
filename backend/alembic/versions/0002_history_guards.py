"""Database guards for pinned immutable history, report limits, and duplicate cycles."""

from alembic import op

revision = "0002_history_guards"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION staffer_reject_history_update() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Retained evidence and event history are immutable' USING ERRCODE = '23514'; END;
    $$""")
    for table in (
        "job_snapshots",
        "job_facts",
        "job_evaluations",
        "rule_results",
        "application_events",
        "user_job_events",
        "search_profile_versions",
        "initial_deliveries",
        "job_identity_tombstones",
    ):
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION staffer_reject_history_update()"
        )
    op.execute("""CREATE FUNCTION staffer_report_membership_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
    END; $$""")
    op.execute(
        "CREATE TRIGGER report_membership_guard BEFORE INSERT OR UPDATE OR DELETE ON report_jobs FOR EACH ROW EXECUTE FUNCTION staffer_report_membership_guard()"
    )
    op.execute("""CREATE FUNCTION staffer_no_redirect_cycle() RETURNS trigger LANGUAGE plpgsql AS $$
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
    END; $$""")
    op.execute(
        "CREATE TRIGGER no_redirect_cycle BEFORE INSERT OR UPDATE OF canonical_redirect_id ON jobs FOR EACH ROW EXECUTE FUNCTION staffer_no_redirect_cycle()"
    )


def downgrade():
    op.execute("DROP TRIGGER no_redirect_cycle ON jobs")
    op.execute("DROP FUNCTION staffer_no_redirect_cycle()")
    op.execute("DROP TRIGGER report_membership_guard ON report_jobs")
    op.execute("DROP FUNCTION staffer_report_membership_guard()")
    for table in (
        "job_snapshots",
        "job_facts",
        "job_evaluations",
        "rule_results",
        "application_events",
        "user_job_events",
        "search_profile_versions",
        "initial_deliveries",
        "job_identity_tombstones",
    ):
        op.execute(f"DROP TRIGGER immutable_{table} ON {table}")
    op.execute("DROP FUNCTION staffer_reject_history_update()")
