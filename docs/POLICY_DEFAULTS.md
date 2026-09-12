# Policy defaults and verification boundaries

Policy version: `spec-1.0-policy-1.0`. Deterministic extractor, relevance and identity versions are stored with their outputs. Requirements: PR-03–PR-13, PR-15, PR-24; acceptance coverage principally AT-01–AT-24 and AT-28.

## Evidence and eligibility

`app.eligibility.models.JobEvidence` is the source/evidence input, separate from `Evaluation`. `evaluate_job(job, now=..., policy=...)` is pure and reproducible with a timezone-aware frozen clock. Every rule contains a decision, reason, version and snapshot field/text references. Extracted clauses preserve exact description offsets. No fabricated confidence values or match percentages are used.

A `FAIL` yields `INELIGIBLE`; otherwise `UNKNOWN`/`REVIEW` yields `NEEDS_REVIEW`; only passing all rules yields `ELIGIBLE`. A complete successfully retrieved JD is mandatory. Silence in that complete JD permits the sponsorship and clearance exclusion rules to pass, but their displayed facts remain `NOT_STATED` / `NO_REQUIREMENT_FOUND`.

| Gate | Implemented default |
|---|---|
| Country | Explicit normalized US/USA hiring geography required. Generic remote withheld; conflicting evidence reviewed. Country codes must come from retained source evidence, never employer headquarters inference. |
| Employment | Credible full-time metadata or JD; excluded engagements override full-time metadata. Permanent staffing placement needs verified payroll employer. Consulting-company identity alone is not an excluded engagement. |
| Sponsorship | Explicit denials, visa transfer exclusion, citizenship/permanent-resident-only or permanent unrestricted authorization restrictions fail. Ordinary US work authorization passes. Unrecognized sponsorship clauses or quoted policy examples go to review. |
| Clearance | Required security/Secret/TS-SCI/DOE Q/L/Public Trust/government suitability or ability to obtain/maintain fail. Preferred-only is flagged; explicit negation and ordinary background/drug checks pass. Ambiguous requiredness is reviewed. |
| Experience | Exact 4, 2–4 and up to 4 pass. 4+, minimum 4, at least 4, more than 4 and any mandatory range extending beyond 4 fail. 1+/2+/3+ pass. Distinct mandatory skill requirements are not summed and cannot hide a higher requirement. Preferred years stay preferred. Unknown education alternatives/quoted or ambiguous clauses/absent experience go to review. Months are interpreted as stated months ÷ 12; nonintegral years preserve numeric precision. |
| E-Verify | Matching actual legal entity plus legal name, evidence source/reference/hash, reviewer/mechanism and check date required. Search miss is unknown. Conflicting identity is reviewed. Default recheck 30 days, earlier explicit deadline honored. No synthetic approval in normal evaluation. |
| Active opening | Specific opening identity, actionable HTTP(S) application URL, dated evidence and recent check required. Default check freshness 24 hours. HTTP 200 alone is insufficient. Explicit closure fails; blocked/error/generic careers redirect is unknown. |
| Role relevance | Versioned approved families plus substantive extracted responsibilities. Broad healthcare/AI/data keywords do not approve unrelated roles. Senior title alone does not exclude. Faculty, teaching and postdoctoral titles excluded. |

The 24-hour opening-evidence window is a conservative engineering default for cached verification, not a guarantee that an employer link remains available that long. Delivery should recheck when practical; retained history is independent of current eligibility. Changing a hard threshold is a product-policy change and requires preserving the user contract, versioning and regression evidence.

## Time, salary and priority

Publication intervals store earliest/latest possible timestamp, precision, semantic kind, source field and timezone separately from first seen/update times. Exact age 72 hours passes; any older exact age fails. Intervals crossing the boundary are reviewed. Five minutes of future clock skew is tolerated and displayed as “Just posted”; larger future uncertainty is reviewed. `UPDATED` and `FIRST_SEEN` never establish publication. `LAST_PUBLICATION` requires an independent repost check. Known reposts fail freshness despite a new timestamp.

