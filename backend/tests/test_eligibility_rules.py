from datetime import timedelta

import pytest
from pydantic import ValidationError
from test_eligibility_corpus import CORPUS, NOW

from app.eligibility import JobEvidence, PublicationEvidence, Salary, evaluate_job, salary_band
from app.eligibility.dedupe import JobIdentity, canonical_destination, compare_identity, identity_tombstones
from app.relevance import analyze_relevance, canonicalize_skills


def job_with(**changes):
    data = JobEvidence.model_validate(CORPUS["cases"][0]["bundle"]).model_dump()
    data.update(changes)
    return JobEvidence.model_validate(data)


def rule_for(text, rule="experience"):
    job = job_with(
        description="Responsibilities\nBuild SQL dashboards and analyze revenue data.\nRequired qualifications\n" + text
    )
    ev = evaluate_job(job, now=NOW, allow_synthetic=True)
    return next(r for r in ev.rules if r.rule == rule)


@pytest.mark.parametrize(
    "clause,expected",
    [
        ("Four years required.", "PASS"),
        ("At least four (4) years required.", "FAIL"),
        ("A minimum of 4 years required.", "FAIL"),
        ("4 years minimum.", "FAIL"),
        ("4 years or more required.", "FAIL"),
        ("Minimum experience: 4 years.", "FAIL"),
        ("4 years of experience minimum.", "FAIL"),
        ("48 months required.", "PASS"),
        ("49 months required.", "FAIL"),
        ("4.5 years required.", "FAIL"),
        ("2 years required and 5 years preferred.", "PASS"),
        ("5 years required and 2 years preferred.", "FAIL"),
        ("2 years required.\nPreferred qualifications\n5 years analytics experience.", "PASS"),
        ("2 years required.\n5 years desirable.", "PASS"),
        ("Less than 5 years required.", "REVIEW"),
        ("The company was founded 20 years ago.", "REVIEW"),
        ("2 years required.\nThe company was founded 20 years ago.", "PASS"),
        ("2 years required.\nPrior experience with customer contracts.", "PASS"),
    ],
)
def test_comparator_and_requiredness_semantics(clause, expected):
    assert rule_for(clause).decision == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Applicants must be authorized to work in the U.S.", "PASS"),
        ("No sponsorship required.", "PASS"),
        ("No sponsorship is required for applicants who already have unrestricted authorization.", "REVIEW"),
        ("We do not prohibit visa sponsorship.", "PASS"),
        ("Visa sponsorship is available. We will not provide sponsorship in the future.", "FAIL"),
        ("Candidates must work without visa sponsorship.", "FAIL"),
        ("CPT candidates are not considered.", "FAIL"),
        ("Contact us regarding sponsorship eligibility.", "REVIEW"),
    ],
)
def test_sponsorship_context(text, expected):
    assert rule_for("2 years required.\n" + text, "sponsorship").decision == expected


@pytest.mark.parametrize(
    "minimum,maximum,currency,interval,expected",
    [
        (80000, 95000, "USD", "YEAR", "A"),
        (90000, None, "USD", "ANNUAL", "A"),
        (70000, 90000, "USD", "YEAR", "B"),
        (None, None, None, None, "B"),
        (79000, 79999, "USD", "YEAR", "C"),
        (None, 70000, "USD", "YEAR", "C"),
        (50, 60, "USD", "HOUR", "B"),
        (100000, 120000, "CAD", "YEAR", "B"),
        (80000, 80000, "USD", "YEAR", "A"),
        (None, 95000, "USD", "YEAR", "B"),
    ],
)
def test_salary_bands_do_not_invent_annual_compensation(minimum, maximum, currency, interval, expected):
    salary = Salary(minimum=minimum, maximum=maximum, currency=currency, interval=interval)
    assert salary_band(salary) == expected


def test_priority_overlap_and_generic_us_remote():
    baseline = job_with(watchlisted=True, university=True)
    first = evaluate_job(baseline, now=NOW, allow_synthetic=True)
    assert first.priority_reasons == ["WATCHLIST", "UNIVERSITY"]
    assert "CONNECTICUT" not in first.priority_reasons
    explicit_ct = evaluate_job(
        baseline.model_copy(update={"explicit_remote_states": ["CT"]}), now=NOW, allow_synthetic=True
    )
    assert explicit_ct.priority_reasons == ["WATCHLIST", "UNIVERSITY", "CONNECTICUT"]
    unrelated_ct = evaluate_job(
        baseline.model_copy(update={"title": "Professor of AI", "explicit_remote_states": ["CT"]}),
        now=NOW,
        allow_synthetic=True,
    )
    assert unrelated_ct.priority_reasons == []


@pytest.mark.parametrize(
    "arrangement,workplace,remote,expected",
    [
        ("REMOTE", ["CT"], [], False),
        ("ONSITE", ["CT"], [], True),
        ("HYBRID", ["CT"], [], True),
        ("UNKNOWN", ["CT"], [], False),
        ("REMOTE", [], ["CT"], True),
    ],
)
def test_connecticut_evidence_matches_arrangement(arrangement, workplace, remote, expected):
    ev = evaluate_job(
        job_with(work_arrangement=arrangement, workplace_states=workplace, explicit_remote_states=remote),
        now=NOW,
        allow_synthetic=True,
    )
    assert ("CONNECTICUT" in ev.priority_reasons) == expected


