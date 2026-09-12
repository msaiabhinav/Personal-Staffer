#!/usr/bin/env python3
"""Run one complete backend debugging pass and retain honest command results.

From repository root: python scripts/verify_backend.py --pass-number 1
Database tests require TEST_DATABASE_URL; pytest records actual skips in JUnit.
Native and provider/device verification are separate, never implied by this script.
"""

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pass-number", type=int, choices=(1, 2), required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    backend = root / "backend"
    evidence = root / "docs" / "verification"
    evidence.mkdir(parents=True, exist_ok=True)
    prefix = f"backend-pass-{args.pass_number}"
    commands = [
        ("lock", ["uv", "lock", "--check"]),
        ("lint", ["uv", "run", "ruff", "check", "app", "tests", "../scripts"]),
        (
            "format",
            ["uv", "run", "ruff", "format", "--check", "app", "tests", "../scripts"],
        ),
        (
            "compile",
            [
                "uv",
                "run",
                "python",
                "-m",
                "compileall",
                "-q",
                "app",
                "tests",
                "../scripts",
            ],
        ),
        (
            "tests",
            ["uv", "run", "pytest", "-q", f"--junitxml={evidence / (prefix + '.xml')}"],
        ),
        ("policy-replay", ["uv", "run", "python", "-m", "app.cli", "replay-fixtures"]),
        ("migration-render", ["uv", "run", "alembic", "upgrade", "head", "--sql"]),
    ]
    # Import every application module in a new process, catching import-order defects
    # that one combined test process can mask. No module may contact providers on import.
    for path in sorted((backend / "app").rglob("*.py")):
        module = ".".join(path.relative_to(backend).with_suffix("").parts)
        commands.append((f"import-{module}", ["uv", "run", "python", "-c", f"import {module}"]))
    results = []
    for name, command in commands:
        started = time.monotonic()
        log = evidence / f"{prefix}-{name}.log"
        with log.open("w") as output:
            try:
                result = subprocess.run(
                    command,
                    cwd=backend,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=180,
                    check=False,
                )
                code = result.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                output.write(f"Verification command unavailable or timed out: {type(exc).__name__}\n")
                code = 125
        results.append(
            {
                "name": name,
                "command": command,
                "exit_code": code,
                "seconds": round(time.monotonic() - started, 2),
                "log": log.name,
            }
        )
        if not name.startswith("import-") or code:
            print(f"{name}: {'PASS' if code == 0 else 'FAILED'}", flush=True)
    passed = all(item["exit_code"] == 0 for item in results)
    (evidence / f"{prefix}.json").write_text(
        json.dumps(
            {
                "at_utc": datetime.now(UTC).isoformat(),
                "passed": passed,
                "results": results,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        f"{len(results)} commands; {'all passed' if passed else 'inspect failures'}. PostgreSQL skips remain unverified."
    )
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
