"""Bounded source runs with network I/O outside every PostgreSQL transaction.

Candidate identity persistence and its progress checkpoint commit together. Passing
an existing run_id resumes unfinished work or returns its finalized result. Redis
redelivery may repeat fetches; it cannot bypass source identities or delivery ledgers.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.connectors import get_connector
from app.connectors.contracts import Health
from app.db.models import ConnectorRun, Job, JobSource, SearchProfile, SearchRun, SourceRegistry, User, UserChange
from app.jobs.pipeline import ingest_normalized

MAX_ERROR_DETAILS = 100
LEASE_SECONDS = 300
TERMINAL_RUN_STATES = {"SUCCEEDED", "PARTIAL", "FAILED"}


class SourceRunBusy(RuntimeError):
    """A live lease owns the requested run; the durable worker may retry later."""


class SourceRunLeaseLost(RuntimeError):
    """An expired runner cannot overwrite the new runner's progress."""


class SourceStopped(RuntimeError):
    """An administrator disabled a source while its network call was in flight."""


def _aware(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value))
        return result if result.tzinfo is not None and result.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def _safe_error(code, message, *, stage=None, external_id=None, retry_after=None):
    item = {"code": code, "message": message}
    if stage:
        item["stage"] = stage
    if external_id:
        item["external_id"] = external_id
    if retry_after:
        item["retry_after"] = retry_after.isoformat() if isinstance(retry_after, datetime) else str(retry_after)
    return item


def _source_errors(errors, *, stage, external_id=None):
    return [
        dict(error.model_dump(mode="json"), stage=stage, **({"external_id": external_id} if external_id else {}))
        for error in errors
    ]


def _summarize_health(health: Health, errors, complete_listing):
    state = health.state
    if state == "HEALTHY" and (errors or complete_listing is False):
        state = "DEGRADED"
    return state


