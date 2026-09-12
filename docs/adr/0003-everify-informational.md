# ADR 0003 — E-Verify becomes informational for this owner

Status: accepted, owner decision on 12 September 2026 ("forget about E-Verify; it is difficult to identify").

PR-05 and the policy defaults made confirmed E-Verify legal-employer evidence a hard gate: unknown or conflicting evidence withheld delivery. The first live source run on the laptop (Oscar Health, 288 postings) withheld every posting on that gate because no reviewed legal-entity evidence exists and no automated public E-Verify lookup is available. The owner decided that E-Verify should not block delivery.

Decision: a policy switch `EVERIFY_GATE` (`REQUIRED` | `INFORMATIONAL`). The specification default in code and `.env.example` remains `REQUIRED`; the owner's `.env.local` sets `INFORMATIONAL`. In informational mode the `everify` rule never withholds: its decision becomes `PASS` with the original reason suffixed `_INFORMATIONAL` and the flag `EVERIFY_INFORMATIONAL`, the evidence references are retained, and the `everify` fact keeps its honest state (`UNKNOWN`, `KNOWN`, `CONFLICTING`). Confirmed evidence evaluates exactly as before; nothing ever labels an employer "E-Verify confirmed" without matching reviewed evidence. The test suite pins `REQUIRED` for every test (conftest) so specification behaviour stays verified regardless of the host configuration.

Consequences: delivered jobs may come from employers whose E-Verify participation is unknown; the client must show that state as "Unknown", not as a confirmation. Sponsorship, clearance, employment type, freshness, geography, experience, relevance and active-opening gates are unchanged. Reverting to the specification gate is a one-line configuration change.
