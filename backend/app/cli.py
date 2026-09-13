"""Run from backend/: uv run python -m app.cli --help."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID


def parser():
    p = argparse.ArgumentParser(prog="personal-staffer")
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("replay-fixtures")
    r.add_argument("--path", default="tests/fixtures/eligibility_synthetic_v1.json")
    sub.add_parser("seed-registry")
    sub.add_parser("list-sources")
    sub.add_parser("demo-seed")
    source = sub.add_parser("register-source")
    source.add_argument("--type", required=True)
    source.add_argument("--tenant", required=True)
    source.add_argument("--employer", required=True)
    source.add_argument(
        "--pool",
        action="append",
        default=[],
        choices=["WATCHLIST", "CONNECTICUT", "UNIVERSITY", "ACADEMIC_MEDICAL_CENTER", "NYC", "BAY_AREA"],
    )
    source.add_argument(
        "--pool-evidence", type=Path, help="Reviewed JSON evidence for company pools; plain labels remain unverified"
    )
    source.add_argument("--enable", action="store_true")
    search = sub.add_parser("run-search")
    search.add_argument("--source", required=True, help="registered source UUID")
    search.add_argument("--user", type=UUID)
    report = sub.add_parser("build-report")
    report.add_argument("--date", type=date.fromisoformat)
    report.add_argument("--user", type=UUID)
    imp = sub.add_parser("import-source-fixture")
    imp.add_argument("path")
    imp.add_argument("--source", type=UUID, required=True)
    imp.add_argument("--user", type=UUID)
    resolve = sub.add_parser("resolve-job-employer")
    resolve.add_argument("--job", type=UUID, required=True)
    resolve.add_argument("--entity", type=UUID, required=True)
    resolve.add_argument(
        "--evidence", required=True, help="path to JSON with source_reference, quoted_text and reviewer"
    )
    history = sub.add_parser(
        "import-email-applications",
        help="One-time: propose/create applications from open Gmail confirmation reviews (preview by default)",
    )
    history.add_argument("--apply", action="store_true", help="Create/link applications; default is preview only")
    history.add_argument("--include-low", action="store_true", help="Also import LOW-confidence proposals")
    history.add_argument("--user", type=UUID)
    sub.add_parser("schedule-once")
    sub.add_parser("dispatch-once")
    sub.add_parser("dispatch-loop")
    return p


def only_user(session, selected=None):
    from sqlalchemy import select

    from app.db.models import User

    rows = list(session.scalars(select(User).where(User.id == selected) if selected else select(User)))
    if len(rows) != 1:
        raise ValueError("Complete Google owner enrollment first, or use demo-seed in isolated local DEMO_MODE")
    return rows[0]


def seed_registry(session):
    from sqlalchemy import select

    from app.db.models import EmployerGroup, WatchlistEntry

    names = [
        "HCA Healthcare",
        "Henry Ford Health",
        "Infosys",
        "Cognizant",
        "Tata Consultancy Services",
        "Thermo Fisher Scientific",
        "Walmart",
        "Amazon",
        "Microsoft",
        "Tesla",
        "Analog Devices",
    ]
    user = only_user(session)
    for name in names:
        group = session.scalar(select(EmployerGroup).where(EmployerGroup.canonical_name == name))
        if group is None:
            group = EmployerGroup(
                canonical_name=name,
                normalized_name=name.casefold(),
                grouping_evidence={"basis": "User specification watchlist; legal entity not verified"},
            )
            session.add(group)
            session.flush()
        if not session.scalar(
            select(WatchlistEntry.id).where(
                WatchlistEntry.user_id == user.id, WatchlistEntry.employer_group_id == group.id
            )
        ):
            session.add(WatchlistEntry(user_id=user.id, employer_group_id=group.id))
    return {"watchlist_employers": len(names), "everify_confirmed": 0}


def validate_real_source_bundle(bundle):
    provenance = bundle.get("provenance", bundle)
    if not isinstance(provenance, dict) or provenance.get("synthetic") is not False:
        raise ValueError(
            "Real source import requires provenance.synthetic explicitly false; use demo-seed for synthetic fixtures"
        )
    if not (provenance.get("fetched_at") or provenance.get("observed_at")):
        raise ValueError("Recorded source evidence requires fetched_at or observed_at provenance")
    return provenance


def validate_pool_evidence(employer, requested_pools, evidence_path):
    if evidence_path is None:
        return [], {}
    evidence = json.loads(Path(evidence_path).read_text())
    if not isinstance(evidence, dict):
        raise TypeError("Pool evidence must be a JSON object keyed by requested pool")
    verified = []
    bay_cities = {
        "san francisco",
        "oakland",
        "berkeley",
        "san jose",
        "palo alto",
        "mountain view",
        "menlo park",
        "redwood city",
        "san mateo",
        "santa clara",
        "sunnyvale",
        "cupertino",
        "south san francisco",
    }
    for pool, proof in evidence.items():
        if pool not in requested_pools or pool not in {"NYC", "BAY_AREA", "UNIVERSITY", "ACADEMIC_MEDICAL_CENTER"}:
            raise ValueError("Only requested company/institution pools can receive reviewed membership evidence")
        if not isinstance(proof, dict) or not all(
            isinstance(proof.get(field), str) and proof[field].strip()
            for field in ("source_reference", "quoted_text", "reviewer", "checked_at")
        ):
            raise ValueError("Pool membership requires source_reference, quoted_text, reviewer and checked_at")
        checked = datetime.fromisoformat(proof["checked_at"])
        if checked.tzinfo is None or checked.utcoffset() is None or checked > datetime.now(UTC):
            raise ValueError("Pool evidence checked_at must be a past timezone-aware timestamp")
        if employer.casefold() not in proof["quoted_text"].casefold():
            raise ValueError("Pool evidence must identify the registered company")
        if pool in {"NYC", "BAY_AREA"}:
            if proof.get("company_location_kind") not in {"HEADQUARTERS", "MAJOR_OPERATING_OFFICE"}:
                raise ValueError("Startup pool membership requires headquarters or major-office evidence")
            location = proof.get("location", "").strip().casefold()
            allowed = {"nyc", "new york city", "new york, ny"} if pool == "NYC" else bay_cities
            if location not in allowed:
                raise ValueError("Startup pool location needs a supported city; preserve job location independently")
            if not proof.get("startup_basis"):
                raise ValueError(
                    "Record the source-backed basis for startup membership without inventing a funding stage"
                )
        verified.append(pool + "_VERIFIED")
    return verified, evidence


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "replay-fixtures":
        from app.eligibility.replay import replay_corpus

        print(json.dumps(replay_corpus(Path(args.path)), indent=2, default=str))
        return
    from sqlalchemy import select

    from app.db.models import EmployerGroup, SourceRegistry
    from app.db.session import session_factory

    factory = session_factory()
    if args.command == "run-search":
        from app.jobs.orchestration import run_source_batched

        with factory() as session:
            user_id = only_user(session, args.user).id
        run = run_source_batched(factory, UUID(args.source), user_id)
        print(
            json.dumps(
                {"run_id": str(run.id), "state": run.state, "counts": run.counts, "errors": run.errors},
                indent=2,
                default=str,
            )
        )
        return
    if args.command.startswith("dispatch"):
        from app.workers.celery_app import process_event
        from app.workers.service import dispatch_once

        while True:
            from app.workers.schedule import schedule_due
            from app.workers.service import reconcile

            # The dispatcher can recover schedule occurrences after Redis/Beat loss.
            with factory() as session, session.begin():
                schedule_due(session)
                reconcile(session)
            count = dispatch_once(factory, lambda event_id: process_event.delay(event_id))
            if args.command == "dispatch-once":
                print(json.dumps({"dispatched": count}))
                return
            time.sleep(5)
    if args.command == "import-email-applications":
        from app.email.import_history import apply as apply_import
        from app.email.import_history import propose

        with factory() as session, session.begin():
            user_id = only_user(session, args.user).id
            proposals = propose(session, user_id)
            for p in proposals:
                print(
                    f"{p.received_at:%Y-%m-%d} | {p.confidence:<6} | {p.action:<6} | "
                    f"{(p.company or '?')[:38]:<38} | {(p.title or '?')[:60]:<60} | {p.subject[:70]}"
                )
            print(f"{chr(10)}{len(proposals)} open confirmation review(s)")
            if args.apply:
                print(json.dumps(apply_import(session, user_id, proposals, include_low=args.include_low), indent=2))
            else:
                print("Preview only. Rerun with --apply (and --include-low to include LOW-confidence rows).")
        return
    with factory() as session, session.begin():
        if args.command == "seed-registry":
            result = seed_registry(session)
        elif args.command == "demo-seed":
            from app.demo import seed_demo

            result = seed_demo(session)
        elif args.command == "list-sources":
            result = [
                {
                    "id": str(s.id),
                    "type": s.connector_type,
                    "tenant": s.tenant,
                    "state": s.configuration_state,
                    "enabled": s.enabled,
                }
                for s in session.scalars(select(SourceRegistry))
            ]
        elif args.command == "register-source":
            from app.connectors import get_connector

            get_connector(args.type)  # Reject unsupported/disabled labels.
            source = session.scalar(
                select(SourceRegistry).where(
                    SourceRegistry.connector_type == args.type, SourceRegistry.tenant == args.tenant
                )
            )
            if source:
                raise ValueError("Source already exists; do not silently replace its employer mapping")
            verified_pools, pool_evidence = validate_pool_evidence(args.employer, args.pool, args.pool_evidence)
            group = EmployerGroup(
                canonical_name=args.employer,
                normalized_name=args.employer.casefold(),
                pool_tags=args.pool + verified_pools,
                grouping_evidence={"method": "ADMIN_SOURCE_REGISTRATION", "pool_evidence": pool_evidence},
            )
            session.add(group)
            session.flush()
            source = SourceRegistry(
                connector_type=args.type,
                tenant=args.tenant,
                employer_group_id=group.id,
                board_identifier=args.tenant,
                enabled=args.enable,
                pool_tags=args.pool,
                configuration_state="NOT_CONFIGURED",
                capabilities={"registered_by": "ADMIN_CLI"},
            )
            session.add(source)
            session.flush()
            result = {
                "source_id": str(source.id),
                "group_id": str(group.id),
                "enabled": source.enabled,
                "verified_pools": verified_pools,
                "note": "Plain pool tags are search requests, not verified institution/startup membership. Registration is not E-Verify or legal-employer confirmation",
            }
        elif args.command == "build-report":
            from app.reports.service import build_report

            r = build_report(session, only_user(session, args.user).id, args.date)
            result = {"report_id": str(r.id), "date": str(r.report_date), "summary": r.summary}
        elif args.command == "schedule-once":
            from app.workers.schedule import schedule_due

            result = {"scheduled": schedule_due(session)}
        elif args.command == "import-source-fixture":
            from app.connectors import get_connector
            from app.connectors.contracts import Candidate, FetchResult, OpeningVerification
            from app.jobs.pipeline import ingest_normalized

            bundle = json.loads(Path(args.path).read_text())
            provenance = validate_real_source_bundle(bundle)
            source = session.get(SourceRegistry, args.source)
            if source is None or source.employer_group_id is None:
                raise ValueError("Register a source with an employer group before importing recorded evidence")
            raw = bundle.get("job") or bundle.get("raw") or bundle.get("sample_job")
            if raw is None:
                raise ValueError("Bundle must include the recorded job payload")
            observed = datetime.fromisoformat(provenance.get("fetched_at") or provenance["observed_at"])
            if observed.tzinfo is None or observed.utcoffset() is None:
                raise ValueError("Recorded fetch timestamp must include its timezone")
            candidate = Candidate(
                source_type=source.connector_type,
                tenant=source.tenant,
                external_id=str(raw["id"]),
                source_url=raw.get("jobUrl") or raw.get("absolute_url") or provenance["url"],
                employer_name=session.get(EmployerGroup, source.employer_group_id).canonical_name,
            )
            payload = FetchResult(
                candidate=candidate,
                outcome="SUCCESS",
                payload=raw,
                description_complete=True,
                source_url=candidate.source_url,
                fetched_at=observed,
            )
            normalized = get_connector(source.connector_type).normalize(payload)
            job, evaluation = ingest_normalized(
                session,
                source,
                normalized,
                OpeningVerification(
                    status="UNKNOWN", evidence_text="Recorded payload import: application path not checked live"
                ),
                user_id=only_user(session, args.user).id,
            )
            result = {"job_id": str(job.id), "decision": evaluation.decision, "live_application_verified": False}
        elif args.command == "resolve-job-employer":
            from app.db.models import EmployerEntity, Job, ReviewItem
            from app.jobs.pipeline import reevaluate_job

            evidence = json.loads(Path(args.evidence).read_text())
            if not all(
                isinstance(evidence.get(k), str) and evidence[k].strip()
                for k in ("source_reference", "quoted_text", "reviewer")
            ):
                raise ValueError("Employer resolution requires source_reference, quoted_text and reviewer")
            job = session.get(Job, args.job)
            entity = session.get(EmployerEntity, args.entity)
            if not job or not entity or entity.group_id != job.employer_group_id:
                raise ValueError("Entity must belong to the job's evidenced employer group")
            user = only_user(session)
            session.add(
                ReviewItem(
                    user_id=user.id,
                    review_type="EMPLOYER_RESOLUTION",
                    target_id=job.id,
                    reason="Reviewed actual employing entity",
                    evidence=evidence,
                    state="RESOLVED",
                    admin_only=True,
                    resolved_at=datetime.now(UTC),
                    resolution={"entity_id": str(entity.id)},
                )
            )
            job.entity_id = entity.id
            result = {"decision": reevaluate_job(session, job.id, user.id).decision}
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
