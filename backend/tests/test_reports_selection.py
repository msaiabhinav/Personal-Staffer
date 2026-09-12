from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.reports.selection import Candidate, cycle_for, recovery_dates, release_at, select_regular

NOW = datetime(2026, 9, 12, 15, tzinfo=UTC)


def c(i, **kwargs):
    return replace(
        Candidate(str(i), f"company-{i}", NOW - timedelta(hours=1), "B", True, NOW + timedelta(hours=1)), **kwargs
    )


def test_at21_salary_selection_then_newest_display():
    rows = [
        c(1, salary_band="C", published_at=NOW),
        c(2, salary_band="A", published_at=NOW - timedelta(hours=20)),
        c(3),
    ]
    assert [x.job_id for x in select_regular(rows, now=NOW, used_groups=set(), limit=2)] == ["3", "2"]
    assert [x.job_id for x in select_regular(rows, now=NOW, used_groups=set())] == ["1", "3", "2"]


def test_at25_limits_and_stable_identity():
    rows = [c(i, employer_group_id=f"group-{i // 4}") for i in range(160)]
    result = select_regular(rows + rows, now=NOW, used_groups=set())
    assert len(result) == 50
    assert len({x.job_id for x in result}) == 50
    assert all(sum(y.employer_group_id == x.employer_group_id for y in result) <= 2 for x in result)


def test_at26_shared_boundary_not_individual_cooldown():
    anchor = date(2026, 9, 1)
    assert cycle_for(anchor, date(2026, 10, 2)) == (0, anchor, date(2026, 10, 3))
    assert cycle_for(anchor, date(2026, 10, 3)) == (1, date(2026, 10, 3), date(2026, 11, 4))


@pytest.mark.parametrize(
    "change",
    [
        {"delivered": True},
        {"applied": True},
        {"dismissed": True},
        {"priority": True},
        {"eligible": False},
        {"valid_until": NOW - timedelta(seconds=1)},
    ],
)
def test_at27_28_suppression(change):
    assert select_regular([c(1, **change)], now=NOW, used_groups=set()) == []


def test_at30_dst_preserves_local_eleven():
    assert release_at(date(2026, 3, 7)).hour == 16
    assert release_at(date(2026, 3, 8)).hour == 15
    assert release_at(date(2026, 11, 1)).hour == 16
    due, missed = recovery_dates(now=NOW, last_report_date=date(2026, 9, 9))
    assert due == date(2026, 9, 12)
    assert missed == [date(2026, 9, 10), date(2026, 9, 11)]
    assert recovery_dates(now=NOW - timedelta(hours=1), last_report_date=None)[0] is None


def test_rotation_usage_changes_only_selection_input():
    assert select_regular([c(1)], now=NOW, used_groups={"company-1"}) == []
    assert len(select_regular([c(1)], now=NOW, used_groups=set())) == 1
