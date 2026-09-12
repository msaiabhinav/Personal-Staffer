"""Driver ordering/budgets with deterministic connectors; these are not SQL tests."""

from collections import Counter
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_eligibility_corpus import NOW
from test_pipeline_mapping import normalized, opening

from app.connectors.contracts import Candidate, DiscoverResult, FetchResult, Health
from app.jobs.orchestration import _drive_run, _summarize_health, run_source_batched
from app.jobs.pipeline import _verified_startup_pool
from app.workers.schedule import source_interval


class MemoryCheckpoint:
    """Explicit driver test double; real transaction behavior has separate PG tests."""

    def __init__(self, *, max_pages=20, max_candidates=500):
        self.run_id = uuid4()
        self.query = ""
        self.source = {"type": "fixture", "tenant": "synthetic"}
        self.limits = {"max_pages": max_pages, "max_candidates": max_candidates, "max_elapsed_seconds": 600}
        self.state = {
            "counts": {},
            "errors": [],
            "coverage": {"seen": [], "processed": {}, "pages_completed": 0},
            "cursor": None,
        }
        self.events = []

    def heartbeat(self):
        self.events.append("CHECKPOINT")

    def page(self, discovery):
        seen = set(self.state["coverage"]["seen"])
        before = len(seen)
        for candidate in discovery.candidates:
            if len(seen) < self.limits["max_candidates"]:
                seen.add(candidate.external_id)
        self.state["coverage"]["seen"] = sorted(seen)
        counts = Counter(self.state["counts"])
        counts["discovered"] += len(seen) - before
        counts["raw_discovered"] += len(discovery.candidates)
        self.state["counts"] = dict(counts)
        self.state["errors"].extend(error.model_dump(mode="json") for error in discovery.errors)
        self.events.append("PAGE_COMMIT")

    def candidate(self, candidate, *, normalized=None, opening=None, increments=None, errors=(), availability=None):
        if candidate.external_id in self.state["coverage"]["processed"]:
            return False
        counts = Counter(self.state["counts"])
        counts.update(increments or {})
        counts["persisted"] += int(normalized is not None)
        self.state["counts"] = dict(counts)
        self.state["errors"].extend(errors)
        self.state["coverage"]["processed"][candidate.external_id] = "COMMITTED" if normalized else "FAILED"
        self.events.append("CANDIDATE_COMMIT:" + candidate.external_id)
        return True

    def failure(self, errors, increments=None):
        self.state["errors"].extend(errors)
        counts = Counter(self.state["counts"])
        counts.update(increments or {})
        self.state["counts"] = dict(counts)

    def complete_page(self, cursor):
        self.state["coverage"]["pages_completed"] += 1
        self.state["cursor"] = cursor

    def finish(self, health, *, terminal_complete=None):
        state = _summarize_health(health, self.state["errors"], terminal_complete)
        self.events.append("RUN_COMMIT")
        return SimpleNamespace(
            state="SUCCEEDED" if state == "HEALTHY" else "PARTIAL",
            counts=self.state["counts"],
            errors=self.state["errors"],
            complete_listing=terminal_complete,
        )


class FixtureConnector:
    def __init__(self, store, ids=("one", "two"), *, complete=True, health="HEALTHY", next_cursor=None, fail_id=None):
        self.store, self.ids, self.complete, self.next_cursor, self.fail_id = store, ids, complete, next_cursor, fail_id
        self.state = health
        self.fetches = []
        self.discoveries = 0

    def discover(self, query, tenant, cursor):
        self.store.events.append("NETWORK_DISCOVER")
        self.discoveries += 1
        return DiscoverResult(
            candidates=[
                Candidate(
                    source_type="fixture",
                    tenant=tenant,
                    external_id=identifier,
                    source_url=f"https://fixture.invalid/{identifier}",
                )
                for identifier in self.ids
            ],
            next_cursor=self.next_cursor,
            coverage={"complete_listing": self.complete, "synthetic": True},
        )

    def fetch(self, candidate):
        self.store.events.append("NETWORK_FETCH:" + candidate.external_id)
        self.fetches.append(candidate.external_id)
        if candidate.external_id == self.fail_id:
            raise RuntimeError("Synthetic connector failure")
        return FetchResult(
            candidate=candidate, outcome="SUCCESS", source_url=candidate.source_url, description_complete=True
        )

    def normalize(self, fetched):
        return normalized(external_id=fetched.candidate.external_id, requisition_id=fetched.candidate.external_id)

    def verify_opening(self, normal):
        self.store.events.append("NETWORK_VERIFY:" + normal.external_id)
        return opening()

    def health(self):
        return Health(source_type="fixture", state=self.state)