Salary bands: A annual USD minimum ≥ 80,000; C annual USD maximum < 80,000; B all crossing, undisclosed or unusable ranges. Hourly/non-USD compensation stays as published, with no conversion invented. Selection/report code is responsible for salary-band then timestamp selection and newest-first final display. `Salary` rejects reversed ranges. A fixed salary should be supplied as equal min/max.

Priority reason labels are generated only for eligible relevant jobs. Watchlist requires a resolved group; US university/academic-medical-center roles qualify; Connecticut onsite/hybrid needs CT workplace evidence, while remote requires explicit CT eligibility. Generic US remote is not CT priority. Startup pool metadata neither changes job geography nor creates priority. Overlapping reasons return one ordered list for one job event; the delivery ledger enforces notification and quota dedupe.

## Identity and relevance boundaries

`app.eligibility.dedupe.compare_identity` returns `SAME`, `DISTINCT` or `REVIEW` with an auditable reason. Same source/tenant/external ID, verified employer-scoped requisition identity or a verified exact employer destination can establish sameness. Different verified requisitions remain distinct even with identical boilerplate. A source ID reused against conflicting requisitions is reviewed. Similarity only creates a review candidate, never an automatic merge. Only known tracking parameters are removed from URL comparison; job IDs and location parameters remain.

The caller may set `requisition_verified=True` only after establishing that the IDs share a common exact employer namespace. Employer rotation groups and fuzzy brand labels do not establish this. Persist the emitted identity keys as permanent tombstones along with canonical redirects and merge/correction evidence; the pure comparator does not manage database merges or retention itself.

Skills preserve original vocabulary and canonical aliases (including `PowwerBI` → `Power BI`). Exact skills, related technologies, preferred/required skills and missing requested skills are separate. A related PostgreSQL mention does not assert the user possesses PostgreSQL or call it an exact SQL mention. The summary is extracted verbatim from responsibility clauses, and the match reason is a transparent template.

## Executed tests and corpus

