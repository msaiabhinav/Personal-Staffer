"""Real PostgreSQL lock, checkpoint, crash/retry and Retry-After integration checks."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_database_core
import test_reports_database
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from test_pipeline_mapping import normalized, opening
from test_reports_database import seed_owner, seed_source

from app.connectors.contracts import Candidate, DiscoverResult, FetchResult, Health
from app.db.models import (
    ConnectorRun,
    EmployerGroup,
    Job,
    JobEvaluation,
    JobSnapshot,
    SearchRun,
    SourceRegistry,
    User,
    WorkItem,
)
from app.jobs.orchestration import run_source_batched
from app.workers.schedule import schedule_due

pg_engine = test_database_core.pg_engine
local_synthetic_mode = test_reports_database.local_synthetic_mode
pytestmark = pytest.mark.postgres


class DatabaseFixtureConnector:
    def __init__(
        self, engine, user_id, source_id, tenant, group_id, *, crash_on=None, state="HEALTHY", retry_after=None
    ):
        self.engine, self.user_id, self.source_id, self.tenant, self.group_id = (
            engine,
            user_id,
            source_id,
            tenant,
            group_id,
        )
        self.crash_on, self.state, self.retry_after = crash_on, state, retry_after
        self.fetches = []
        self.network_probes = 0

    def _probe_network_boundary(self):
        # This independent connection can acquire every interaction-critical lock
        # during provider I/O. A surrounding ingestion transaction would fail NOWAIT.
        with Session(self.engine) as session, session.begin():
            session.execute(select(User).where(User.id == self.user_id).with_for_update(nowait=True))
            session.execute(
                select(SourceRegistry).where(SourceRegistry.id == self.source_id).with_for_update(nowait=True)
            )
            session.execute(select(EmployerGroup).where(EmployerGroup.id == self.group_id).with_for_update(nowait=True))
        self.network_probes += 1

    def discover(self, query, tenant, cursor):
        self._probe_network_boundary()
        return DiscoverResult(
            candidates=[
                Candidate(
                    source_type="fixture",
                    tenant=tenant,
                    external_id=identifier,
                    source_url=f"https://fixture.invalid/{tenant}/{identifier}",
                )
                for identifier in ("one", "two")
            ],
            coverage={"complete_listing": True, "synthetic_only": True},
        )

    def fetch(self, candidate):
        self._probe_network_boundary()
        self.fetches.append(candidate.external_id)
        if candidate.external_id == self.crash_on:
            raise KeyboardInterrupt("Synthetic process death")
        return FetchResult(
            candidate=candidate, outcome="SUCCESS", source_url=candidate.source_url, description_complete=True
        )

    def normalize(self, fetched):
        return normalized(
            tenant=self.tenant,
            external_id=fetched.candidate.external_id,
            requisition_id=fetched.candidate.external_id,
            employer_url=f"https://fixture.invalid/{self.tenant}/{fetched.candidate.external_id}",
            application_url=f"https://fixture.invalid/{self.tenant}/{fetched.candidate.external_id}/apply",
        )

    def verify_opening(self, normal):
        self._probe_network_boundary()
        return opening(application_url=normal.application_url, final_url=normal.employer_url)

    def health(self):
        return Health(source_type="fixture", state=self.state, retry_after=self.retry_after)


def seeded(pg_engine):
    with Session(pg_engine) as session, session.begin():
        owner = seed_owner(session)
        source, _entity = seed_source(session)
        return owner.id, source.id, source.tenant, source.employer_group_id


def test_network_runs_without_user_source_or_group_locks_and_persists_counts(pg_engine):
    user, source, tenant, group = seeded(pg_engine)
    connector = DatabaseFixtureConnector(pg_engine, user, source, tenant, group)
    factory = sessionmaker(pg_engine, expire_on_commit=False)
    run = run_source_batched(factory, source, user, connector=connector)
    assert run.state == "SUCCEEDED" and run.counts["persisted"] == 2
    assert run.counts["NEEDS_REVIEW"] == 2  # No automatic legal-employer approval.
    assert connector.network_probes == 5
    assert run.coverage["page_coverages"][0]["synthetic_only"]
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 2
        assert session.scalar(select(func.count()).select_from(JobSnapshot)) == 2


def test_crash_after_first_commit_resumes_without_reingesting_it(pg_engine):
    user, source, tenant, group = seeded(pg_engine)
    factory = sessionmaker(pg_engine, expire_on_commit=False)
    run_id = uuid4()
    crashing = DatabaseFixtureConnector(pg_engine, user, source, tenant, group, crash_on="two")
    with pytest.raises(KeyboardInterrupt):
        run_source_batched(factory, source, user, connector=crashing, run_id=run_id)
    with Session(pg_engine) as session, session.begin():
        assert session.scalar(select(func.count()).select_from(Job)) == 1
        cr = session.scalar(select(ConnectorRun).where(ConnectorRun.search_run_id == run_id))
        assert cr.counts["persisted"] == 1 and cr.coverage["processed"]["one"] == "NEEDS_REVIEW"
        # Simulate lease expiry after a dead process; recovery does not erase progress.
        cr.coverage = {
            **cr.coverage,
            "lease": {"token": "dead", "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
        }
    resumed = DatabaseFixtureConnector(pg_engine, user, source, tenant, group)
    run = run_source_batched(factory, source, user, connector=resumed, run_id=run_id)
    assert resumed.fetches == ["two"] and run.counts["persisted"] == 2
    assert run_source_batched(factory, source, user, connector=resumed, run_id=run_id).id == run.id
    assert resumed.fetches == ["two"]
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 2
        assert session.scalar(select(func.count()).select_from(JobSnapshot)) == 2
        assert session.scalar(select(func.count()).select_from(SearchRun)) == 1


def test_retry_after_persists_skips_provider_and_prevents_early_schedule(pg_engine):
    user, source, tenant, group = seeded(pg_engine)
    factory = sessionmaker(pg_engine, expire_on_commit=False)
    retry_after = datetime.now(UTC) + timedelta(hours=1)
    limited = DatabaseFixtureConnector(
        pg_engine, user, source, tenant, group, state="RATE_LIMITED", retry_after=retry_after
    )
    run = run_source_batched(factory, source, user, connector=limited)
    assert run.state == "PARTIAL" and run.coverage["retry_after"] == retry_after.isoformat()
    blocked = DatabaseFixtureConnector(pg_engine, user, source, tenant, group)
    deferred = run_source_batched(factory, source, user, connector=blocked)
    assert deferred.state == "DEFERRED" and blocked.fetches == [] and blocked.network_probes == 0
    with Session(pg_engine) as session, session.begin():
        schedule_due(session, now=datetime.now(UTC))
        assert (
            session.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.task_type == "SEARCH_SOURCE")) == 0
        )


def test_rescan_of_unchanged_postings_appends_no_snapshot_or_evaluation(pg_engine):
    # Regression: the first live board (288 postings) accumulated ~5 evaluations per job within
    # minutes because every scheduled rescan re-ingested identical content.
    user, source, tenant, group = seeded(pg_engine)
    factory = sessionmaker(pg_engine, expire_on_commit=False)
    connector = DatabaseFixtureConnector(pg_engine, user, source, tenant, group)
    first = run_source_batched(factory, source, user, connector=connector)
    assert first.counts["persisted"] == 2
    second = run_source_batched(factory, source, user, connector=connector)
    assert second.id != first.id and second.counts["persisted"] == 2
    assert second.counts["NEEDS_REVIEW"] == 2  # Retained decisions are still reported per run.
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 2
        assert session.scalar(select(func.count()).select_from(JobSnapshot)) == 2
        assert session.scalar(select(func.count()).select_from(JobEvaluation)) == 2

    class ChangedConnector(DatabaseFixtureConnector):
        def normalize(self, fetched):
            base = super().normalize(fetched)
            return base.model_copy(update={"description_text": base.description_text + "\nUpdated: now hybrid."})

    changed = ChangedConnector(pg_engine, user, source, tenant, group)
    run_source_batched(factory, source, user, connector=changed)
    with Session(pg_engine) as session:
        # Changed content still produces a new immutable snapshot and evaluation per job.
        assert session.scalar(select(func.count()).select_from(JobSnapshot)) == 4
        assert session.scalar(select(func.count()).select_from(JobEvaluation)) == 4


def test_scheduler_runs_one_bounded_search_per_reviewed_query(pg_engine):
    from app.db.models import SourceRegistry
    from app.workers.schedule import source_queries

    _user, source, _tenant, _group = seeded(pg_engine)
    with Session(pg_engine) as session, session.begin():
        row = session.get(SourceRegistry, source)
        row.enabled = True
        row.capabilities = {**(row.capabilities or {}), "queries": [" analyst ", "data", "analyst", "", 7]}
        assert source_queries(row) == ["analyst", "data", "7"]
    with Session(pg_engine) as session, session.begin():
        schedule_due(session, now=datetime(2026, 9, 13, 12, tzinfo=UTC))
        items = session.scalars(select(WorkItem).where(WorkItem.task_type == "SEARCH_SOURCE")).all()
        by_query = {item.payload.get("query"): item.task_key for item in items}
        assert set(by_query) == {"analyst", "data", "7"}
        assert by_query["analyst"].endswith(str(source)) is False  # bucket suffix present
        assert not by_query["analyst"].endswith(":1") and by_query["data"].endswith(":1")
        assert by_query["7"].endswith(":2")
        assert all(item.payload["source_id"] == str(source) for item in items)
    with Session(pg_engine) as session, session.begin():
        row = session.get(SourceRegistry, source)
        row.capabilities = {"registered_by": "TEST"}
        assert source_queries(row) == [""]  # board sources: one run, no query key
