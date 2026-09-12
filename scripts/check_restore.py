#!/usr/bin/env python3
"""Compare retained state after a restore without running any workers."""

import hashlib
import os

import psycopg
from psycopg import sql

TABLES = [
    "users",
    "jobs",
    "job_snapshots",
    "job_sources",
    "job_evaluations",
    "saved_job_versions",
    "user_job_state",
    "user_job_events",
    "applications",
    "application_events",
    "reports",
    "report_jobs",
    "company_cycles",
    "company_cycle_usage",
    "initial_deliveries",
    "job_identity_tombstones",
    "notifications",
    "notification_deliveries",
    "processed_operations",
    "gmail_sync_state",
    "email_messages",
    "email_application_links",
    "review_items",
    "work_items",
    "outbox_events",
]


def summary(url):
    with psycopg.connect(url.replace("postgresql+psycopg:", "postgresql:", 1)) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        values = {"schema": sorted(row[0] for row in conn.execute("SELECT version_num FROM alembic_version"))}
        # Server cursors bound memory instead of aggregating permanent history into one SQL string.
        for index, table in enumerate(TABLES):
            digest, count = hashlib.sha256(), 0
            with conn.cursor(name=f"restore_check_{index}") as cursor:
                cursor.itersize = 256
                cursor.execute(
                    sql.SQL("SELECT to_jsonb(t)::text FROM {} t ORDER BY t.id").format(sql.Identifier(table))
                )
                for (logical_row,) in cursor:
                    encoded = logical_row.encode("utf-8")
                    digest.update(len(encoded).to_bytes(8, "big"))
                    digest.update(encoded)
                    count += 1
            values[table] = count
            values[table + "_content"] = digest.hexdigest()
        return values


if __name__ == "__main__":
    original = summary(os.environ["DATABASE_URL"])
    restored = summary(os.environ["RESTORE_DATABASE_URL"])
    if original != restored:
        raise SystemExit("Restored data differs; do not activate this restored deployment")
    print("Restored retained state, snapshots, history, schema and complete work/outbox contents match.")