def test_driver_commits_each_candidate_before_fetching_the_next():
    store = MemoryCheckpoint()
    connector = FixtureConnector(store)
    result = _drive_run(store, connector)
    assert result.state == "SUCCEEDED" and result.counts["persisted"] == 2
    events = store.events
    assert events.index("CANDIDATE_COMMIT:one") < events.index("NETWORK_FETCH:two")
    assert events.index("NETWORK_VERIFY:one") < events.index("CANDIDATE_COMMIT:one")


def test_retry_skips_atomically_committed_candidates_and_duplicate_discoveries():
    store = MemoryCheckpoint()
    store.state["coverage"].update({"seen": ["one"], "processed": {"one": "COMMITTED"}})
    store.state["counts"] = {"persisted": 1, "discovered": 1}
    connector = FixtureConnector(store, ids=("one", "two", "two"))
    result = _drive_run(store, connector)
    assert connector.fetches == ["two"]
    assert result.counts["persisted"] == 2 and result.counts["discovered"] == 2


@pytest.mark.parametrize("complete,health", [(False, "HEALTHY"), (True, "DEGRADED"), (True, "NOT_CONFIGURED")])
def test_empty_incomplete_or_unhealthy_listing_is_partial(complete, health):
    store = MemoryCheckpoint()
    connector = FixtureConnector(store, ids=(), complete=complete, health=health)
    assert _drive_run(store, connector).state == "PARTIAL"


def test_candidate_failure_preserves_other_committed_results():
    store = MemoryCheckpoint()
    connector = FixtureConnector(store, fail_id="two")
    result = _drive_run(store, connector)
    assert result.state == "PARTIAL" and result.counts["persisted"] == 1
    assert result.errors[0]["code"] == "CANDIDATE_EXCEPTION"
    assert "Synthetic connector failure" not in str(result.errors)  # Exception content is not retained.


def test_budgets_stop_further_fetch_and_page_requests():
    store = MemoryCheckpoint(max_candidates=1)
    connector = FixtureConnector(store)
    result = _drive_run(store, connector)
    assert connector.fetches == ["one"] and result.state == "PARTIAL"
    assert result.errors[-1]["code"] == "RUN_CANDIDATE_BUDGET_EXHAUSTED"
    store = MemoryCheckpoint(max_pages=1)
    connector = FixtureConnector(store, next_cursor="next")
    result = _drive_run(store, connector)
    assert connector.discoveries == 1 and result.errors[-1]["code"] == "RUN_PAGE_BUDGET_EXHAUSTED"


def test_repeated_cursor_stops_without_looping():
    store = MemoryCheckpoint()
    connector = FixtureConnector(store, next_cursor="same")
    result = _drive_run(store, connector)
    assert connector.discoveries == 2
    assert result.errors[-1]["code"] == "SOURCE_CURSOR_REPEATED"


def test_unreasonable_budgets_rejected_before_database_access():
    with pytest.raises(ValueError, match="budgets"):
        run_source_batched(lambda: None, uuid4(), uuid4(), max_candidates=501)


def test_jobspy_site_variants_get_the_bounded_cadence():
    assert source_interval(SimpleNamespace(pool_tags=[], connector_type="jobspy:indeed")) == 28800
    assert source_interval(SimpleNamespace(pool_tags=[], connector_type="jobspy:google")) == 28800
    assert source_interval(SimpleNamespace(pool_tags=[], connector_type="ashby")) == 14400


def test_startup_pool_requires_retained_company_evidence_and_preserves_job_location():
    group = SimpleNamespace(pool_tags=["NYC_VERIFIED"], grouping_evidence={})
    assert _verified_startup_pool(group) is None
    group.grouping_evidence = {
        "pool_evidence": {
            "NYC": {
                "source_reference": "https://fixture.invalid/about",
                "quoted_text": "Synthetic employer has a major New York City office.",
                "reviewer": "synthetic-reviewer",
                "checked_at": NOW.isoformat(),
                "company_location_kind": "MAJOR_OPERATING_OFFICE",
                "location": "New York City",
                "startup_basis": "Synthetic sourced startup description",
            }
        }
    }
    assert _verified_startup_pool(group) == "NYC"
    group.grouping_evidence["pool_evidence"]["NYC"]["company_location_kind"] = "JOB_WORKPLACE"
    assert _verified_startup_pool(group) is None
