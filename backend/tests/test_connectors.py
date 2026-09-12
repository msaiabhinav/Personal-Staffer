import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.connectors import (
    AshbyConnector,
    Candidate,
    FetchResult,
    GreenhouseConnector,
    LeverConnector,
    SmartRecruitersConnector,
    get_connector,
)
from app.connectors.direct import DirectConnector, DirectoryDiscovery, jobpostings
from app.connectors.jobspy_adapter import JobSpyConnector
from app.connectors.parsing import publication, readable_html, sanitized_html
from app.connectors.safe_http import HTTPResult, SourceHTTPError
from app.connectors.usajobs import USAJobsConnector
from app.connectors.workday import WorkdayConnector, tenant_parts

NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


class FakeClient:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append((url, headers))
        response = self.values.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, HTTPResult):
            return response
        return HTTPResult(200, json.dumps(response).encode(), url, {})

    def post_json(self, url, body, headers=None):
        self.calls.append(("POST_BODY", body))
        return self.get(url, headers)


def fetched(source, data, *, external_id="j1", tenant="example", complete=True):
    c = Candidate(
        source_type=source,
        tenant=tenant,
        external_id=external_id,
        source_url="https://jobs.example.com/jobs/" + external_id,
        employer_name="Example Synthetic Employer",
    )
    return FetchResult(
        candidate=c,
        outcome="SUCCESS",
        payload=data,
        description_complete=complete,
        source_url=c.source_url,
        fetched_at=NOW,
    )


ASHBY = {
    "id": "j1",
    "title": "Data Analyst",
    "descriptionHtml": "<h2>Required</h2><p>2 years. Build SQL dashboards.</p>",
    "employmentType": "FullTime",
    "isListed": True,
    "publishedAt": "2026-09-11T12:00:00Z",
    "address": {"postalAddress": {"addressCountry": "USA", "addressRegion": "CT"}},
    "location": "New Haven, CT",
    "workplaceType": "Hybrid",
    "jobUrl": "https://jobs.ashbyhq.com/example/j1",
    "applyUrl": "https://jobs.ashbyhq.com/example/j1/application",
}


def test_ashby_last_publication_is_not_original_and_has_per_field_evidence():
    job = AshbyConnector().normalize(fetched("ashby", ASHBY))
    assert job.original_published_at is None
    assert job.last_published_at == NOW - timedelta(days=1)
    assert job.publication.kind == "LAST_PUBLICATION"
    assert not job.publication.repost_checked
    assert job.country_codes == ["US"]
    assert job.workplace_states == ["CT"]
    assert job.employment_type == "FULL_TIME"
    assert job.field_evidence["publication"][0].field_path == "publishedAt"


def test_ashby_discovery_snapshot_reused_with_observation_time_and_excludes_unlisted():
    client = FakeClient([{"jobs": [ASHBY, dict(ASHBY, id="j2", isListed=False)]}, {"jobs": [ASHBY]}])
    connector = AshbyConnector(client)
    result = connector.discover("analyst", "example")
    assert len(result.candidates) == 1
    fetched_job = connector.fetch(result.candidates[0])
    assert fetched_job.description_complete
    assert fetched_job.fetched_at == result.source_timestamp
    assert len(client.calls) == 1
    assert connector.health().state == "HEALTHY"


def test_ashby_run_cache_expiration_refetches_and_never_uses_caller_injected_payload(monkeypatch):
    from app.connectors import ats

    clock = [0]
    monkeypatch.setattr(ats.time, "monotonic", lambda: clock[0])
    client = FakeClient([{"jobs": [ASHBY]}, {"jobs": []}])
    connector = AshbyConnector(client)
    candidate = connector.discover(tenant="example").candidates[0]
    candidate.payload["descriptionHtml"] = "invented description"
    assert connector.fetch(candidate).payload["descriptionHtml"] == ASHBY["descriptionHtml"]
    clock[0] = 61
    assert connector.fetch(candidate).outcome == "CLOSED"
    assert len(client.calls) == 2


