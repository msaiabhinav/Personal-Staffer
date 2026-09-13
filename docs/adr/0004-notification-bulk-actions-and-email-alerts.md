# ADR 0004 — Notification bulk actions and what the owner is alerted about

Status: accepted, owner request on 12 September 2026 ("add mark as read and delete all notifications; I want notifications mainly when a watchlist company's career site shows a relevant job and when I get an email regarding any job").

Context: the one-time Gmail history import created 299 `EMAIL_REVIEW` alerts titled "Application email needs review" with no way to clear them except one at a time. Watchlist job alerts already exist (`PRIORITY_JOB`, priority reason `WATCHLIST`, published by `deliver_priority` after every source run), but employer emails that auto-linked to an application as evidence only produced no alert at all.

Decision:

- Two owner-scoped bulk mutations behind the same idempotent command path as every other write: `POST /notifications/read-all` (reads every unread row, each keeps its own revision history) and `POST /notifications/delete-all` with `{"read_only": true|false}`. Deletion removes only the alert rows (and their push-delivery attempts); jobs, applications, reviews and reports are never touched. Each removed row is a tombstone in `/sync/changes`, so every device drops its copy; an undelivered push for a removed row resolves as `MISSING`, as before.
- Every employer email about an application now alerts: an auto-linked status change keeps `APPLICATION_STATUS`; an auto-linked evidence-only email adds `APPLICATION_EMAIL` ("<Company>: new email", opens the application); an email that needs the owner's decision keeps `EMAIL_REVIEW` but is titled "Email from <sender>" with the subject in the body, so it can be triaged from the toast.
- The Notifications page gains Mark all read, a Delete menu (read only / everything, confirmed first) and a type filter (Watchlist jobs / Job emails / Reports). The filter is a client-side view over the exact server types; nothing is hidden from sync.

Not done (deliberately): no per-type push preference yet. The daily report alert stays; if the owner later wants only the two kinds they named, a per-type toggle in Settings is the next step and would suppress delivery, never creation.