class SourceRunStore:
    """Small explicit transaction boundary. No connector/network calls occur here."""

    def __init__(self, factory, source_id, user_id, query, run_id, limits, *, clock=None):
        self.factory = factory
        self.source_id = source_id
        self.user_id = user_id
        self.query = query
        self.run_id = run_id or uuid4()
        self.lease_token = uuid4().hex
        self.clock = clock or (lambda: datetime.now(UTC))
        self.limits = limits
        self.state = {}
        self.source = {}
        self.final = None

    def start(self):
        # A deterministic run_id is the durable worker's idempotency identity. Resolve a
        # concurrent first insert by reloading its PK winner, not by creating another run.
        for attempt in range(2):
            try:
                return self._start()
            except IntegrityError:
                if attempt:
                    raise
        raise AssertionError("unreachable")

    def _start(self):
        now = self.clock()
        with self.factory() as session, session.begin():
            source = session.get(SourceRegistry, self.source_id)
            if source is None or session.get(User, self.user_id) is None:
                raise ValueError("Known source and user are required")
            self.source = {
                "id": source.id,
                "type": source.connector_type,
                "tenant": source.tenant,
                "enabled": source.enabled,
                "retry_after": (source.capabilities or {}).get("runtime_retry_after"),
            }
            run = session.scalar(select(SearchRun).where(SearchRun.id == self.run_id).with_for_update())
            if run is None:
                profile = session.scalar(select(SearchProfile).where(SearchProfile.user_id == self.user_id))
                run = SearchRun(
                    id=self.run_id,
                    user_id=self.user_id,
                    profile_version=profile.version if profile else 1,
                    started_at=now,
                    coverage={"source_id": str(source.id), "query": self.query, "transaction_mode": "PER_CANDIDATE"},
                )
                session.add(run)
                session.flush()
                cr = ConnectorRun(
                    search_run_id=run.id,
                    source_registry_id=source.id,
                    query={"query": self.query},
                    health="NOT_CONFIGURED",
                    started_at=now,
                    coverage={
                        "limits": self.limits,
                        "processed": {},
                        "seen": [],
                        "pages_completed": 0,
                        "page_coverages": [],
                        "error_count": 0,
                    },
                )
                session.add(cr)
                session.flush()
            else:
                if (
                    run.user_id != self.user_id
                    or run.coverage.get("source_id") != str(self.source_id)
                    or run.coverage.get("query", "") != self.query
                ):
                    raise ValueError("Run ID cannot be reused for a different owner/source/query")
                cr = session.scalar(select(ConnectorRun).where(ConnectorRun.search_run_id == run.id).with_for_update())
                if cr is None:
                    raise ValueError("Run checkpoint has no connector record")
                if run.state in TERMINAL_RUN_STATES:
                    session.expunge(run)
                    self.final = run
                    return self
            data = dict(cr.coverage or {})
            lease = data.get("lease", {})
            expiry = _aware(lease.get("expires_at"))
            if expiry and expiry > now and lease.get("token") != self.lease_token:
                raise SourceRunBusy("This source run has a live execution lease")
            data["lease"] = {
                "token": self.lease_token,
                "expires_at": (now + timedelta(seconds=LEASE_SECONDS)).isoformat(),
            }
            cr.coverage = data
            run.state = "RUNNING"
            self.cr_id = cr.id
            self._remember(run, cr)
        return self

    def _locked(self, session):
        run = session.scalar(select(SearchRun).where(SearchRun.id == self.run_id).with_for_update())
        cr = session.scalar(select(ConnectorRun).where(ConnectorRun.id == self.cr_id).with_for_update())
        if run is None or cr is None or (cr.coverage or {}).get("lease", {}).get("token") != self.lease_token:
            raise SourceRunLeaseLost("Source run lease was replaced")
        return run, cr

    def _remember(self, run, cr):
        self.state = {
            "counts": dict(run.counts or {}),
            "errors": list(run.errors or []),
            "coverage": dict(cr.coverage or {}),
            "cursor": cr.cursor,
        }
        self.limits = self.state["coverage"].get("limits", self.limits)

    def _write(self, run, cr, counts, data, errors=()):
        now = self.clock()
        all_errors = list(run.errors or [])
        data["error_count"] = data.get("error_count", 0) + len(errors)
        all_errors.extend(errors[: max(0, MAX_ERROR_DETAILS - len(all_errors))])
        data["lease"] = {"token": self.lease_token, "expires_at": (now + timedelta(seconds=LEASE_SECONDS)).isoformat()}
        run.counts = cr.counts = dict(counts)
        run.errors = cr.errors = all_errors
        cr.coverage = data
        # Keep public run coverage bounded and omit internal lease/processed identifiers.
        run.coverage = {
            **run.coverage,
            "limits": data.get("limits"),
            "pages_completed": data.get("pages_completed", 0),
            "page_coverages": data.get("page_coverages", []),
            "error_count": data.get("error_count", 0),
            "errors_truncated": data.get("error_count", 0) > MAX_ERROR_DETAILS,
            "next_cursor": cr.cursor,
        }
        self._remember(run, cr)

    def heartbeat(self):
        with self.factory() as session, session.begin():
            run, cr = self._locked(session)
            self._write(run, cr, Counter(run.counts or {}), dict(cr.coverage or {}))

    def page(self, discovery):
        with self.factory() as session, session.begin():
            run, cr = self._locked(session)
            data, counts = dict(cr.coverage or {}), Counter(run.counts or {})
            seen = set(data.get("seen", []))
            selected = []
            for candidate in discovery.candidates:
                key = candidate.external_id
                if key in seen:
                    continue
                if len(seen) >= self.limits["max_candidates"]:
                    break
                seen.add(key)
                selected.append(key)
            counts["raw_discovered"] += len(discovery.candidates)
            counts["discovered"] += len(selected)
            data["seen"] = sorted(seen)
            data["current_page_coverage"] = discovery.coverage
            self._write(run, cr, counts, data, _source_errors(discovery.errors, stage="DISCOVER"))
        return set(selected)

    def candidate(self, candidate, *, normalized=None, opening=None, increments=None, errors=(), availability=None):
        """The ingest outcome and processed checkpoint are one atomic transaction."""
        with self.factory() as session, session.begin():
            run, cr = self._locked(session)
            data, counts = dict(cr.coverage or {}), Counter(run.counts or {})
            processed = dict(data.get("processed", {}))
            if candidate.external_id in processed:
                self._remember(run, cr)
                return False
            source = session.get(SourceRegistry, self.source_id)
            if source is None or not source.enabled:
                raise SourceStopped("Source was disabled or removed during this run")
            counts.update(increments or {})
            if availability in {"CLOSED", "UNKNOWN"}:
                session.execute(select(User).where(User.id == self.user_id).with_for_update())
                retained = session.scalar(
                    select(JobSource)
                    .where(
                        JobSource.source_registry_id == self.source_id, JobSource.external_id == candidate.external_id
                    )
                    .with_for_update()
                )
                if retained:
                    job = session.scalar(select(Job).where(Job.id == retained.job_id).with_for_update())
                    retained.availability = job.availability = availability
                    retained.last_verified = self.clock()
                    retained.link_evidence = {
                        **(retained.link_evidence or {}),
                        "opening": {
                            "status": availability,
                            "application_url": retained.application_url,
                            "identity_match": False,
                            "actionable": False,
                            "checked_at": self.clock().isoformat(),
                            "evidence_text": "Source retrieval explicitly closed the opening"
                            if availability == "CLOSED"
                            else "Source retrieval is temporarily unverifiable",
                        },
                    }
                    session.add(UserChange(user_id=self.user_id, entity_type="jobs", entity_id=job.id, revision=1))
            outcome = "FETCH_FAILED"
            if normalized is not None:
                _, evaluation = ingest_normalized(session, source, normalized, opening, user_id=self.user_id)
                outcome = str(evaluation.decision)
                counts["persisted"] += 1
                counts[outcome] += 1
            processed[candidate.external_id] = outcome
            data["processed"] = processed
            self._write(run, cr, counts, data, errors)
        return True

    def failure(self, errors, increments=None):
        with self.factory() as session, session.begin():
            run, cr = self._locked(session)
            counts = Counter(run.counts or {})
            counts.update(increments or {})
            self._write(run, cr, counts, dict(cr.coverage or {}), errors)

    def complete_page(self, next_cursor):
        with self.factory() as session, session.begin():
            run, cr = self._locked(session)
            data = dict(cr.coverage or {})
            data["pages_completed"] = data.get("pages_completed", 0) + 1
            coverages = list(data.get("page_coverages", []))
            coverages.append(data.get("current_page_coverage", {}))
            data["page_coverages"] = coverages[-self.limits["max_pages"] :]
            cr.cursor = next_cursor
            self._write(run, cr, Counter(run.counts or {}), data)

    def release(self):
        with self.factory() as session, session.begin():
            _run, cr = self._locked(session)
            data = dict(cr.coverage or {})
            data["lease"] = {"token": self.lease_token, "expires_at": self.clock().isoformat()}
            cr.coverage = data

    def finish(self, health, *, terminal_complete=None, deferred=False):
        with self.factory() as session, session.begin():
            run, cr = self._locked(session)
            data = dict(cr.coverage or {})
            state = _summarize_health(health, run.errors or [], terminal_complete)
            if terminal_complete is False and not any(
                e.get("code") == "SOURCE_COVERAGE_INCOMPLETE" for e in run.errors or []
            ):
                self._write(
                    run,
                    cr,
                    Counter(run.counts or {}),
                    data,
                    [
                        _safe_error(
                            "SOURCE_COVERAGE_INCOMPLETE", "Source reports incomplete listing coverage", stage="DISCOVER"
                        )
                    ],
                )
                data = dict(cr.coverage or {})
            if state != "HEALTHY" and not run.errors:
                self._write(
                    run,
                    cr,
                    Counter(run.counts or {}),
                    data,
                    [_safe_error("SOURCE_UNHEALTHY", f"Connector health is {state}", stage="HEALTH")],
                )
                data = dict(cr.coverage or {})
            now = self.clock()
            retry_times = [_aware(error.get("retry_after")) for error in run.errors or []]
            if health.retry_after:
                retry_times.append(health.retry_after)
            retry_times = [value for value in retry_times if value and value > now]
            source = session.scalar(select(SourceRegistry).where(SourceRegistry.id == self.source_id).with_for_update())
            source.configuration_state = cr.health = state
            source.last_error = (run.errors or [])[-1]["code"] if run.errors else None
            capabilities = dict(source.capabilities or {})
            if retry_times:
                capabilities["runtime_retry_after"] = max(retry_times).isoformat()
                run.coverage = {**run.coverage, "retry_after": max(retry_times).isoformat()}
            elif _aware(capabilities.get("runtime_retry_after")) and _aware(capabilities["runtime_retry_after"]) <= now:
                capabilities.pop("runtime_retry_after", None)
            source.capabilities = capabilities
            if state == "HEALTHY" and not run.errors:
                source.last_success = now
            run.state = "DEFERRED" if deferred else "PARTIAL" if run.errors or state != "HEALTHY" else "SUCCEEDED"
            run.finished_at = cr.finished_at = now
            data.pop("lease", None)
            cr.coverage = data
            run.coverage = {**run.coverage, "complete_listing": terminal_complete, "connector_health": state}
            session.flush()
            session.expunge(run)
            self.final = run
            return run