def test_source_error_is_not_successful_empty_search():
    connector = AshbyConnector(FakeClient([HTTPResult(403, b"denied", "https://api.ashbyhq.com", {})]))
    result = connector.discover(tenant="example")
    assert result.errors and result.candidates == []
    assert result.coverage["complete_listing"] is False
    assert connector.health().state == "BLOCKED"


def test_not_listed_is_closed_without_inventing_success():
    c = fetched("ashby", ASHBY).candidate
    connector = AshbyConnector(FakeClient([{"jobs": []}]))
    result = connector.fetch(c)
    assert result.outcome == "CLOSED"
    assert not result.description_complete
    with pytest.raises(ValueError):
        connector.normalize(result)


def test_greenhouse_update_is_never_publication_and_no_fulltime_invention():
    job = GreenhouseConnector().normalize(
        fetched(
            "greenhouse",
            {
                "id": "j1",
                "title": "Analyst",
                "content": "Build SQL dashboards",
                "updated_at": "2026-09-12T11:00:00Z",
                "absolute_url": "https://example.com/jobs/j1",
            },
        )
    )
    assert job.publication.precision == "UNKNOWN"
    assert job.original_published_at is None
    assert job.source_updated_at == NOW - timedelta(hours=1)
    assert job.employment_type is None


def test_greenhouse_detail_first_published_preserved_and_no_cents_annualization():
    data = {
        "id": "j1",
        "title": "Analyst",
        "content": "SQL analytics",
        "first_published": "2026-09-11T12:00:00Z",
        "requisition_id": "REQ-3",
        "pay_input_ranges": [{"min_cents": 8000000, "max_cents": 10000000, "currency_type": "USD"}],
    }
    job = GreenhouseConnector().normalize(fetched("greenhouse", data))
    assert job.original_published_at == NOW - timedelta(days=1)
    assert job.requisition_id == "REQ-3"
    assert job.salary.minimum is None
    assert job.field_evidence["salary"][0].value


def test_greenhouse_fetch_rejects_wrong_id():
    connector = GreenhouseConnector(FakeClient([{"id": "other", "content": "wrong job"}]))
    result = connector.fetch(fetched("greenhouse", {}).candidate)
    assert result.outcome == "FAILED"
    assert result.errors[0].code == "IDENTITY_MISMATCH"


def test_lever_complete_description_preserves_lists_and_preferred_section():
    data = {
        "id": "j1",
        "text": "Analyst",
        "description": "<p>Responsibilities: SQL reporting</p>",
        "lists": [
            {"text": "Required", "content": "<ul><li>2 years experience</li></ul>"},
            {"text": "Preferred", "content": "5 years Python"},
        ],
        "additional": "No sponsorship now or in the future.",
        "categories": {"commitment": "Full-time", "location": "Remote"},
        "createdAt": 1700000000000,
    }
    job = LeverConnector().normalize(fetched("lever", data))
    assert "2 years experience" in job.description_text
    assert "Preferred" in job.description_text and "No sponsorship" in job.description_text
    assert job.country_codes == [] and job.publication.precision == "UNKNOWN"
    assert job.employment_type == "FULL_TIME"


def test_smartrecruiters_full_sections_and_explicit_country():
    data = {
        "id": "j1",
        "name": "BI Analyst",
        "releasedDate": "2026-09-11T12:00:00Z",
        "location": {"city": "New York", "region": "NY", "country": "us"},
        "typeOfEmployment": {"label": "Full-time"},
        "jobAd": {
            "sections": {
                "jobDescription": {"text": "Build reporting"},
                "qualifications": {"text": "5 years required"},
                "additionalInformation": {"text": "Clearance required"},
            }
        },
    }
    job = SmartRecruitersConnector().normalize(fetched("smartrecruiters", data))
    assert "5 years required" in job.description_text and "Clearance required" in job.description_text
    assert job.country_codes == ["US"] and job.publication.kind == "LAST_PUBLICATION"


