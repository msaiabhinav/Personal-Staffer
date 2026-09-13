"""Source inventory records implementation honestly; labels do not implement a scraper."""

import os

from .amazon_jobs import AmazonJobsConnector
from .ats import AshbyConnector, GreenhouseConnector, LeverConnector, SmartRecruitersConnector
from .direct import DirectConnector
from .jobspy_adapter import JobSpyConnector
from .usajobs import USAJobsConnector
from .workday import WorkdayConnector

CATALOG = [
    {
        "source_type": "amazon_jobs",
        "implementation": "PUBLIC_SEARCH_JSON_CONNECTOR",
        "configuration": "COUNTRY_REQUIRED",
    },
    {"source_type": "ashby", "implementation": "PUBLIC_ATS_CONNECTOR", "configuration": "EMPLOYER_BOARD_REQUIRED"},
    {"source_type": "greenhouse", "implementation": "PUBLIC_ATS_CONNECTOR", "configuration": "EMPLOYER_BOARD_REQUIRED"},
    {"source_type": "lever", "implementation": "PUBLIC_ATS_CONNECTOR", "configuration": "EMPLOYER_BOARD_REQUIRED"},
    {
        "source_type": "smartrecruiters",
        "implementation": "PUBLIC_ATS_CONNECTOR",
        "configuration": "EMPLOYER_BOARD_REQUIRED",
    },
    {
        "source_type": "workday",
        "implementation": "EXPERIMENTAL_CXS_CONNECTOR",
        "configuration": "REVIEWED_TENANT_REQUIRED",
    },
    {
        "source_type": "direct",
        "implementation": "STATIC_JOBPOSTING_JSONLD_CONNECTOR",
        "configuration": "CAREER_URL_REQUIRED",
    },
    {
        "source_type": "university",
        "implementation": "DIRECT_JSONLD_ONLY_PORTAL_SPECIFIC_GAPS",
        "configuration": "CAREER_URL_REQUIRED",
    },
    *[
        {
            "source_type": "jobspy:" + site,
            "implementation": "OPTIONAL_DISCOVERY_ADAPTER",
            "configuration": "NOT_CONFIGURED",
        }
        for site in ["indeed", "google", "glassdoor", "zip_recruiter"]
    ],
    {"source_type": "usajobs", "implementation": "OFFICIAL_API_CONNECTOR", "configuration": "NOT_CONFIGURED"},
    *[
        {
            "source_type": name,
            "implementation": "STATIC_DIRECTORY_LINK_LEADS_ONLY",
            "configuration": "MANUAL_REVIEW_REQUIRED",
        }
        for name in ["wellfound", "welcome_to_the_jungle", "yc", "a16z", "sequoia", "usv"]
    ],
    {"source_type": "linkedin", "implementation": "DISABLED_BY_PRODUCT_POLICY", "configuration": "DISABLED"},
]


def get_connector(source_type: str, **kwargs):
    factories = {
        "amazon_jobs": AmazonJobsConnector,
        "ashby": AshbyConnector,
        "greenhouse": GreenhouseConnector,
        "lever": LeverConnector,
        "smartrecruiters": SmartRecruitersConnector,
        "workday": WorkdayConnector,
        "direct": DirectConnector,
        "university": DirectConnector,
    }
    if source_type in factories:
        connector = factories[source_type](**kwargs)
        connector.source_type = source_type
        connector._health.source_type = source_type
        return connector
    if source_type == "usajobs":
        from app.config import get_settings

        settings = get_settings()
        kwargs.setdefault("api_key", settings.usajobs_api_key)
        kwargs.setdefault("user_agent", settings.usajobs_user_agent)
        return USAJobsConnector(**kwargs)
    if source_type.startswith("jobspy:"):
        kwargs.setdefault("enabled", os.getenv("JOBSPY_ENABLED", "false").lower() == "true")
        return JobSpyConnector(site=source_type.split(":", 1)[1], **kwargs)
    raise ValueError(f"Source {source_type!r} is not an executable job connector; consult the source catalog")
