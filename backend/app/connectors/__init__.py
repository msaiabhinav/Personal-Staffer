"""Public source acquisition. Discovery is never proof of eligibility."""

from .amazon_jobs import AmazonJobsConnector
from .ats import AshbyConnector, GreenhouseConnector, LeverConnector, SmartRecruitersConnector
from .catalog import CATALOG, get_connector
from .contracts import Candidate, DiscoverResult, FetchResult, NormalizedJob, OpeningVerification
from .safe_http import SafeHTTPClient

__all__ = [
    "CATALOG",
    "AmazonJobsConnector",
    "AshbyConnector",
    "Candidate",
    "DiscoverResult",
    "FetchResult",
    "GreenhouseConnector",
    "LeverConnector",
    "NormalizedJob",
    "OpeningVerification",
    "SafeHTTPClient",
    "SmartRecruitersConnector",
    "get_connector",
]
