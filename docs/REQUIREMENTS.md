# Requirement implementation map

Statuses distinguish code from executed verification. Every requirement remains part of scope. **The full product is not release-accepted.** Paths beginning app/ are under backend/.

| ID | Contract | Implementation | Verification boundary |
|---|---|---|---|
| PR-01 | Installed Windows and Android clients; shared cloud state; Windows first. | client/lib; client/windows; client/android | Flutter analyze/widget/cache checks; Android release compiled unsigned; Windows/device acceptance pending |
| PR-02 | Single-user identity; no resume required; Gmail selected. | backend/app/auth; app/demo.py | signed OIDC and owner/session contracts; PostgreSQL and live consent pending |
| PR-03 | U.S. jobs, remote/hybrid/onsite, role-family and skill-based discovery. | app/eligibility; app/relevance; app/api/router.py | synthetic role/geography/skills cases |
| PR-04 | Complete JD, confirmed full-time, verified freshness within 72 hours. | app/eligibility; app/connectors; app/jobs | freshness/full-time/completeness tests; real delivery not verified |
| PR-05 | Confirmed E-Verify legal employer; unknown employers withheld. Superseded for this owner by ADR 0003: `EVERIFY_GATE=INFORMATIONAL` shows the evidence state without withholding. | app/api/admin.py; app/jobs/pipeline.py; app/eligibility/engine.py; EVerifyEvidence | proof-free approval refused; both gate modes tested; no real entity confirmed |
| PR-06 | Exclude explicit sponsorship restrictions; unstated sponsorship permitted. | app/eligibility/text_rules.py | sponsorship exclusion/negation/silence tests |
| PR-07 | Exclude required clearance; preferred-only clearance flagged. | app/eligibility/text_rules.py | clearance/negation/preferred-only tests |
| PR-08 | Exactly four years allowed; 4+ and higher required experience excluded. | app/eligibility/text_rules.py | exact4 vs4+ and alternative/required-skill tests |
| PR-09 | $80K preference, undisclosed eligible, lower compensation may fill slots. | app/reports/selection.py; app/eligibility/engine.py | salary band selection tests |
| PR-10 | Daily maximum 50; newest-first display; at most two jobs per company. | app/reports/service.py; migrations0002 | selection tests; PostgreSQL frozen/concurrent report checks pending |
| PR-11 | Shared 32-day employer rotation; permanent duplicate/repost suppression. | app/reports; app/eligibility/dedupe.py; app/jobs | shared-cycle/dedupe unit tests; DB constraints pending |
| PR-12 | Priority watchlist, university and Connecticut alerts, independent of daily quota/rotation. | app/reports; app/jobs; WatchlistEntry | priority triggers tested; live priority release not verified |
| PR-13 | Dedicated NYC and Bay Area startup discovery pools. | app/connectors/catalog.py; app/cli.py; app/jobs | verified pool evidence required; full company-location pilot pending |
| PR-14 | JobSpy excluding LinkedIn plus direct employer, ATS and specialized sources. | app/connectors | ATS/SafeHTTP74 scoped tests + real payload replay; specialized coverage partial; JobSpy package qualified but BLOCKED_SECURITY |
| PR-15 | Full job details, evidence, source links and original application destination. | JobSnapshot/JobSource; api job/application details; client job view | retained links and evidence code; complete DB/native workflow pending |
| PR-16 | Up to ten relevant public LinkedIn people per job; relationship evidence; no ranking. | app/people; client People | public-search adapter/evidence grouping tests; provider not configured |
| PR-17 | Exact five-item navigation and Homepage's two tabs. Superseded in part by ADR 0002: Watchlist is the sixth primary destination (owner decision, 2026-09-12). | client/lib/app.dart; client/lib/features/watchlist.dart | Flutter exact navigation/tabs tests assert the six-item order |
| PR-18 | Saved jobs persist until applied or unsaved; no age-based removal. | app/applications; app/sync; SavedJobVersion | state code + PG persistence cases pending |
| PR-19 | Permanent applications, snapshots, source links and event history. | app/applications; ApplicationEvent/JobSnapshot; migrations0002 | append-only history/retention code; PG verification pending |
| PR-20 | Accidental Applied and automatic status changes can be corrected; prior state restored appropriately. | app/applications/service.py; client applications | event correction/undo code; pure projection tests + PG checks pending |
| PR-21 | Gmail-driven application dashboard, review of ambiguous updates and source evidence. | app/email; dashboard routes | mail template/history contracts; no Gmail grant |
| PR-22 | Clickable notifications navigate to the specific destination; persistent inbox and unread count. | app/notifications; client platform bridge | typed route/dedupe tests; actual OS lifecycle pending |
| PR-23 | Cross-device sync, explicit pending states and conflict-safe offline actions. | app/sync; client/core/cache.dart; client/core/repository.dart | encrypted SQLite/pending/conflict tests on Linux; cross-device pending |
| PR-24 | Search-run history, source health and explainable inclusion/withholding. | SearchRun/ConnectorRun; connectors health; jobs orchestration | real source access outcomes recorded; production DNS unavailable here |
| PR-25 | Authentication, secure storage, backups, restore, installation and update instructions. | auth/config; deployment; scripts; native packaging | security review + static tests; signed installs/restore/deployment pending |

## Mandatory acceptance scenarios

The exact AT-01–AT-60 scenarios remain in BUILD_SPECIFICATION.md. Matching automated tests are under backend/tests and client/test. PostgreSQL, external-provider and native lifecycle checks are explicitly pending until their actual environments run them. Finite synthetic passing tests are not claimed as real-source accuracy.

| Scenarios | Suitable checks | Current verification type |
|---|---|---|
| AT-01–20 | eligibility, relevance, mapping, connector tests | Synthetic edge cases and retained public payloads; real legal evidence unavailable |
| AT-21–30 | selection, report/pipeline/dedupe/worker tests | Pure tests run; PostgreSQL report/concurrency pending |
| AT-31–37 | application/core/correction/demo database tests | Real PostgreSQL tests prepared, not run locally |
| AT-38–43 | email parser/API/orchestration/database tests | Parser/API mocks run; transaction/live Gmail pending |
| AT-44–46 | inbox contracts, PostgreSQL and native routing | Unit/widget checks run; real devices/provider pending |
| AT-47–48 | People search/grouping/budget contracts | Contract checks run; live professional evidence pilot pending |
| AT-49–50 | Flutter encrypted queue and server sync | Linux checks run; PostgreSQL and cross-device pending |
| AT-51–52 | durable work/outbox/notification retry | Unit contracts run; broker/PostgreSQL failure drill pending |
| AT-53–54 | auth negatives, ownership, unsafe URLs | Signed-claim/SSRF tests run; PostgreSQL ownership pending |
| AT-55–56 | encrypted release cache, installer/APK/lifecycle | Linux encryption tested; Windows/Samsung release verification pending |
| AT-57 | pg_dump/restore content comparison | CI/runbook prepared; actual restore pending |
| AT-58–60 | responsive/a11y states, config, exact navigation | Automated widget/config checks; actual screen-reader/device review pending |
