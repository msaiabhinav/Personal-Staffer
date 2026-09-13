# ADR 0006 — Accurate Gmail capture and a company-centric view

Status: accepted, owner request on 13 September 2026 ("Analyze my Gmail properly, you didn't show accurate numbers; clicking No reply yet must show that list; I must be able to search a company on the dashboard and see its status, all its emails and threads").

## Why the numbers were off

1. **Capture was too narrow.** The 150-day backfill used the bounded Gmail search `{application interview assessment recruiter recruiting "offer of employment" "position closed"}`. Measured on the owner's mailbox on 13 September: that query returns 325 messages; adding the words employers actually use (`applying`, `applied`, `candidacy`, `candidate`, "your interest", "next steps", "thank you for", `resume`, `hiring`, `talent`, `opportunity`) and the applicant-tracking sender domains (Greenhouse, Lever, Workday, iCIMS, SmartRecruiters, Ashby, Jobvite, Taleo, SuccessFactors, Workable, BambooHR, Phenom, Eightfold, BrassRing, UKG, Paylocity, ADP, GovernmentJobs) returns 438. Roughly a third of the relevant mail was never read.
2. **Per-message processing hides the company picture.** 299 messages became 100 confirmations, 168 open "unmatched" reviews and 68 applications; the reviews hold employer replies that were never shown against their company because the automatic matcher only links one email to one application and gives up when a company has several.
3. **Dashboard tiles were counts without a path**: no way to open the list behind a number or to ask "what is going on with company X".

## Decision

- **Wider capture, same safety.** `GmailAPI.backfill` uses the wider query above (read-only scope unchanged; unrelated mail is classified `UNRELATED` and never stored). A CLI `gmail-rebackfill` resets the sync cursor so the scheduled sync re-walks the 150-day window; already-stored messages are skipped by Gmail message id. Incremental history sync is unchanged.
- **Company-centric evidence.** `GET /companies?q=` searches the owner's applications, email senders/subjects and employer groups by name; `GET /companies/{name}` assembles one company: its applications with status and events, every email that is linked to those applications *or* names the company (subject or sender), grouped by Gmail thread and ordered by time, its watchlist entry and its scanned relevant postings. Nothing is re-classified here; the page shows the parser's existing verdict per message ("confirmation", "rejection", "unmatched") so the owner sees the raw evidence behind each status.
- **Every dashboard number opens its list.** KPI tiles link to `/applications?status=…` (`AWAITING_RESPONSE` is a supported filter); the dashboard gains a company search box that opens the company page.
- **Re-run the one-time import** after the wider backfill, then report the numbers with their derivation (messages captured → confirmations → applications created/linked/voided → statuses applied → still unmatched) in TEST_RESULTS.

## Not changed

Eligibility gates, delivery quotas and the read-only Gmail grant. Emails are still never sent, and the owner's decisions on ambiguous matches stay in Review.
