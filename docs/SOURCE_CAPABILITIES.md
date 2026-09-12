# Source capabilities and feasibility checkpoint

Observed on 2026-09-12. This document distinguishes implemented code, recorded live access, and production activation. No company in this experiment has been confirmed in E-Verify; none of these records is an approved recommendation.

## Executable connectors

All job connectors expose typed `discover`, `fetch`, `normalize`, `verify_opening`, and `health` contracts in `backend/app/connectors/`. `get_connector(source_type)` selects executable job connectors. The catalog explicitly labels sources that only have directory-link discovery.

| Source | Working code and deterministic checks | Observed access and remaining limitations |
|---|---|---|
| Ashby | Employer-board discovery; bounded instance cache with preserved observation time; full JD; full-time/location/compensation evidence; last-publication semantics; opening link checks | Ramp, Notion and Abacum JSON obtained; one real payload each normalized. Ramp initial probe returned 403 and the later bounded corpus probe returned 200. OpenAI board exceeded the 12 MiB feasibility limit. No global search API. Reposts and employer evidence still require independent checks. |
| Greenhouse | Board list and detail fetch; identity check; full JD; first_published and updated_at kept distinct; office/custom-field evidence | Eight boards returned JSON and recorded jobs normalized. Current live list records supplied first_published; detail also documents that field. Do not rely on updated_at when first_published is absent. Employment type and country can still be missing. |
| Lever | Bounded board pagination/detail; required/preferred lists and closing notices preserved; country and commitment evidence; exact salary interval retained | Spotify public list returned two real payloads. createdAt was present but is deliberately not promoted to original publication without a proven source contract. Therefore freshness commonly needs official-page enrichment. |
| SmartRecruiters | Bounded list/detail; active flag; full JD sections; releasedDate; application URL; country/employment evidence | Visa endpoint returned HTTP 200 with empty content; this is endpoint access, not a verified populated tenant/detail. Synthetic detail/closed cases tested. releasedDate is treated conservatively as last publication. |
| Workday | Selected public tenant CXS search POST and detail GET; full jobPostingInfo; explicit errors and tenant URL validation | Analog Devices public CXS search returned two postings and reported 259 matches. CXS is experimental per-tenant website integration, not a guaranteed stable global API. Detail/production smoke and tenant-specific startDate semantics remain unverified; postedOn is not exact publication. |
| Employer career pages | Static JSON-LD JobPosting/@graph reader; typed normalization; exact/uncertain dates; safe description/link handling | Works for pages exposing that structured schema; no JavaScript is executed. Ordinary 200 career homepages do not imply job coverage. JS-only sites have explicit incomplete coverage. |
| University portals | Can use reviewed direct JSON-LD/ATS tenant connectors | Five universities included in feasibility probes. Generic university portal automation is not implemented. These homepages/redirects establish neither jobs nor complete university coverage. |
| JobSpy: Indeed, Google, Glassdoor, ZipRecruiter | Explicit site allowlist; independent source calls; pagination bounds; compatible Indeed time-filter strategy; no annual salary conversion; NaN handling; subprocess timeout/output limits; failures/empty uncertainty retained | Optional python-jobspy==1.1.82 is locked in the nondefault jobspy dependency group; real import and all four site-option signatures were checked in an isolated Python 3.12 environment. Dependency audit found CVE-2025-46656 in upstream-constrained markdownify; real execution is BLOCKED_SECURITY even when enabled. No live scrape was performed. See JOBSPY_SETUP.md. Adapter results always require independent complete-JD/eligibility verification; no result is silently accepted. LinkedIn is forbidden. |
| USAJOBS | Official search API with Fields=Full; page bounds; complete-description check; explicit key/user-agent validation | NOT_CONFIGURED until USAJOBS_API_KEY and registered USAJOBS_USER_AGENT are supplied securely. No live authenticated API call performed. A “public” audience never implies eligibility for this user. |
| Wellfound; Welcome to the Jungle | Reviewed public-directory static external-link lead extraction | No authenticated/job-feed connector. Static links are unverified leads only; source-specific job discovery remains incomplete. |
| YC; a16z; Sequoia; USV | Same bounded public-directory external-link lead extraction | No global company database integration or verified funding/office facts. Internal directory pages require further source-specific discovery; no claims of complete startup coverage. |
| LinkedIn jobs | Disabled by product policy and connector factory/URL tests | No job source, login, cookie handling or scraping. Public professional People links are a separate domain. |