def test_startup_pool_does_not_change_job_country_or_priority():
    job = job_with(startup_pool="NYC", country_codes=["CA"])
    ev = evaluate_job(job, now=NOW, allow_synthetic=True)
    assert ev.decision == "INELIGIBLE" and ev.priority_reasons == []
    domestic = evaluate_job(job_with(startup_pool="BAY_AREA"), now=NOW, allow_synthetic=True)
    assert domestic.decision == "ELIGIBLE" and domestic.priority_reasons == []


def test_relevance_skills_aliases_and_related_are_distinct():
    result = analyze_relevance(
        "Business Analyst",
        "Build PostgreSQL dashboards and document business requirements.\nRequired qualifications\nPowwerBI required.\nTableau preferred.",
        vocabulary=["PowwerBI", "SQL", "Tableau", "Python"],
    )
    assert result.relevant
    assert result.direct_skills == ["Power BI", "Tableau"]
    assert result.related_skills == {"SQL": ["postgresql"]}
    assert result.required_skills == ["Power BI"]
    assert result.preferred_skills == ["Tableau"]
    assert result.missing_requested_skills == ["SQL", "Python"]
    assert result.original_vocabulary[0] == "PowwerBI"
    assert canonicalize_skills(["PowerBI", "PowwerBI", "power bi"]) == ["Power BI"]


def test_relevance_title_alone_does_not_approve():
    result = analyze_relevance("AI Engineer", "Our company supports customers. Python required.")
    assert result.relevant is None and not result.summary


def test_exact_publication_needs_same_aware_endpoints():
    with pytest.raises(ValidationError):
        PublicationEvidence(earliest=NOW, latest=NOW + timedelta(hours=1), precision="EXACT", kind="ORIGINAL")
    with pytest.raises(ValidationError):
        PublicationEvidence(earliest=NOW.replace(tzinfo=None), latest=NOW, precision="DATE", kind="ORIGINAL")
    with pytest.raises(ValueError):
        evaluate_job(job_with(), now=NOW.replace(tzinfo=None))


def test_republication_requires_check_and_update_never_refreshes_age():
    pub = job_with().publication.model_copy(update={"kind": "LAST_PUBLICATION", "repost_checked": False})
    ev = evaluate_job(job_with(publication=pub, updated_at=NOW), now=NOW, allow_synthetic=True)
    assert "REPOST_CHECK_REQUIRED" in ev.reason_codes
    checked = pub.model_copy(update={"repost_checked": True})
    assert evaluate_job(job_with(publication=checked), now=NOW, allow_synthetic=True).decision == "ELIGIBLE"


def test_explicit_recheck_deadline_can_be_shorter_than_policy():
    ev = job_with().everify.model_copy(update={"recheck_due_at": NOW - timedelta(seconds=1)})
    assert "EVERIFY_STALE" in evaluate_job(job_with(everify=ev), now=NOW, allow_synthetic=True).reason_codes


def identity(identifier="one", **changes):
    data = {
        "canonical_id": identifier,
        "employer_group_id": "synthetic-employer",
        "title": "Revenue Analyst",
        "location": "US Remote",
        "description": "Build revenue dashboards.",
    }
    data.update(changes)
    return JobIdentity(**data)


def test_verified_requisition_merges_cross_sources():
    a = identity(requisition_id="REQ1", requisition_verified=True, source="ATS")
    b = identity("two", requisition_id="REQ1", requisition_verified=True, source="AGGREGATOR")
    assert compare_identity(a, b).decision == "SAME"


def test_different_requisitions_with_identical_jd_are_distinct():
    a = identity(requisition_id="REQ1", requisition_verified=True)
    b = identity("two", requisition_id="REQ2", requisition_verified=True)
    assert compare_identity(a, b).decision == "DISTINCT"


def test_similarity_only_creates_review_not_a_merge():
    assert compare_identity(identity(), identity("two")).decision == "REVIEW"


def test_identity_query_parameters_retained_and_trackers_removed():
    assert (
        canonical_destination("https://EXAMPLE.invalid/apply?jobId=1&utm_source=test&location=CT")
        == "https://example.invalid/apply?jobId=1&location=CT"
    )
    a = identity(
        employer_destination="https://example.invalid/apply?jobId=1", destination_identity_verified=True, description=""
    )
    b = identity(
        "two",
        employer_destination="https://example.invalid/apply?jobId=2",
        destination_identity_verified=True,
        description="",
    )
    assert compare_identity(a, b).decision == "DISTINCT"


def test_source_identity_and_tombstones_preserve_cross_cycle_suppression_keys():
    a = identity(
        source="ashby", tenant="synthetic-board", external_id="123", requisition_id="REQ1", requisition_verified=True
    )
    b = identity("two", source="ashby", tenant="synthetic-board", external_id="123")
    assert compare_identity(a, b).decision == "SAME"
    assert identity_tombstones(a) == ["source:ashby|synthetic-board|123", "req:synthetic-employer|REQ1"]
    conflicting = b.model_copy(update={"requisition_id": "REQ2", "requisition_verified": True})
    assert compare_identity(a, conflicting).decision == "REVIEW"


@pytest.mark.parametrize(
    "text",
    [
        "Employment Type: Contract",
        "Job type: Contractor",
        "This is a contractor position.",
        "Contract",
        "This is a 6-month contract.",
    ],
)
def test_contract_heading_overrides_full_time_metadata(text):
    assert rule_for("2 years required.\n" + text, "employment").decision == "FAIL"


@pytest.mark.parametrize(
    "text",
    [
        "Security clearance: Not required.",
        "Security clearance: None.",
        "No need to obtain a security clearance.",
        "This job does not require a security clearance.",
    ],
)
def test_negated_clearance_word_order(text):
    assert rule_for("2 years required.\n" + text, "clearance").decision == "PASS"