def _drive_run(store, connector, *, monotonic_clock=monotonic, progress=None):
    started = monotonic_clock()
    terminal_complete = None
    stop = False
    health_override = None
    seen_cursors = set()
    while store.state["coverage"].get("pages_completed", 0) < store.limits["max_pages"]:
        if monotonic_clock() - started >= store.limits["max_elapsed_seconds"]:
            store.failure([_safe_error("RUN_TIME_BUDGET_EXHAUSTED", "Source run reached its bounded time budget")])
            break
        store.heartbeat()
        if progress:
            progress(store.run_id, store.state["counts"])
        cursor = store.state["cursor"]
        if cursor in seen_cursors:
            store.failure([_safe_error("SOURCE_CURSOR_REPEATED", "Connector repeated a pagination cursor")])
            break
        seen_cursors.add(cursor)
        try:
            discovery = connector.discover(store.query, store.source["tenant"], cursor)
        except Exception as exc:  # noqa: BLE001 - Provider adapters expose different transport/parser exceptions.
            store.failure([_safe_error("DISCOVER_EXCEPTION", type(exc).__name__, stage="DISCOVER")])
            break
        store.page(discovery)
        terminal_complete = discovery.coverage.get("complete_listing")
        # Existing seen-but-unprocessed IDs are deliberately replayed after a crash.
        admitted = set(store.state["coverage"].get("seen", []))
        for candidate in discovery.candidates:
            if candidate.external_id not in admitted:
                store.failure(
                    [_safe_error("RUN_CANDIDATE_BUDGET_EXHAUSTED", "Source run reached its candidate budget")]
                )
                stop = True
                break
            if candidate.external_id in store.state["coverage"].get("processed", {}):
                continue
            if monotonic_clock() - started >= store.limits["max_elapsed_seconds"]:
                store.failure([_safe_error("RUN_TIME_BUDGET_EXHAUSTED", "Source run reached its bounded time budget")])
                stop = True
                break
            store.heartbeat()
            if progress:
                progress(store.run_id, store.state["counts"])
            increments = Counter({"fetched": 1})
            errors = []
            normalized = check = None
            availability = None
            phase = "FETCH"
            try:
                if candidate.source_type != store.source["type"] or candidate.tenant != store.source["tenant"]:
                    raise ValueError("Discovered candidate source identity differs from registered source")
                fetched = connector.fetch(candidate)
                if fetched.outcome != "SUCCESS":
                    availability = "CLOSED" if fetched.outcome == "CLOSED" else "UNKNOWN"
                    increments["opening_closed" if fetched.outcome == "CLOSED" else "fetch_failed"] += 1
                    if fetched.outcome != "CLOSED":
                        errors = _source_errors(fetched.errors, stage="FETCH", external_id=candidate.external_id)
                        if not errors:
                            errors = [
                                _safe_error(
                                    "FETCH_" + fetched.outcome,
                                    "Candidate retrieval did not succeed",
                                    stage="FETCH",
                                    external_id=candidate.external_id,
                                )
                            ]
                else:
                    increments["fetch_success"] += 1
                    phase = "NORMALIZE"
                    normalized = connector.normalize(fetched)
                    increments["complete_description"] += int(normalized.description_complete)
                    phase = "VERIFY"
                    check = connector.verify_opening(normalized)
                    increments["opening_" + check.status.lower()] += 1
                    if check.status == "UNKNOWN":
                        errors.append(
                            _safe_error(
                                "OPENING_UNVERIFIED",
                                "Opening verification remains unresolved",
                                stage="VERIFY",
                                external_id=candidate.external_id,
                            )
                        )
                    if check.http_status in {403, 429}:
                        health_override = Health(
                            source_type=store.source["type"],
                            state="BLOCKED" if check.http_status == 403 else "RATE_LIMITED",
                            retry_after=datetime.now(UTC) + timedelta(minutes=1) if check.http_status == 429 else None,
                        )
            except Exception as exc:  # noqa: BLE001 - Capture provider-specific failures with safe class names only.
                normalized = check = None
                availability = "UNKNOWN"
                increments[
                    {"FETCH": "fetch_failed", "NORMALIZE": "parse_failed", "VERIFY": "opening_check_failed"}[phase]
                ] += 1
                errors.append(
                    _safe_error(
                        "CANDIDATE_EXCEPTION", type(exc).__name__, stage=phase, external_id=candidate.external_id
                    )
                )
            try:
                store.candidate(
                    candidate,
                    normalized=normalized,
                    opening=check,
                    increments=increments,
                    errors=errors,
                    availability=availability,
                )
            except (SourceRunLeaseLost, SourceRunBusy):
                raise
            except SourceStopped:
                store.failure([_safe_error("SOURCE_DISABLED_DURING_RUN", "Source was disabled during execution")])
                stop = True
                break
            except SQLAlchemyError as exc:
                # Previous candidates are committed. Leave this one unprocessed for a durable retry.
                store.failure(
                    [
                        _safe_error(
                            "DATABASE_INGEST_FAILED",
                            type(exc).__name__,
                            stage="INGEST",
                            external_id=candidate.external_id,
                        )
                    ]
                )
                raise
            except (ValueError, TypeError) as exc:
                store.candidate(
                    candidate,
                    increments={**increments, "ingest_failed": 1},
                    errors=[
                        *errors,
                        _safe_error(
                            "INGEST_REJECTED", type(exc).__name__, stage="INGEST", external_id=candidate.external_id
                        ),
                    ],
                )
            health = connector.health()
            if health_override or health.state in {"BLOCKED", "RATE_LIMITED", "NOT_CONFIGURED"}:
                stop = True
                break
        if stop:
            break
        store.complete_page(discovery.next_cursor)
        if not discovery.next_cursor:
            break
        if discovery.errors and connector.health().state in {"BLOCKED", "RATE_LIMITED", "NOT_CONFIGURED"}:
            break
    else:
        if store.state["cursor"]:
            store.failure([_safe_error("RUN_PAGE_BUDGET_EXHAUSTED", "Source run reached its pagination budget")])
    return store.finish(health_override or connector.health(), terminal_complete=terminal_complete)


