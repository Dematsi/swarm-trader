from datetime import date, datetime, time

import pytest

from src.options_research.market_calendar import (
    ET,
    entry_exit_cutoffs,
    get_session,
    next_session_on_or_after,
    previous_session_on_or_before,
    sessions_between,
)


def test_regular_session_open_close_in_eastern_time():
    s = get_session(date(2025, 6, 11))
    assert s.open_et == datetime(2025, 6, 11, 9, 30, tzinfo=ET)
    assert s.close_et == datetime(2025, 6, 11, 16, 0, tzinfo=ET)
    assert s.is_half_day is False


def test_half_day_close_1300():
    s = get_session(date(2025, 11, 28))
    assert s.close_et.time() == time(13, 0)
    assert s.is_half_day is True


def test_holiday_is_not_a_session():
    assert get_session(date(2025, 12, 25)) is None


@pytest.mark.parametrize("day", [date(2025, 3, 10), date(2025, 11, 3)])
def test_close_is_1600_et_across_dst_changes(day):
    assert get_session(day).close_et.hour == 16


def test_cutoffs_0dte_regular_day():
    last_entry, hard_exit = entry_exit_cutoffs(date(2025, 6, 11), is_0dte=True)
    assert (last_entry.time(), hard_exit.time()) == (time(15, 0), time(15, 25))


def test_cutoffs_other_expiries_regular_day():
    last_entry, hard_exit = entry_exit_cutoffs(date(2025, 6, 11), is_0dte=False)
    assert (last_entry.time(), hard_exit.time()) == (time(15, 15), time(15, 45))


def test_cutoffs_follow_half_day_close():
    last_entry, hard_exit = entry_exit_cutoffs(date(2025, 11, 28), is_0dte=True)
    assert (last_entry.time(), hard_exit.time()) == (time(12, 0), time(12, 25))


def test_cutoffs_reject_non_session():
    with pytest.raises(ValueError):
        entry_exit_cutoffs(date(2025, 12, 25), is_0dte=False)


def test_session_navigation_and_range():
    assert previous_session_on_or_before(date(2025, 12, 25)) == date(2025, 12, 24)
    assert next_session_on_or_after(date(2025, 12, 25)) == date(2025, 12, 26)
    assert [s.day for s in sessions_between(date(2025, 12, 22), date(2025, 12, 29))] == [
        date(2025, 12, 22), date(2025, 12, 23), date(2025, 12, 24), date(2025, 12, 26), date(2025, 12, 29)
    ]
