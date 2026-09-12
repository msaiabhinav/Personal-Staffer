#!/usr/bin/env python3
"""Stream pg_dump directly to encrypted restic; never write a plaintext mailbox backup."""

import argparse
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

TLS_OPTIONS = {
    "sslmode": "PGSSLMODE",
    "sslrootcert": "PGSSLROOTCERT",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "sslcrl": "PGSSLCRL",
    "sslcrldir": "PGSSLCRLDIR",
    "channel_binding": "PGCHANNELBINDING",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "gssencmode": "PGGSSENCMODE",
    "target_session_attrs": "PGTARGETSESSIONATTRS",
    "ssl_min_protocol_version": "PGSSLMINPROTOCOLVERSION",
    "ssl_max_protocol_version": "PGSSLMAXPROTOCOLVERSION",
}


def database_environment(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"postgresql", "postgresql+psycopg"}
        or not parsed.hostname
        or not parsed.username
        or parsed.fragment
    ):
        raise ValueError("An explicit PostgreSQL host, user and database are required")
    database = unquote(parsed.path.removeprefix("/"))
    # pg_restore --dbname also accepts connection strings: never let a decoded
    # database component change the verified host/user or bypass restore isolation.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$-]{0,62}", database):
        raise ValueError("Use a simple explicit PostgreSQL database name")
    values = {
        "PGHOST": parsed.hostname,
        "PGPORT": str(parsed.port or 5432),
        "PGUSER": unquote(parsed.username),
        "PGPASSWORD": unquote(parsed.password or ""),
        "PGDATABASE": database,
        "PGCONNECT_TIMEOUT": "15",
    }
    if any(any(c in value for c in "\r\n\x00") for value in values.values()):
        raise ValueError("Control characters are not allowed in database configuration")
    options = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    seen = set()
    for key, value in options:
        if key not in TLS_OPTIONS or key in seen or not value or any(c in value for c in "\r\n\x00"):
            raise ValueError("Unsupported or duplicated PostgreSQL connection option")
        seen.add(key)
        values[TLS_OPTIONS[key]] = value
    # Ambient libpq options (especially PGHOSTADDR/PGSERVICE) must not override
    # the explicit URL. Keep restic/cloud transport configuration available.
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("PG", "GOOGLE_", "TOKEN_ENCRYPTION_", "PEOPLE_", "USAJOBS_", "FCM_"))
        and k not in {"DATABASE_URL", "RESTORE_DATABASE_URL"}
    }
    return {**env, **values}


@contextmanager
def protected_database_environment(url):
    env = database_environment(url)
    password = env.pop("PGPASSWORD")
    # A private, short-lived pgpass file avoids passwords in argv or child env.
    with tempfile.TemporaryDirectory(prefix="staffer-pgpass-") as folder:
        path = Path(folder) / "pgpass"

        def escape(value):
            return value.replace("\\", "\\\\").replace(":", "\\:")

        fields = [
            env["PGHOST"],
            env["PGPORT"],
            env["PGDATABASE"],
            env["PGUSER"],
            password,
        ]
        with open(path, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
            stream.write(":".join(escape(value) for value in fields) + "\n")
        yield {**env, "PGPASSFILE": str(path)}


def validate_restore_target(source_url, restore_url):
    source, target = database_environment(source_url), database_environment(restore_url)
    # A different database name is mandatory even if the host is another alias.
    if not target["PGDATABASE"].endswith("_restore") or target["PGDATABASE"] == source["PGDATABASE"]:
        raise ValueError("Restore requires a separate database whose name ends in _restore")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("--snapshot", default="latest")
    args = parser.parse_args()
    if not os.getenv("RESTIC_REPOSITORY") or not os.getenv("RESTIC_PASSWORD_FILE"):
        raise SystemExit("Configure an off-server RESTIC_REPOSITORY and protected RESTIC_PASSWORD_FILE")
    if args.operation == "backup":
        with protected_database_environment(os.environ["DATABASE_URL"]) as env:
            # Restic cancels snapshot creation if the invoked pg_dump fails.
            subprocess.run(
                [
                    "restic",
                    "backup",
                    "--stdin-filename",
                    "staffer.dump",
                    "--tag",
                    "personal-staffer",
                    "--stdin-from-command",
                    "--",
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                ],
                env=env,
                check=True,
            )
        subprocess.run(["restic", "check"], check=True)
        print("Encrypted backup completed and repository checked. Restore verification is separate.")
    else:
        source_url, restore_url = (
            os.environ["DATABASE_URL"],
            os.environ["RESTORE_DATABASE_URL"],
        )
        validate_restore_target(source_url, restore_url)
        if args.snapshot != "latest" and not re.fullmatch(r"[a-fA-F0-9]{8,64}", args.snapshot):
            raise SystemExit("Snapshot must be latest or a hexadecimal snapshot ID")
        subprocess.run(["restic", "check"], check=True)
        with protected_database_environment(restore_url) as env:
            producer = subprocess.Popen(
                [
                    "restic",
                    "dump",
                    "--path",
                    "/staffer.dump",
                    args.snapshot,
                    "staffer.dump",
                ],
                stdout=subprocess.PIPE,
            )
            try:
                consumer = subprocess.run(
                    [
                        "pg_restore",
                        "--dbname",
                        env["PGDATABASE"],
                        "--no-owner",
                        "--no-acl",
                        "--exit-on-error",
                    ],
                    env=env,
                    stdin=producer.stdout,
                    check=False,
                )
            finally:
                producer.stdout.close()
            if producer.wait() or consumer.returncode:
                raise SystemExit("Restore failed; inspect isolated target before proceeding")
        print("Restored to isolated target. Keep workers stopped until invariants and outbox history are verified.")


if __name__ == "__main__":
    main()
