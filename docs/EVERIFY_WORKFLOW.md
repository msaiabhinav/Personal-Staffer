# E-Verify evidence register and pilot workflow

## Current verified state

**No real employer has been confirmed in this build.** The official [E-Verify Employer Search](https://www.e-verify.gov/e-verify-employer-search) is discoverable in official search results, but fetching it returned HTTP 403. An older official lookup URL also returned 403; `https://e-verify.uscis.gov/empSearch/` returned 502. The [official updated-tool announcement](https://www.e-verify.gov/about-e-verify/whats-new/e-verify-employer-search-tool-updated) also could not be opened directly. There is no verified working public automated lookup API or usable bulk export in this build.

Those outcomes are source-access blockers, not evidence that a company does or does not participate. The real ATS payloads in `backend/tests/fixtures/connectors/` contain no E-Verify confirmation. Do not derive participation from an employer's brand, reputation, visa history, ordinary work-authorization text, a search snippet, or a source name ending in “verified”.

The reviewed evidence register is the intended pilot fallback. It can support employer-by-employer activation when an authorized reviewer can inspect official evidence. It does not establish automated nationwide coverage. Continue other connectors, saved/applied tracking, email integration and client work while this gate remains unresolved.

## Three separate identities

1. **Employer group** is the explicitly documented company grouping used for the shared 32-day rotation.
2. **Displayed brand** is the name the person recognizes in the job feed.
3. **Legal employing entity** is the organization that would actually employ/payroll this particular opening.

Participation evidence belongs to the legal entity. A parent company's record does not approve a subsidiary. A client's record does not approve a staffing firm's payroll placement. Alias mappings need their own source, reviewer and observation time. If the JD/official employer record does not resolve the actual entity, leave `jobs.entity_id` unknown and withhold new recommendations.

## Obtain and review evidence

Inspect the official employer-search result through normal public access if it is available to the reviewer. Preserve the legal name exactly as displayed, context/address or location where needed to distinguish same-name entities, observed participation state, the specific official source URL/reference, the observation date, and the relevant readable result excerpt. Keep a local evidence snapshot or retained official reference. Do not solve access blocks using account cookies, CAPTCHA bypass, impersonation, rotating proxies or unofficial scraped lists.

A **search miss is UNKNOWN**, not NO_LONGER_CONFIRMED. Use CONFLICTING when credible evidence disagrees. Use NO_LONGER_CONFIRMED only when reviewed evidence justifies withdrawing prior confirmation, preserving the old record and its history. A screenshot/CSV from an official source can inform review, but the current API consumes the reviewed text and source reference, not unaudited booleans or a binary upload.

## Administrative import

The operator must be signed in as the allowed owner with administrator access. `POST /api/v1/admin/employer-evidence` requires an `Idempotency-Key` and this JSON schema. Values below are **field placeholders, not employer evidence** and must be replaced from an inspected official record; never submit this example as a real confirmation.

```json
{
  "entity_id": "<existing-legal-entity-UUID>",
  "status": "CONFIRMED",
  "legal_name_as_found": "<exact official legal entity name>",
  "source_reference": "https://www.e-verify.gov/<actual-inspected-official-reference>",
  "snapshot": "<relevant official result text with legal name and participation context>",
  "checked_at": "<actual-observation-time-with-UTC-offset>",
  "verification_method": "REVIEWED_OFFICIAL_SOURCE",
  "synthetic": false
}
```

The entity must already exist in the employer register; registering an ATS tenant or watchlist brand does not create or verify the legal entity. Use the reviewed entity-registration mechanism documented in the current CLI/OpenAPI. Do not substitute the brand row's UUID for an entity UUID. If entity-registration UI is unavailable, keep that activation dependency visible in CONTINUATION instead of inventing an entity association.

The implementation validates administrator identity, an exact legal-name match to the selected entity, official E-Verify/USCIS source hostname for confirmation, presence of the legal name in the excerpt, an aware observation timestamp that is not implausibly future-dated, and explicit evidence method. It hashes the retained excerpt, records the reviewer from the authenticated account, stores an append-only evidence record and a resolved administrative review item, and returns the next required re-evaluation state. These checks establish an auditable review boundary; they cannot make forged operator-supplied content true.

Only `REVIEWED_OFFICIAL_SOURCE` and `OFFICIAL_DATA_IMPORT` are accepted methods. The latter is for actual reviewed official data; no live bulk-import dataset was obtained here. Synthetic evidence is refused except in explicit isolated local DEMO_MODE, and must never be used to approve production recommendations.

## Resolve the actual job employer, then re-evaluate

After creating the entity and importing participation evidence, resolve each actual opening's employing entity using independent job/employer identity evidence. From `backend/`, the implemented command is:

```bash
uv run python -m app.cli resolve-job-employer \
  --job <job-UUID> --entity <entity-UUID> --evidence <reviewed-identity-evidence.json>
```

The evidence JSON requires `source_reference`, `quoted_text`, and `reviewer`. This command checks the entity's employer group, writes an administrative resolution record and runs ordinary job re-evaluation. It does not make an unknown or ineligible opening eligible by fiat. The explicit administrative re-evaluation endpoint is `POST /api/v1/admin/jobs/{job_id}/reevaluate` and uses the same production rules; its current queued/response behavior is defined in OpenAPI.

Both **identity_match** and current official participation evidence must support the same employing entity. Other gates—including complete JD, confirmed full-time/U.S. employment, publication freshness, required experience, sponsorship exclusions, clearance, active application route, role relevance and repost identity—still apply. E-Verify confirmation is not a sponsorship promise.

## Rechecks and retention

`EVERIFY_RECHECK_DAYS` defaults to 30. This is this application's operational evidence-freshness policy, not a government guarantee. A confirmation older than its review deadline cannot approve a new delivery. Recheck sooner when employer identity or participation evidence contradicts the register. A recheck failure should produce a visible review/source-health dependency, not reset checked_at to now.

Retain every prior record, snapshot hash, reviewer and decision so corrections remain explainable. Expired/unconfirmed employer evidence never removes Saved Jobs, applied snapshots, application dates, source URLs or event history. Refreshing evidence re-runs normal rules for future recommendations; it does not bypass the permanent delivered/repost ledger or automatically rediscover old jobs.

## Outstanding release evidence

- Inspect and import at least one real official legal-entity result, plus independently resolve that entity for a real opening.
- Verify due-date rechecks, contradictory evidence and exact-subsidiary behavior in the actual pilot register.
- Measure the fraction of real relevant openings for which legal identity and participation can be established.
- Evaluate whether an official export or permitted automation becomes available; until then report reviewed-register coverage honestly.
- Run a multi-day accepted/withheld-job audit. No minimum daily yield is promised and filters must not be weakened to reach 50.

Access observations are recorded in SOURCE_CAPABILITIES and the source fixture metadata. Automated rule tests cover synthetic current/stale/unknown/conflicting evidence; they do not count as verified participating employers.
