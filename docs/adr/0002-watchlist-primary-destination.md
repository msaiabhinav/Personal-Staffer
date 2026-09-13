# ADR 0002 — Watchlist as a sixth primary destination, appearance modes and browser-style history

Status: accepted, product decision by the owner on 12 September 2026.

PR-17 fixed five primary destinations (Notifications, Homepage, People, Saved Jobs, Applied Jobs) and placed Watchlist inside Settings. The owner asked for Watchlist in the side navigation. The five original destinations keep their labels and order; **Watchlist** is appended as the sixth. Settings keeps a link to it. The exact-navigation test (AT-60) now asserts the six-item order, and the demo seed registers the specification's eleven priority employers so the destination has real content in DEMO_MODE. Watchlist behavior is unchanged: entries are additional to the daily quota and rotation and never bypass hard eligibility (PR-12).

The owner also asked for a dark appearance and a richer visual treatment. Two palettes are defined in `client/lib/core/theme.dart`; since 13 September 2026 they follow the owner's logo ("Parchment" light: cream canvas, espresso ink, gold accent; "Espresso" dark: dark-roast canvas, gold accent), with the espresso badge colour as the sidebar in both modes. The preference (System/Light/Dark) is device-local, persisted through the platform secure store, and is not synchronized account state. Color is never the only carrier of meaning; status pills carry text.

Browser-style Back/Forward controls (always visible, Alt+Left/Alt+Right) keep a linear history of visited shell locations in `client/lib/core/history.dart`, independent of go_router's replaced stack. Login redirects are not recorded.

Requirement impact: PR-17's wording ("exact five-item navigation") is superseded by this decision for the primary destinations; the Homepage's two tabs are unchanged. REQUIREMENTS.md and BUILD_SPECIFICATION references should be read with this ADR.
