# Backup and restore

**A real backup/restore drill has not run in this restricted Linux environment.** PostgreSQL cannot start here and no off-server destination was supplied. The CI workflow includes an actual PostgreSQL logical dump/clean restore with retained data comparison; it has been prepared, not executed remotely.

## Encrypted backup

Install a compatible PostgreSQL 17 client and restic with `--stdin-from-command` support on the server/backup worker. Configure DATABASE_URL, off-server RESTIC_REPOSITORY and RESTIC_PASSWORD_FILE (protected file). Initialize the repository explicitly with `restic init` only for a new empty backup target. From repo root:

```bash
python scripts/backup.py backup
```

The script uses restic `--stdin-from-command` to stream pg_dump directly into encrypted storage. A failed dump command fails the backup, then a successful backup runs `restic check`. PostgreSQL TLS parameters are preserved; a mode-0600 temporary pgpass file supplies database credentials and is removed afterward. It never writes a plaintext mailbox/database dump to disk. Keep the mailbox encryption key and necessary configuration in separately protected recovery storage; a database dump alone cannot recover encrypted provider credentials. Do not store recovery keys only on the VPS.

Schedule daily after confirming a first successful backup. Suggested retention: seven daily, four weekly, six monthly (`restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6`); review snapshots before applying pruning. Daily backup can lose about 24 hours of changes after total host loss; choose a shorter interval if necessary. Monitor age and failed backups.

## Clean isolated restore

Create a fresh database ending `_restore`. Set both DATABASE_URL (original) and RESTORE_DATABASE_URL (target), using distinct decoded database names. The restore script rejects ambiguous connection-string names and inherited connection overrides. Keep all writers, workers and dispatchers stopped on both compared databases:

```bash
python scripts/backup.py restore --snapshot latest
cd backend
uv run python ../scripts/check_restore.py
```

Comparison reads repeatable, read-only snapshots and streams deterministic SHA-256 hashes for retained records, saved/applied evidence, histories, report/cycle identities, Gmail progress, reviews, notifications, idempotency results and complete work/outbox state. It avoids aggregating the full permanent history into one SQL value. Inspect pending work/notification delivery state before enabling reconciliation. Processed history must stay processed; original queued work may legitimately recover. At-least-once push can repeat a hint after a crash, so inbox event keys remain authoritative. Do not mass-reset notification deliveries to PENDING after restore.

## Failure runbook

Failed migration: stop writers, preserve logs/backup, restore in isolation or roll back compatible code. Revoked Gmail: reconnect via Settings; jobs/manual tracking continue. Expired TLS: check DNS/challenge reachability and Caddy logs. Full disk: stop raw acquisition, preserve user records, free only documented transient data and repair backup health. Redis restart: dispatcher reconstructs work from PostgreSQL. Unavailable source: show BLOCKED/RATE_LIMITED/FAILED, back off and use healthy sources. Never delete saved/applied snapshots as cleanup.