@pytest.mark.parametrize(
    "body,expected",
    [
        ("<h1>Data Analyst</h1><p>This position is now closed.</p>", "CLOSED"),
        ("<h1>Data Analyst</h1><button>Apply now</button>", "ACTIVE"),
        ("<p>Welcome to our website</p>", "UNKNOWN"),
        ("<h1>Other Job</h1><button>Apply now</button>", "UNKNOWN"),
    ],
)
def test_active_verification_requires_identity_and_action_not_200(body, expected):
    job = AshbyConnector().normalize(fetched("ashby", ASHBY))
    connector = AshbyConnector(FakeClient([HTTPResult(200, body.encode(), job.application_url, {})]))
    assert connector.verify_opening(job).status == expected


def test_generic_careers_redirect_with_matching_job_title_not_active():
    job = AshbyConnector().normalize(fetched("ashby", ASHBY))
    connector = AshbyConnector(
        FakeClient([HTTPResult(200, b"Data Analyst apply now", "https://example.com/careers", {})])
    )
    result = connector.verify_opening(job)
    assert result.status == "UNKNOWN" and result.generic_careers_redirect


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_temporary_application_block_is_unknown(status):
    job = AshbyConnector().normalize(fetched("ashby", ASHBY))
    connector = AshbyConnector(FakeClient([HTTPResult(status, b"error", job.application_url, {})]))
    assert connector.verify_opening(job).status == "UNKNOWN"


def test_html_never_executes_or_retains_scripts_and_escapes_attributes():
    text = readable_html(
        '<h2>Required</h2><script>stealSecrets()</script><iframe src="file:///etc/passwd"></iframe><p onclick="run()">SQL</p>'
    )
    assert text == "Required\nSQL"
    assert "stealSecrets" not in text


def test_safe_html_retains_legitimate_links_but_drops_handlers_scripts_and_private_links():
    value = (
        '<h2>Required</h2><a href="https://example.com/job?id=3" onclick="steal()">Posting</a>'
        '<a href="javascript:steal()">Unsafe</a><a href="http://127.0.0.1">Private</a><script>evil()</script>'
    )
    safe = sanitized_html(value)
    assert "<h2>Required</h2>" in safe and 'href="https://example.com/job?id=3"' in safe
    assert "onclick" not in safe and "javascript" not in safe and "127.0.0.1" not in safe and "evil()" not in safe


def test_inactive_structured_posting_and_expired_deadline_do_not_pass_on_live_apply_button():
    job = AshbyConnector().normalize(fetched("ashby", ASHBY))
    connector = AshbyConnector(FakeClient([]))
    assert connector.verify_opening(job.model_copy(update={"source_active": False})).status == "CLOSED"
    assert (
        connector.verify_opening(job.model_copy(update={"valid_through": datetime(2000, 1, 1, tzinfo=UTC)})).status
        == "CLOSED"
    )


def test_linkedin_job_urls_rejected_even_through_direct_connector():
    connector = DirectConnector(FakeClient([]))
    result = connector.discover(tenant="https://www.linkedin.com/jobs/view/123")
    assert result.errors[0].code == "DISABLED_SOURCE"


def test_rate_limit_health_retains_retry_after_deadline():
    connector = AshbyConnector(FakeClient([HTTPResult(429, b"", "https://api.ashbyhq.com", {"retry-after": "3600"})]))
    result = connector.discover(tenant="example")
    assert connector.health().state == "RATE_LIMITED"
    assert result.errors[0].retry_after is not None and connector.health().retry_after is not None


