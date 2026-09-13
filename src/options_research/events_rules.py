"""Rule-computed market-structure/macro events and FOMC events (spec §5.2)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.options_research.market_calendar import (
    get_session,
    next_session_on_or_after,
    previous_session_on_or_before,
    sessions_between,
)

EVENT_COLUMNS = ["date", "time_et", "type", "tier", "source", "ticker"]
FOMC_CSV = Path(__file__).parent / "calendars" / "fomc_meetings.csv"
_FRIDAY = 4
_TUESDAY = 1


def make_event(day: date, time_et: str | None, type_: str, tier: str, source: str, ticker: str | None = None) -> dict:
    return {"date": day, "time_et": time_et, "type": type_, "tier": tier, "source": source, "ticker": ticker}


def _nth_friday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(_FRIDAY - first.weekday()) % 7 + 7 * (n - 1))


def third_friday(year: int, month: int) -> date:
    return _nth_friday(year, month, 3)


def fourth_friday(year: int, month: int) -> date:
    return _nth_friday(year, month, 4)


def _months(start: date, end: date) -> Iterator[tuple[int, int]]:
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _last_calendar_day(year: int, month: int) -> date:
    next_first = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return next_first - timedelta(days=1)


def _vix_expiration(year: int, month: int) -> date:
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    friday = third_friday(next_year, next_month)
    if get_session(friday) is None:
        friday = previous_session_on_or_before(friday - timedelta(days=1))
    return previous_session_on_or_before(friday - timedelta(days=30))


def rule_events(start: date, end: date) -> list[dict]:
    events: list[dict] = []

    def add(day: date, time_et: str | None, type_: str, tier: str) -> None:
        if start <= day <= end:
            events.append(make_event(day, time_et, type_, tier, "rule"))

    for year, month in _months(start, end):
        opex = previous_session_on_or_before(third_friday(year, month))
        add(opex, None, "opex", "market")
        if month in (3, 6, 9, 12):
            add(opex, None, "quad_witching", "market")
        add(_vix_expiration(year, month), None, "vix_expiration", "market")

        month_end = previous_session_on_or_before(_last_calendar_day(year, month))
        add(month_end, "16:00", "month_end", "market")
        if month in (3, 6, 9, 12):
            add(month_end, "16:00", "quarter_end", "market")

        month_sessions = sessions_between(date(year, month, 1), _last_calendar_day(year, month))
        if month_sessions:
            add(month_sessions[0].day, "10:00", "ism_manufacturing", "2")
        if len(month_sessions) >= 3:
            add(month_sessions[2].day, "10:00", "ism_services", "2")

        last_day = _last_calendar_day(year, month)
        last_tuesday = last_day - timedelta(days=(last_day.weekday() - _TUESDAY) % 7)
        add(previous_session_on_or_before(last_tuesday), "10:00", "consumer_confidence", "2")

        if month == 6:
            add(previous_session_on_or_before(fourth_friday(year, 6)), "16:00", "russell_reconstitution", "market")
    return events


def fomc_events(start: date, end: date, csv_path: Path = FOMC_CSV) -> list[dict]:
    meetings = pd.read_csv(csv_path, parse_dates=["start_date", "end_date"])
    events: list[dict] = []
    for decision in (ts.date() for ts in meetings["end_date"]):
        if start <= decision <= end:
            events.append(make_event(decision, "14:00", "fomc_decision", "1", "fomc_csv"))
            events.append(make_event(decision, "14:30", "fomc_press_conference", "1", "fomc_csv"))
        minutes_day = next_session_on_or_after(decision + timedelta(days=21))
        if start <= minutes_day <= end:
            events.append(make_event(minutes_day, "14:00", "fomc_minutes", "2", "fomc_csv"))
    return events
