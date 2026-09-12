from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Candidate:
    job_id: str
    employer_group_id: str
    published_at: datetime
    salary_band: str
    eligible: bool
    valid_until: datetime | None
    priority: bool = False
    delivered: bool = False
    applied: bool = False
    dismissed: bool = False


def release_at(report_date: date) -> datetime:
    return datetime.combine(report_date, time(11), tzinfo=EASTERN).astimezone(UTC)


def cycle_for(anchor: date, target: date) -> tuple[int, date, date]:
    if target < anchor:
        raise ValueError("Report date precedes the permanent cycle anchor")
    index = (target - anchor).days // 32
    start = anchor + timedelta(days=32 * index)
    return index, start, start + timedelta(days=32)


def select_regular(
    candidates: list[Candidate], *, now: datetime, used_groups: set[str], limit: int = 50
) -> list[Candidate]:
    """Choose by compensation, then display newest-first. Never weaken gates."""
    if now.tzinfo is None or not 0 <= limit <= 50:
        raise ValueError("Aware time and a report limit in 0..50 are required")
    available = [
        c
        for c in candidates
        if c.eligible
        and c.valid_until is not None
        and c.valid_until >= now
        and not (c.priority or c.delivered or c.applied or c.dismissed)
        and c.employer_group_id not in used_groups
        and now - timedelta(hours=72) <= c.published_at <= now + timedelta(minutes=5)
    ]
    available.sort(key=lambda c: (c.salary_band, -c.published_at.timestamp(), c.job_id))
    selected, counts, ids = [], {}, set()
    for candidate in available:
        if len(selected) >= limit:
            break
        if candidate.job_id in ids or counts.get(candidate.employer_group_id, 0) >= 2:
            continue
        selected.append(candidate)
        ids.add(candidate.job_id)
        counts[candidate.employer_group_id] = counts.get(candidate.employer_group_id, 0) + 1
    return sorted(selected, key=lambda c: (-c.published_at.timestamp(), c.job_id))


def recovery_dates(*, now: datetime, last_report_date: date | None) -> tuple[date | None, list[date]]:
    """Only today's overdue report may be created, never historical backfill."""
    today = now.astimezone(EASTERN).date()
    due = today if now >= release_at(today) and last_report_date != today else None
    missed = []
    if last_report_date:
        d = last_report_date + timedelta(days=1)
        while d < today:
            missed.append(d)
            d += timedelta(days=1)
    return due, missed
