"""NYSE sessions, half-days and per-day entry/exit cutoffs (spec §5.2, §7.5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from src.options_research.config import TZ_ET

ET = ZoneInfo(TZ_ET)
_REGULAR_CLOSE = time(16, 0)


@dataclass(frozen=True)
class Session:
    day: date
    open_et: datetime
    close_et: datetime

    @property
    def is_half_day(self) -> bool:
        return self.close_et.time() < _REGULAR_CLOSE


@lru_cache(maxsize=1)
def _schedule() -> pd.DataFrame:
    return xcals.get_calendar("XNYS", start="2021-01-04", end="2027-12-31").schedule


def _to_session(index: pd.Timestamp, row: pd.Series) -> Session:
    return Session(
        day=index.date(),
        open_et=row["open"].tz_convert(ET).to_pydatetime(),
        close_et=row["close"].tz_convert(ET).to_pydatetime(),
    )


def get_session(day: date) -> Session | None:
    key = pd.Timestamp(day)
    schedule = _schedule()
    if key not in schedule.index:
        return None
    return _to_session(key, schedule.loc[key])


def sessions_between(start: date, end: date) -> list[Session]:
    window = _schedule().loc[pd.Timestamp(start):pd.Timestamp(end)]
    return [_to_session(index, row) for index, row in window.iterrows()]


def previous_session_on_or_before(day: date) -> date:
    candidate = day
    for _ in range(10):
        if get_session(candidate) is not None:
            return candidate
        candidate -= timedelta(days=1)
    raise ValueError(f"no session within 10 days on or before {day}")


def next_session_on_or_after(day: date) -> date:
    candidate = day
    for _ in range(10):
        if get_session(candidate) is not None:
            return candidate
        candidate += timedelta(days=1)
    raise ValueError(f"no session within 10 days on or after {day}")


def entry_exit_cutoffs(day: date, is_0dte: bool) -> tuple[datetime, datetime]:
    session = get_session(day)
    if session is None:
        raise ValueError(f"{day} is not a trading session")
    if is_0dte:
        return session.close_et - timedelta(minutes=60), session.close_et - timedelta(minutes=35)
    return session.close_et - timedelta(minutes=45), session.close_et - timedelta(minutes=15)