def run_source_batched(
    session_factory: Callable[[], Session],
    source_id: UUID,
    user_id: UUID,
    *,
    query="",
    connector=None,
    run_id: UUID | None = None,
    max_pages=20,
    max_candidates=500,
    max_elapsed_seconds=600,
    on_progress=None,
) -> SearchRun:
    """Run one source with bounded calls and per-candidate commits.

    session_factory is a zero-argument callable returning a new Session. An optional
    deterministic run_id binds the result to a durable WorkItem. Call outside any
    caller-owned transaction; on_progress may renew the worker's separate lease.
    """
    if not 1 <= max_pages <= 20 or not 1 <= max_candidates <= 500 or not 1 <= max_elapsed_seconds <= 1800:
        raise ValueError("Source run budgets exceed supported bounds")
    limits = {"max_pages": max_pages, "max_candidates": max_candidates, "max_elapsed_seconds": max_elapsed_seconds}
    store = SourceRunStore(session_factory, source_id, user_id, query, run_id, limits).start()
    if store.final is not None:
        return store.final
    if not store.source["enabled"]:
        store.failure([_safe_error("NOT_CONFIGURED", "Source is disabled")])
        return store.finish(Health(source_type=store.source["type"], state="NOT_CONFIGURED"))
    retry_after = _aware(store.source.get("retry_after"))
    if retry_after and retry_after > datetime.now(UTC):
        store.failure(
            [_safe_error("SOURCE_BACKOFF_ACTIVE", "Source retry-after time has not arrived", retry_after=retry_after)]
        )
        return store.finish(
            Health(source_type=store.source["type"], state="RATE_LIMITED", retry_after=retry_after), deferred=True
        )
    try:
        connector = connector or get_connector(store.source["type"])
    except (ValueError, ImportError) as exc:
        store.failure([_safe_error("CONNECTOR_NOT_CONFIGURED", type(exc).__name__)])
        return store.finish(Health(source_type=store.source["type"], state="NOT_CONFIGURED"))
    try:
        return _drive_run(store, connector, progress=on_progress)
    except (SourceRunLeaseLost, SourceRunBusy):
        raise
    except Exception:
        # Earlier candidate commits remain durable. Database unavailability may also
        # prevent releasing this lease; expiry is the recovery fallback in that case.
        try:
            store.release()
        except SQLAlchemyError:
            pass
        raise
