"""Check the optional installed interface without calling any scraper."""

import importlib.metadata
import inspect
import json
import socket
import sys
from pathlib import Path


def deny_connection(*args, **kwargs):
    raise RuntimeError("Network calls are prohibited during this interface check")


socket.create_connection = deny_connection
socket.socket.connect = deny_connection
socket.socket.connect_ex = deny_connection
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from jobspy import scrape_jobs

from app.connectors.jobspy_adapter import ALLOWED_SITES, JobSpyConnector

assert sys.version_info[:2] == (3, 12), "The optional JobSpy group requires Python 3.12"
assert importlib.metadata.version("python-jobspy") == "1.1.82"
signature = inspect.signature(scrape_jobs)
for site in sorted(ALLOWED_SITES):
    connector = JobSpyConnector(site=site, enabled=True)
    assert connector.health().state == "BLOCKED"
    assert connector.health().last_error.code == "BLOCKED_SECURITY"
    options = connector.query_options("data analyst")
    assert set(options) <= set(signature.parameters), "An option is no longer an explicit upstream parameter"
    signature.bind(**options)
    assert options["site_name"] == [site] and site != "linkedin"
    assert options["proxies"] is None and options["enforce_annual_salary"] is False
    assert not {"hours_old", "job_type", "is_remote"} <= set(options)
print(
    json.dumps(
        {
            "package": "python-jobspy",
            "version": "1.1.82",
            "sites_checked": sorted(ALLOWED_SITES),
            "interface": "PASS",
            "scraping_performed": False,
            "runtime_activation": "BLOCKED_SECURITY",
        }
    )
)