## Bounded employer/source experiments

The main experiment attempted 30 employer URLs, plus two E-Verify endpoints, at concurrency four, maximum 15 seconds per request, no redirects followed, no login, no retries or proxy rotation, and maximum 12 MiB per response. Four additional source-specific probes checked Lever, SmartRecruiters, Workday and the current E-Verify search URL at 12 seconds each. This was read-only public retrieval, including the documented read-only CXS search POST.

The environment requires its managed egress proxy and does not resolve public DNS using `socket.getaddrinfo`. The **production SafeHTTPClient was not weakened** to fit that environment. The feasibility experiment used the environment's provided transport for fixed public source URLs and recorded its mechanism in every record. Those observations validate real public payload shape and normalization, not production socket/TLS connectivity. Direct production client smoke is blocked here by DNS_UNAVAILABLE. This distinction also applies to source-to-database replay.

11 ATS boards yielded 1,791 raw source records in this one observation. That is a sum of provider rows, not distinct jobs, eligible jobs, or deliverable jobs. One selected real payload from each board is retained; the selection was title-oriented for parser testing and does not claim role eligibility. Candidate startup-pool labels below are investigation pools, **not verified company geography**. No office, funding-stage or legal-entity facts were invented.

| Employer / target | Investigation pool | Source | Outcome | HTTP | Source job count |
|---|---|---|---|---:|---:|
| [HCA Healthcare](https://careers.hcahealthcare.com/) | WATCHLIST | direct | BLOCKED | 403 | — |
| [Henry Ford Health](https://henryford.referrals.selectminds.com/) | WATCHLIST | direct | FETCHED | 200 | — |
| [Infosys](https://digitalcareers.infosys.com/) | WATCHLIST | direct | REDIRECT | 302 | — |
| [Cognizant](https://careers.cognizant.com/us/en) | WATCHLIST | direct | BLOCKED | 403 | — |
| [Tata Consultancy Services](https://www.tcs.com/careers/united-states) | WATCHLIST | direct | FETCHED | 200 | — |
| [Thermo Fisher Scientific](https://jobs.thermofisher.com/global/en) | WATCHLIST | direct | FETCHED | 200 | — |
| [Walmart](https://careers.walmart.com/) | WATCHLIST | direct | REDIRECT | 308 | — |
| [Amazon](https://www.amazon.jobs/en/search?base_query=data+analyst&loc_query=United+States) | WATCHLIST | direct | FETCHED | 200 | — |
| [Microsoft](https://careers.microsoft.com/) | WATCHLIST | direct | REDIRECT | 302 | — |
| [Tesla](https://www.tesla.com/careers/search/) | WATCHLIST | direct | FETCHED | 200 | — |
| [Analog Devices](https://analogdevices.wd1.myworkdayjobs.com/External) | WATCHLIST | workday | FETCHED | 200 | — |
| [Yale University](https://careers.yale.edu/) | UNIVERSITY | direct | REDIRECT | 303 | — |
| [University of Connecticut](https://jobs.uconn.edu/) | UNIVERSITY | direct | REDIRECT | 302 | — |
| [Harvard University](https://careers.harvard.edu/) | UNIVERSITY | direct | FETCHED | 200 | — |
| [Stanford University](https://careersearch.stanford.edu/) | UNIVERSITY | direct | REDIRECT | 301 | — |
| [Columbia University](https://opportunities.columbia.edu/) | UNIVERSITY | direct | REDIRECT | 302 | — |
| [Ramp](https://api.ashbyhq.com/posting-api/job-board/ramp?includeCompensation=true) | NYC_CANDIDATE | ashby | FETCHED | 200 | 145 |
| [Clay](https://api.ashbyhq.com/posting-api/job-board/clay?includeCompensation=true) | NYC_CANDIDATE | ashby | HTTP_ERROR | 404 | — |
| [Mercury](https://boards-api.greenhouse.io/v1/boards/mercury/jobs?content=true) | BAY_AREA_CANDIDATE | greenhouse | FETCHED | 200 | 61 |
| [Vercel](https://boards-api.greenhouse.io/v1/boards/vercel/jobs?content=true) | NYC_CANDIDATE | greenhouse | FETCHED | 200 | 86 |
| [Cockroach Labs](https://boards-api.greenhouse.io/v1/boards/cockroachlabs/jobs?content=true) | NYC_CANDIDATE | greenhouse | FETCHED | 200 | 20 |
| [Oscar Health](https://boards-api.greenhouse.io/v1/boards/oscar/jobs?content=true) | NYC_CANDIDATE | greenhouse | FETCHED | 200 | 289 |
| [Flatiron Health](https://boards-api.greenhouse.io/v1/boards/flatironhealth/jobs?content=true) | NYC_CANDIDATE | greenhouse | FETCHED | 200 | 28 |
| [Anthropic](https://boards-api.greenhouse.io/v1/boards/anthropic/jobs?content=true) | BAY_AREA_CANDIDATE | greenhouse | FETCHED | 200 | 595 |
| [OpenAI](https://api.ashbyhq.com/posting-api/job-board/openai?includeCompensation=true) | BAY_AREA_CANDIDATE | ashby | PAYLOAD_TOO_LARGE | 200 | — |
| [Notion](https://api.ashbyhq.com/posting-api/job-board/notion?includeCompensation=true) | BAY_AREA_CANDIDATE | ashby | FETCHED | 200 | 127 |
| [Retool](https://boards-api.greenhouse.io/v1/boards/retool/jobs?content=true) | BAY_AREA_CANDIDATE | greenhouse | HTTP_ERROR | 404 | — |
| [Figma](https://boards-api.greenhouse.io/v1/boards/figma/jobs?content=true) | BAY_AREA_CANDIDATE | greenhouse | FETCHED | 200 | 153 |
| [Brex](https://boards-api.greenhouse.io/v1/boards/brex/jobs?content=true) | BAY_AREA_CANDIDATE | greenhouse | FETCHED | 200 | 273 |
| [Abacum](https://api.ashbyhq.com/posting-api/job-board/abacum?includeCompensation=true) | NYC_CANDIDATE | ashby | FETCHED | 200 | 14 |
| [E-Verify lookup](https://www.e-verify.gov/about-e-verify/e-verify-data/how-to-find-participating-employers) | EVIDENCE | everify | BLOCKED | 403 | — |
| [E-Verify employer search](https://e-verify.uscis.gov/empSearch/) | EVIDENCE | everify | HTTP_ERROR | 502 | — |

Redirect outcomes intentionally did not follow the destination during this bounded experiment. A 404 board slug is an unresolved board mapping, not proof the company has no jobs. A 403/502/oversize response is not converted to an empty success.

## Evidence artifacts and commands

- `backend/tests/fixtures/connectors/source_probes_real.json`: exact per-target observation time, request URL, outcomes, counts, response hash and transport mechanism.
- `*_real.json`: original selected job fields with parent request provenance, explicitly synthetic=false. Parent raw_sha256 hashes the full board response; the retained record is a selected subset, not a full-board snapshot.
- `*_real_normalized.json`: corresponding normalized snapshots. These have no E-Verify confirmation or active-link guarantee; Ashby repost_checked remains false.
- `additional_source_access.json`: recorded additional Lever, SmartRecruiters, Workday and E-Verify probes.
- `runtime_smoke.json`: executed production SafeHTTPClient Ashby attempt returned FAILED/DNS_UNAVAILABLE, with incomplete coverage and an explicit error; no network bypass.
- Synthetic boundary cases live in test code and are never claimed as real jobs or real employers.

From `backend/`:

```bash
uv run pytest tests/test_connectors.py tests/test_connectors_safe_http.py -q
uv run ruff check app/connectors tests/test_connectors.py tests/test_connectors_safe_http.py
```

Executed scoped connector verification: **51 source-contract tests and 23 SafeHTTP tests passed**; ruff check passed. The latest isolated source-contract run passed 51 tests with zero warnings after the JobSpy security guard; the earlier 82-test security/configuration/HTTP run had three upstream dependency deprecation warnings. Tests cover successful source contracts, real replay, unsafe URLs/private and metadata addresses, mixed DNS answers, DNS pinning, redirects and secret stripping, byte limit, backoff, closed-vs-blocked pages, preserved qualifications, last-publication semantics, date uncertainty, and explicit optional configuration. Network tests are not silently run with ordinary pytest. Database ingestion/worker/report checks are tracked in BUILD_STATUS and TEST_RESULTS.

## Source safety and operating bounds

`SafeHTTPClient` uses validated public IPs pinned to the actual socket; original hostname remains the TLS verification/SNI identity. It checks every redirect, refuses HTTPS downgrade, ignores ambient proxy settings/credentials, strips authorization secrets on cross-origin redirects, disallows metadata/private/loopback/multicast/reserved addresses and non-HTTP schemes, and allows only ports 80/443. DNS concurrency is bounded to four. Defaults: connect 10 seconds, total request 30 seconds, at most three attempts, three redirects, response cap 8 MiB. Responses that ignore identity encoding and remain compressed are refused by the bounded reader; a compression-aware reader is future work, never unlimited decompression. HTTP 403 is not retried; 429/5xx honor Retry-After within the remaining request budget and expose rate-limited health. Safe source failure never supplies a complete JD.

Descriptions are converted to safe readable text plus sanitized formatting and public HTTP(S) links. Scripts, event handlers, frames and other active content cannot survive in generated HTML. Source text is data, not instructions. The JobSpy process has no backend provider secrets in its environment, an execution timeout, Linux output/CPU limits, and explicit allowlisted sites; its third-party networking remains an additional release qualification before enabling it on a production worker.

No paid provider has been purchased. Public ATS endpoints do not provide guaranteed availability, nationwide coverage, or a supply of 50 qualifying jobs daily. Keep an employer registry and review real accepted/withheld results over multiple days before release.

## Official references consulted

- [Ashby public postings](https://developers.ashbyhq.com/docs/public-job-posting-api): publishedAt describes last publication; employer board name is required.
- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html): public GET access, detail fields, first_published, updated_at, and application questions.
- [Lever maintained postings API repository](https://github.com/lever/postings-api): public employer-scoped posting contract and full description components.
- [SmartRecruiters objects](https://developers.smartrecruiters.com/docs/objects) and [endpoints](https://developers.smartrecruiters.com/docs/endpoints): live/unpublished flag and posting/application fields.
- [JobSpy maintained repository](https://github.com/speedyapply/JobSpy): compatible search options, supported site identifiers and output limitations. Its suggestions about proxy evasion are not implemented.
- [USAJOBS authentication](https://developer.usajobs.gov/guides/authentication) and [search reference](https://developer.usajobs.gov/api-reference/get-api-search): required key/user-agent and full-field request option.
- [Schema.org JobPosting](https://schema.org/JobPosting) and [Google job structured-data guide](https://developers.google.com/search/docs/appearance/structured-data/job-posting): explicit publication/location/expiry fields and why stale structured data is not sufficient proof of an active opening.
- [E-Verify Employer Search](https://www.e-verify.gov/e-verify-employer-search): discoverable official lookup, but direct access returned 403 in this environment. See EVERIFY_WORKFLOW.
