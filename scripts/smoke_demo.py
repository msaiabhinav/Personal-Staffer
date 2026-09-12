#!/usr/bin/env python3
"""Exercise explicit local DEMO against PostgreSQL; preserve useful backup/restore records."""

import os
from uuid import uuid4


def run_workflow(client):
    login = client.post(
        "/api/v1/auth/demo",
        json={
            "device_id": str(uuid4()),
            "platform": "WINDOWS",
            "device_label": "Synthetic workflow verification",
        },
    )
    assert login.status_code == 200, login.text
    assert login.json()["demo_mode"] is True
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    feed = client.get("/api/v1/jobs?scope=priority", headers=headers)
    assert feed.status_code == 200 and len(feed.json()["items"]) == 2, feed.text
    assert all(job["synthetic"] for job in feed.json()["items"])
    job, other = feed.json()["items"]

    def mutate(method, path, body=None):
        response = client.request(
            method,
            "/api/v1" + path,
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json=body,
        )
        assert response.status_code == 200, response.text
        return response.json()

    if not job["application_id"]:
        mutate(
            "PUT",
            f"/jobs/{job['id']}/saved",
            {"saved": True, "expected_revision": job["state"]["revision"]},
        )
        current = client.get(f"/api/v1/jobs/{job['id']}", headers=headers).json()
        applied = mutate(
            "POST",
            f"/jobs/{job['id']}/apply",
            {"expected_revision": current["state"]["revision"]},
        )
        application_id = applied["application_id"]
    else:
        application_id = job["application_id"]
    saved = client.get("/api/v1/saved-jobs", headers=headers).json()["items"]
    assert all(item["id"] != job["id"] for item in saved)
    details = client.get("/api/v1/applications/" + application_id, headers=headers).json()
    assert details["snapshot"]["description"] and details["source_url"]
    assert details["snapshot"]["id"] == details["selected_snapshot_id"]
    # Leave an application plus a saved job for a meaningful restore drill; repeated smoke is safe.
    assert not other["application_id"], "The second demo job was already applied; use a separate smoke-test database."
    mutate(
        "PUT",
        f"/jobs/{other['id']}/saved",
        {"saved": True, "expected_revision": other["state"]["revision"]},
    )
    inbox = client.get("/api/v1/notifications", headers=headers).json()
    assert inbox["items"]
    notification = inbox["items"][0]
    opened = mutate("POST", "/notifications/" + notification["id"] + "/open")
    assert opened["destination"] == f"personalstaffer://{notification['target_type']}/{notification['target_id']}"
    dashboard = client.get("/api/v1/dashboard", headers=headers).json()
    assert dashboard["total"] == 1
    return {
        "application_id": application_id,
        "saved_job_id": other["id"],
        "demo_mode": True,
        "notifications": len(inbox["items"]),
    }


def main():
    # Never override an operator's staging/production configuration just to run a smoke test.
    if os.environ.get("APP_ENV") != "local" or os.environ.get("DEMO_MODE", "").lower() != "true":
        raise SystemExit("Set APP_ENV=local and DEMO_MODE=true against a separate migrated PostgreSQL database.")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        run_workflow(client)
    print("Synthetic API workflow: login, retained feed, save, apply, snapshot, inbox navigation passed on PostgreSQL.")


if __name__ == "__main__":
    main()