def test_date_only_unknown_zone_retains_full_uncertainty_interval():
    p = publication("2026-09-11", "datePosted")
    assert p.precision == "DATE" and p.source_timezone is None
    assert (p.latest - p.earliest) > timedelta(hours=49)
    assert publication("2026-09-11T10:00:00", "datePosted").precision == "UNKNOWN"


def test_direct_nested_jsonld_and_us_remote_without_invented_state():
    p = {
        "@type": "JobPosting",
        "title": "Data Analyst",
        "identifier": {"value": "j1"},
        "description": "<p>SQL reports. 2 years required.</p>",
        "employmentType": "FULL_TIME",
        "datePosted": "2026-09-11",
        "jobLocationType": "TELECOMMUTE",
        "applicantLocationRequirements": {"@type": "Country", "name": "United States"},
        "hiringOrganization": {"name": "Example"},
        "url": "https://example.com/jobs/j1",
    }
    page = '<script type="application/ld+json">' + json.dumps({"@graph": [p]}) + "</script>"
    assert jobpostings(page) == [p]
    connector = DirectConnector(FakeClient([HTTPResult(200, page.encode(), "https://example.com/jobs/j1", {})]))
    found = connector.discover(tenant="https://example.com/jobs/j1")
    assert found.candidates[0].external_id == "j1"
    job = connector.normalize(fetched("direct", p))
    assert job.country_codes == ["US"] and job.workplace_states == [] and job.work_arrangement == "REMOTE"


def test_js_only_direct_portal_is_explicitly_incomplete():
    connector = DirectConnector(
        FakeClient([HTTPResult(200, b'<div id="app"></div>', "https://example.com/careers", {})])
    )
    result = connector.discover(tenant="https://example.com/careers")
    assert not result.coverage["complete_listing"] and not result.candidates
    assert connector.health().state == "DEGRADED"


def test_workday_selected_tenant_validation_and_rounded_date_not_publication():
    assert tenant_parts("https://example.wd5.myworkdayjobs.com/en-US/External") == (
        "https://example.wd5.myworkdayjobs.com",
        "example",
        "External",
    )
    with pytest.raises(SourceHTTPError):
        tenant_parts("https://127.0.0.1/External")
    p = {
        "jobPostingInfo": {
            "title": "Analyst",
            "jobDescription": "SQL reporting, 2 years required",
            "timeType": "Full time",
            "startDate": "2026-09-12",
            "postedOn": "Posted Today",
            "country": {"descriptor": "United States"},
            "jobReqId": "R1",
        }
    }
    job = WorkdayConnector().normalize(fetched("workday", p))
    assert job.publication.precision == "UNKNOWN" and job.country_codes == ["US"]


def test_jobspy_never_defaults_to_all_sources_or_combines_incompatible_indeed_filters():
    connector = JobSpyConnector(site="indeed")
    options = connector.query_options("Data Analyst")
    assert options["site_name"] == ["indeed"]
    assert options["hours_old"] == 72 and "is_remote" not in options and "job_type" not in options
    assert options["enforce_annual_salary"] is False
    with pytest.raises(ValueError):
        JobSpyConnector(site="linkedin")
    with pytest.raises(ValueError):
        get_connector("linkedin")


def test_jobspy_exception_and_empty_results_are_not_fully_successful_searches():
    connector = JobSpyConnector(enabled=True, runner=lambda q: {"rows": [], "errors": [{"code": "failure"}]})
    assert connector.discover("Analyst").errors
    connector = JobSpyConnector(enabled=True, runner=lambda q: {"rows": [], "errors": []})
    assert connector.discover("Analyst").coverage["reason"] == "SCRAPER_EMPTY_UNVERIFIED"
    assert connector.health().state == "DEGRADED"


