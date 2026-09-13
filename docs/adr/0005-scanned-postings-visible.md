# ADR 0005 — Scanned postings are viewable; delivery gates decide only what is alerted

Status: accepted, owner request on 13 September 2026 ("Watchlist: when I click a company it must show available jobs" and "just show me 5 job postings on the homepage to see how it is").

Context: until now a posting was visible in the client only after a delivery (daily report or priority alert), a saved state, or an application. Every posting the owner's own career-site sources collected but withheld was invisible, so a watched company showed nothing and the feed stayed empty while the eligibility gates worked exactly as designed. The owner cannot judge the UI, or the sources, from an empty screen.

Decision:

- `GET /jobs?scope=scanned` lists every open (`availability != CLOSED`, non-redirected) posting collected by an **enabled** registered source, newest first, with the usual filters plus `employer_group_id`. Listing creates **no** `InitialDelivery`, no notification, and touches no gate: a withheld posting stays withheld and carries its evaluation (`ELIGIBLE` / `INELIGIBLE` / `NEEDS_REVIEW` with failed reason codes, or no evaluation) so the client labels it honestly ("Withheld · experience above policy", "Not evaluated yet"). Disabled sources contribute nothing.
- A posting reachable through that scope is also openable (`/jobs/{id}`, evidence, view/save/apply). The access check `_accessible_job` therefore accepts "collected by an enabled source" alongside delivered / saved / applied. This is an authorisation widening for the owner's own data, not an eligibility change.
- `GET /watchlist/{entry_id}` reports the sources scanning that employer, open posting count and how many were delivered; the list adds `source_count` and `open_postings`. The client's Watchlist opens a company page: sources (or "No career site registered"), then its scanned postings with verdicts. Watching alone never fetches postings — a source must be registered.
- The feed gains a "Scanned postings (preview)" scope capped at 5 newest, clearly marked as a preview.

Consequences: with today's nine sources only Analog Devices among the twelve watched companies has a career site registered; the other eleven show an honest empty state until a source for them exists (Phenom/custom career sites are not yet supported by a connector). The daily report, priority alerts, quotas and rotation are unchanged.