From repository root:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/test_eligibility_corpus.py backend/tests/test_eligibility_rules.py -q
```

Initial execution: **125 passed** on Linux with the project environment. The 60-row `backend/tests/fixtures/eligibility_synthetic_v1.json` has full synthetic JD/evidence bundles, rationale and expected outcomes; 48 regression and 12 held-out rows are separated by synthetic template/employer group. All fixtures use `.invalid` URLs and explicit synthetic flags. The evaluator rejects synthetic evidence for normal delivery; replay requires `allow_synthetic=True` and performs no persistence.

Measured initial corpus results: 60/60 expected decisions; 20 eligible, 22 ineligible and 18 review; zero hard-rule false accepts on these cases; eligible recall 100%; review rate 30%. Regression review rate 27.08%; held-out review rate 41.67%. `app.eligibility.replay.replay_corpus(path)` computes split metrics and per-rule measurements on the explicitly annotated rule subset, returning undefined precision/recall as null when no relevant labels exist.

These are finite synthetic regression measurements, **not estimates of real employer/job coverage or general production accuracy**. The reserved held-out template is small and not an independent external benchmark. Approximately 250 legally obtained real evidence bundles, ambiguous real-world language audits and the multi-day accepted/withheld pilot remain release work.

## Known limits

Deterministic English-language patterns do not resolve every qualification, nested conjunction, unusual title or legal-employer ambiguity. Unrecognized experience/sponsorship/clearance wording generally needs review; contextual parser errors remain possible. Relevance currently favors precision and can withhold relevant uncommon titles. Source adapters are responsible for credible structured geography/employment and complete snapshot provenance. Reviewed evidence must rerun the same rules and must never become an override Boolean. Public E-Verify/source availability and actual employer participation are not established by the synthetic corpus. Database concurrency, cycle retention, delivery idempotency and live integration gates are tested by their owning services, not proven by these pure functions.

## Ingestion and delivery audit follow-up

The ingestion service now maps normalized fields into the rule contract without assigning a legal entity from the source's employer group. An administrator must resolve the actual job's `entity_id`; current E-Verify evidence must match that entity and group. Remote eligible states come from `remote_eligible_states` fact values, never the office-state array. Updated snapshots and current CLOSED/UNKNOWN availability are honored during delivery re-evaluation, as are the current saved family/arrangement selections. An explicitly saved empty family selection selects no jobs.

Each ingested snapshot records `identity_checks`: retained source IDs, employer destinations, scoped requisitions and candidate similarities considered, plus the limited local-history coverage statement. `LAST_PUBLICATION` evidence can pass the repost-check prerequisite only after that local check has no unresolved candidates. This does not establish that an unseen repost cannot exist elsewhere. The old source-wide `repost_identity_reviewed` Boolean has no approval effect.

Cross-source requisition equality needs a reviewed common namespace in `SourceRegistry.capabilities.requisition_namespace` with `namespace`, `reviewer`, `evidence_reference` and an aware `checked_at`. The namespace is an exact employer requisition namespace, separate from rotation grouping. Unscoped equal requisitions/similar descriptions are reviewed rather than merged; different requisitions remain distinct. Source, scoped-requisition and proven-destination tombstones preserve known identities across source cleanup and new company cycles. Canonical redirects are followed when checking prior delivery/application/dismissal suppression.

An unresolved identity is retained on the per-opening `JobSource.link_evidence.identity_review_candidates`. A reviewed DISTINCT resolution must name `content_hash`, `source_identity` (`source:<connector>:<tenant>:<external-id>`), `requisition_id` (explicit null allowed), `reviewer`, `evidence_reference`, aware `checked_at` and `decision: DISTINCT`. It cannot silently transfer to a different requisition reusing a source ID. The internal reviewed-record boundary exists; a complete authenticated administration UI/import workflow still needs integration verification.

Additional pure mapping audit: **8 passed**. Eight PostgreSQL report/pipeline tests were added for concurrent caps/idempotency, priority quota bypass, changed profile/current closure, cross-source suppression, local repost review, salary selection and immutable finalized membership. They explicitly **did not run** because `TEST_DATABASE_URL` is unavailable. They reuse the isolated-schema fixture and real Alembic migrations; no SQLite substitution or database correctness claim is made.

Ingestion and report/application operations share user locking for consistent mutations. Worker and CLI search entry points now call `app.jobs.orchestration.run_source_batched`: discovery/fetch/verification happen outside PostgreSQL transactions; each ingestion and its progress checkpoint commit together in a short transaction. The legacy `run_source(session)` remains a diagnostic compatibility path and retains its caller transaction. Actual locking/throughput behavior still requires PostgreSQL and live-load verification.


## Orchestration optimization and debug checkpoint

The batched orchestrator bounds a run to at most 20 pages and 500 admitted candidates, with a configurable elapsed-time budget (worker uses six minutes to leave room for a final bounded provider call before its task timeout). It checkpoints processed source IDs with each candidate transaction; retry can replay the current page while skipping committed candidates. Worker runs use a deterministic SearchRun UUID tied to their durable WorkItem, so retry after a final commit returns the retained result. Run leases prevent concurrent checkpoint writers and recover after process loss.

Run coverage preserves each page's capability/coverage metadata. Incomplete terminal listings and nonhealthy providers produce PARTIAL, including empty JobSpy/unconfigured results. Counts distinguish raw discoveries, unique admitted discoveries, attempted/successful fetches, complete descriptions, opening states, persistence and eligibility outcomes. Provider errors contain safe error codes/classes; per-run error detail is bounded to 100 with a total error count. Source Retry-After is retained in `SourceRegistry.capabilities.runtime_retry_after`; both orchestration and scheduling honor it. JobSpy site-specific registry types get their intended slower cadence.

Verified startup pools require a verified group flag plus retained employer location/startup evidence. This marks the company's pool without changing the job's country or workplace. Fresh-process import tests also fixed and cover a package initialization cycle that ordinary pytest import order had masked.

Latest scoped verification: **147 tests passed; 11 PostgreSQL tests explicitly skipped** because `TEST_DATABASE_URL` is not configured. This includes deterministic orchestration, budget/retry/cursor/coverage tests and three new PostgreSQL-only lock/crash-checkpoint/Retry-After scenarios. The relevant eligibility/relevance/jobs/reports code and tests pass Ruff after reviewed fixes and formatting. These counts are a scoped checkpoint; the root build's subsequent global debug results are authoritative.