def test_jobspy_nan_not_fulltime_or_date_and_no_invented_annual_salary():
    data = {
        "title": "Analyst",
        "description": "A truncated search description",
        "job_type": float("nan"),
        "date_posted": None,
        "min_amount": float("nan"),
        "is_remote": float("nan"),
        "location": "Remote",
    }
    connector = JobSpyConnector(enabled=True, runner=lambda q: {"rows": [], "errors": []})
    result = connector.fetch(fetched("jobspy", data).candidate.model_copy(update={"payload": data}))
    job = connector.normalize(result)
    assert not job.description_complete and job.work_arrangement == "UNKNOWN"
    assert job.employment_type is None and job.salary.minimum is None


def test_usajobs_missing_key_does_not_touch_network():
    connector = USAJobsConnector(FakeClient([]))
    result = connector.discover("Analyst")
    assert connector.health().state == "NOT_CONFIGURED" and result.errors


def test_recorded_lever_and_workday_access_is_real_and_has_correct_unknown_freshness():
    rows = json.loads(Path("tests/fixtures/connectors/additional_source_access.json").read_text())
    lever = next(r for r in rows if r["source_type"] == "lever")
    workday = next(r for r in rows if r["source_type"] == "workday")
    assert lever["status"] == 200 and lever["synthetic"] is False
    job = LeverConnector().normalize(fetched("lever", lever["payload"][0]))
    assert job.description_complete and job.publication.precision == "UNKNOWN"
    assert workday["status"] == 200 and workday["synthetic"] is False
    client = FakeClient([workday["payload"]])
    discovered = WorkdayConnector(client).discover("analyst", "https://analogdevices.wd1.myworkdayjobs.com/External")
    assert discovered.candidates and discovered.next_cursor == "2"
    assert discovered.coverage["experimental_cxs"]


def test_usajobs_summary_is_not_complete_jd():
    connector = USAJobsConnector()
    result = connector.fetch(fetched("usajobs", {"PositionTitle": "Analyst", "QualificationSummary": "SQL"}).candidate)
    assert not result.description_complete


def test_directory_links_are_review_leads_not_verified_pool_or_employer():
    client = FakeClient(
        [
            HTTPResult(
                200,
                b'<a href="https://startup.example/careers">Startup</a>',
                "https://www.ycombinator.com/companies",
                {},
            )
        ]
    )
    result = DirectoryDiscovery(client).discover_employer_links("https://www.ycombinator.com/companies")
    assert result["leads"][0]["verification_state"] == "LEAD_ONLY"
    assert result["leads"][0]["pool_membership_verified"] is False


@pytest.mark.parametrize(
    "filename",
    sorted(
        p.name for p in Path("tests/fixtures/connectors").glob("*_real.json") if p.name != "source_probes_real.json"
    ),
)
def test_actual_recorded_ats_payload_replays_without_fabricated_everify(filename):
    bundle = json.loads((Path("tests/fixtures/connectors") / filename).read_text())
    provenance, p = bundle["provenance"], bundle["job"]
    assert provenance["synthetic"] is False
    assert provenance["http_status"] == 200
    source = provenance["source_type"]
    result = fetched(source, p, external_id=str(p["id"])).model_copy(
        update={"fetched_at": datetime.fromisoformat(provenance["observed_at"])}
    )
    job = get_connector(source).normalize(result)
    assert job.title and len(job.description_text) > 100
    assert job.description_complete
    assert not job.synthetic
    assert "everify" not in type(job).model_fields
    if source == "ashby":
        assert job.publication.kind == "LAST_PUBLICATION" and not job.publication.repost_checked


def test_catalog_identity_matches_registry_for_optional_jobspy_and_university():
    connector = get_connector(
        "jobspy:indeed",
        enabled=True,
        runner=lambda _: {
            "rows": [
                {
                    "id": "demo",
                    "title": "Analyst",
                    "company": "Synthetic Employer",
                    "description": "SQL analytics",
                    "job_url": "https://example.com/jobs/demo",
                }
            ]
        },
    )
    candidate = connector.discover(tenant="registered-search").candidates[0]
    job = connector.normalize(connector.fetch(candidate))
    assert candidate.tenant == job.tenant == "registered-search"
    assert candidate.source_type == job.source_type == connector.health().source_type == "jobspy:indeed"
    university = get_connector("university")
    assert university.source_type == university.health().source_type == "university"


