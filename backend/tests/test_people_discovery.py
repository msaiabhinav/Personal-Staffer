from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.people.discovery import (
    GROUPS,
    BraveSearch,
    JobContext,
    ProviderUnavailable,
    SearchResult,
    normalized_linkedin,
    queries,
    select_people,
    supported_candidate,
)

NOW = datetime(2026, 9, 12, tzinfo=UTC)
CONTEXT = JobContext("job1", "Example Corp", "Data Analyst", "Analytics")


def result(name="Jane Doe", role="Recruiter at Example Corp", days=0):
    return SearchResult(
        f"https://www.linkedin.com/in/{name.lower().replace(' ', '-')}?trk=x",
        f"{name} - {role} | LinkedIn",
        role,
        NOW - timedelta(days=days),
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://linkedin.com.evil/in/test",
        "https://www.linkedin.com/jobs/view/123",
        "http://www.linkedin.com/in/a",
        "https://a:b@www.linkedin.com/in/a",
        "https://www.linkedin.com/in/a/extra",
    ],
)
def test_profile_urls_are_real_profile_paths_only(url):
    assert normalized_linkedin(url) is None


def test_at_47_bounded_alphabetic_deduped_supported_people():
    candidates = [supported_candidate(result(f"Person {chr(65 + index)}"), CONTEXT, NOW) for index in range(15)]
    candidates += candidates
    people = select_people(candidates)
    assert len(people) == 10
    assert len({p.profile_url for p in people}) == 10
    assert [p.name for p in people] == sorted(p.name for p in people)
    assert all(p.group == GROUPS[0] and p.evidence_label == "LIKELY" for p in people)


def test_at_48_stale_and_former_people_are_withheld():
    assert supported_candidate(result(days=31), CONTEXT, NOW) is None
    assert supported_candidate(result(role="Former Recruiter at Example Corp"), CONTEXT, NOW) is None
    assert supported_candidate(result(role="Analyst at Example Corp"), CONTEXT, NOW) is None
    assert supported_candidate(result(role="Chief Executive at Example Corp"), CONTEXT, NOW) is None


def test_hiring_manager_requires_named_opening_evidence():
    row = result(role="Analytics Manager at Example Corp")
    candidate = supported_candidate(row, CONTEXT, NOW)
    assert candidate.group == GROUPS[3]
    assert candidate.evidence_label == "LIKELY"
    job = JobContext(
        "job",
        "Example Corp",
        "Data Analyst",
        "Analytics",
        named_hiring_manager="Jane Doe",
        evidence_reference="snapshot1:line42",
    )
    candidate = supported_candidate(row, job, NOW)
    assert candidate.group == GROUPS[1] and candidate.evidence_label == "CONFIRMED"
    assert candidate.verification == "SEARCH_RESULT_ONLY"


def test_query_count_maximum_eight():
    assert 1 <= len(queries(CONTEXT)) <= 8


def test_provider_not_configured_and_http_contract():
    with pytest.raises(ProviderUnavailable) as error:
        BraveSearch("").search("query")
    assert error.value.state == "NOT_CONFIGURED"

    def handler(request):
        assert request.url.host == "api.search.brave.com"
        assert request.headers["X-Subscription-Token"] == "test-key"
        assert request.url.params["country"] == "us"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://www.linkedin.com/in/jane",
                            "title": "Jane Doe - Recruiter at Example Corp",
                            "description": "<b>Recruiter</b> at Example Corp",
                        }
                    ]
                }
            },
        )

    rows = BraveSearch("test-key", httpx.MockTransport(handler)).search("query")
    assert rows[0].description == "Recruiter at Example Corp"


def test_provider_blocked_is_visible():
    with pytest.raises(ProviderUnavailable) as error:
        BraveSearch("key", httpx.MockTransport(lambda r: httpx.Response(403))).search("query")
    assert error.value.state == "UNAVAILABLE"
