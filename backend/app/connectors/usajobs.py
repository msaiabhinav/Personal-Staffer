"""Optional official USAJOBS API boundary; never converts public to citizen eligibility."""

from __future__ import annotations

from urllib.parse import urlencode

from .base import BaseConnector, source_error
from .contracts import Candidate, DiscoverResult, Health, SourceError
from .parsing import country, employment, exact_time, publication, salary
from .safe_http import SourceHTTPError


class USAJobsConnector(BaseConnector):
    source_type = "usajobs"

    def __init__(self, client=None, *, api_key: str | None = None, user_agent: str | None = None):
        super().__init__(client)
        self.api_key, self.user_agent = api_key, user_agent
        if not api_key or not user_agent:
            self._health = Health(
                source_type=self.source_type,
                state="NOT_CONFIGURED",
                last_error=SourceError(
                    code="MISSING_CONFIGURATION", message="USAJOBS API key and registered user agent are required"
                ),
            )

    def discover(self, query="", tenant="USA", cursor=None):
        if not self.api_key or not self.user_agent:
            return DiscoverResult(
                errors=[self.health().last_error], coverage={"complete_listing": False, "state": "NOT_CONFIGURED"}
            )
        try:
            page = int(cursor or "1")
            if not 1 <= page <= 100:
                raise ValueError("invalid page")
            url = "https://data.usajobs.gov/api/search?" + urlencode(
                {
                    "Keyword": query,
                    "LocationName": "United States",
                    "DatePosted": 3,
                    "Fields": "Full",
                    "Page": page,
                    "ResultsPerPage": 100,
                }
            )
            _, data = self._json(url, headers={"User-Agent": self.user_agent, "Authorization-Key": self.api_key})
            result = data["SearchResult"]
            items = result["SearchResultItems"]
            candidates = []
            for row in items:
                p = row["MatchedObjectDescriptor"]
                candidates.append(
                    Candidate(
                        source_type=self.source_type,
                        tenant="USA",
                        external_id=str(row["MatchedObjectId"]),
                        source_url=p["PositionURI"],
                        title=p.get("PositionTitle"),
                        employer_name=p.get("OrganizationName"),
                        payload=p,
                    )
                )
            more = page * 100 < int(result.get("SearchResultCountAll", len(items)))
            self._success()
            return DiscoverResult(
                candidates=candidates,
                next_cursor=str(page + 1) if more else None,
                coverage={"complete_listing": not more, "raw_count": len(items), "full_fields_requested": True},
            )
        except (SourceHTTPError, ValueError, TypeError, KeyError) as exc:
            error = source_error(exc)
            self._failure(error)
            return DiscoverResult(errors=[error], coverage={"complete_listing": False})

    def fetch(self, candidate):
        # The API's detail fields are carried in the search payload. Preserve discovery timestamp.
        p = candidate.payload
        details = p.get("UserArea", {}).get("Details", {})
        required = {"MajorDuties", "Requirements", "Education", "Evaluations", "OtherInformation"}
        complete = required <= details.keys() and bool(p.get("QualificationSummary"))
        result = self._fetched(candidate, p, complete=complete)
        result.fetched_at = candidate.discovered_at
        return result

    def normalize(self, payload):
        p = payload.payload
        details = p.get("UserArea", {}).get("Details", {})
        sections = []
        for key, value in details.items():
            if isinstance(value, str):
                sections.append(key + "\n" + value)
            elif isinstance(value, list):
                sections.append(key + "\n" + "\n".join(str(v) for v in value if isinstance(v, str)))
        sections.append("Qualifications\n" + p.get("QualificationSummary", ""))
        locs = p.get("PositionLocation") or []
        codes = sorted({c for loc in locs if (c := country(loc.get("CountryCode")))})
        schedules = p.get("PositionSchedule") or []
        schedule = schedules[0].get("Name") if len(schedules) == 1 else None
        compensation = (p.get("PositionRemuneration") or [{}])[0]
        apply = p.get("ApplyURI") or []
        apply = apply[0] if isinstance(apply, list) and apply else apply if isinstance(apply, str) else None
        job = self._base_job(
            payload,
            title=p.get("PositionTitle"),
            description="\n\n".join(sections),
            employer=p.get("OrganizationName"),
            application_url=apply,
            employer_url=p.get("PositionURI"),
            requisition_id=p.get("PositionID"),
            locations=[l.get("LocationName", "") for l in locs],
            country_codes=codes,
            employment_type=employment(schedule),
            publication=publication(p.get("PublicationStartDate"), "PublicationStartDate"),
            original_published_at=exact_time(p.get("PublicationStartDate")),
            salary=salary(
                compensation.get("MinimumRange"),
                compensation.get("MaximumRange"),
                compensation.get("CurrencyCode"),
                compensation.get("Description"),
                "PositionRemuneration",
            ),
            warnings=[] if payload.description_complete else ["USAJOBS_LIGHTWEIGHT_CONTENT_INCOMPLETE"],
        )
        return self._evidence(
            job,
            title=("PositionTitle", p.get("PositionTitle")),
            description=("UserArea.Details", details),
            employment_type=("PositionSchedule", schedules),
            country_codes=("PositionLocation", locs),
            publication=("PublicationStartDate", p.get("PublicationStartDate")),
            application_url=("ApplyURI", apply),
        )