def test_catalog_usajobs_reads_validated_settings_and_allows_explicit_override(monkeypatch):
    from types import SimpleNamespace

    from app import config

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(usajobs_api_key="from-dotenv", usajobs_user_agent="owner@example.com"),
    )
    connector = get_connector("usajobs")
    assert connector.api_key == "from-dotenv" and connector.user_agent == "owner@example.com"
    assert get_connector("usajobs", api_key="explicit").api_key == "explicit"


@pytest.mark.parametrize("version,code", [("1.1.82", "BLOCKED_SECURITY"), ("99.0.0", "JOBSPY_VERSION_UNQUALIFIED")])
def test_installed_jobspy_security_gate_never_starts_subprocess_or_source(monkeypatch, version, code):
    from app.connectors import jobspy_adapter

    monkeypatch.setattr(jobspy_adapter.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(jobspy_adapter.importlib.metadata, "version", lambda _: version)

    def unexpected(*args, **kwargs):
        pytest.fail("Blocked JobSpy must never invoke a subprocess or source")

    monkeypatch.setattr(jobspy_adapter.subprocess, "run", unexpected)
    client = FakeClient([])
    connector = JobSpyConnector(client, enabled=True)
    result = connector.discover("data analyst")
    assert connector.health().state == "BLOCKED" and result.errors[0].code == code
    assert not result.candidates and not result.coverage["complete_listing"]
    assert client.calls == []


def test_absent_optional_jobspy_is_still_not_configured(monkeypatch):
    from app.connectors import jobspy_adapter

    monkeypatch.setattr(jobspy_adapter.importlib.util, "find_spec", lambda _: None)
    client = FakeClient([])
    connector = JobSpyConnector(client, enabled=True)
    assert connector.health().state == "NOT_CONFIGURED"
    assert connector.discover().errors[0].code == "JOBSPY_NOT_CONFIGURED"
    assert client.calls == []


def test_greenhouse_verify_opening_uses_job_board_api_not_javascript_page():
    # Employer pages that embed Greenhouse render client-side; the board API is authoritative.
    payload = {
        "id": "j1",
        "title": "Analyst",
        "absolute_url": "https://boards.greenhouse.io/example/jobs/j1",
        "questions": [{"label": "Resume", "required": True}],
    }
    connector = GreenhouseConnector(FakeClient([payload]))
    job = connector.normalize(fetched("greenhouse", {"id": "j1", "title": "Analyst", "content": "SQL"}))
    check = connector.verify_opening(job)
    assert check.status == "ACTIVE" and check.identity_match and check.actionable
    assert "boards-api.greenhouse.io/v1/boards/example/jobs/j1?questions=true" in connector.client.calls[0][0]
    assert check.application_url == payload["absolute_url"]


def test_greenhouse_verify_opening_reports_closed_on_404_and_unknown_without_form():
    connector = GreenhouseConnector(FakeClient([HTTPResult(404, b"{}", "https://boards-api.greenhouse.io/x", {})]))
    job = connector.normalize(fetched("greenhouse", {"id": "j1", "title": "Analyst", "content": "SQL"}))
    assert connector.verify_opening(job).status == "CLOSED"
    no_form = GreenhouseConnector(FakeClient([{"id": "j1", "absolute_url": "https://x.example/j1", "questions": []}]))
    check = no_form.verify_opening(job)
    assert check.status == "UNKNOWN" and check.identity_match and not check.actionable
    mismatch = GreenhouseConnector(
        FakeClient([{"id": "other", "absolute_url": "https://x.example/o", "questions": [1]}])
    )
    assert mismatch.verify_opening(job).status == "UNKNOWN"
