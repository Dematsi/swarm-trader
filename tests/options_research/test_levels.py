from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from src.options_research.features import split_by_day
from src.options_research.levels import (
    DayLevels,
    assert_premarket_readable,
    clean_grid,
    day_levels,
    history_minutes,
    session_summaries,
)
from src.options_research.market_calendar import ET, get_session

THU, FRI, MON = date(2025, 5, 29), date(2025, 5, 30), date(2025, 6, 2)
SESSIONS = [get_session(THU), get_session(FRI), get_session(MON)]
SPLITS = pd.DataFrame([{"symbol": "TEST", "day": MON, "ratio": 2.0, "factor": 0.5}])


def at(day, hhmm):
    return pd.Timestamp(f"{day} {hhmm}", tz="America/New_York").tz_convert("UTC")


def bar(day, hhmm, o, h, l, c, v, high_clean="raw", low_clean="raw"):
    return {
        "symbol": "TEST", "ts": at(day, hhmm), "open": o, "high": h, "low": l, "close": c, "volume": v, "transactions": 1,
        "bad_high": high_clean != "raw", "bad_low": low_clean != "raw",
        "high_clean": h if high_clean == "raw" else high_clean, "low_clean": l if low_clean == "raw" else low_clean, "source": "zip",
    }


def minutes():
    rows = []
    for m in range(15):
        rows.append(bar(THU, f"09:{30 + m}", 200, 201, 199, 200, 1000))
        rows.append(bar(FRI, f"09:{30 + m}", 200, 205, 195, 200, 2000))
    rows += [
        bar(THU, "15:59", 198, 198, 198, 198, 10),
        bar(FRI, "12:00", 200, 300, 199, 200, 10, high_clean=210.0),
        bar(FRI, "13:00", 250, 400, 100, 250, 10, high_clean=np.nan, low_clean=np.nan),
        bar(FRI, "15:59", 200, 200, 200, 200, 10),
        bar(MON, "07:00", 150, 150, 150, 150, 300, high_clean=np.nan, low_clean=np.nan),
        bar(MON, "08:00", 100, 120, 80, 100, 50),
        bar(MON, "09:00", 100, 101, 99, 100, 500, high_clean=100.8, low_clean=99.2),
        bar(MON, "09:30", 100, 100, 100, 100, 700),
    ]
    return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)


def test_premarket_levels_are_not_readable_before_0937():
    with pytest.raises(ValueError):
        assert_premarket_readable(datetime(2025, 6, 2, 9, 36, tzinfo=ET))
    assert_premarket_readable(datetime(2025, 6, 2, 9, 37, tzinfo=ET))


def test_day_levels_are_filtered_clean_and_split_adjusted():
    summaries = session_summaries(split_by_day(minutes()), SESSIONS)
    levels = day_levels(summaries, SPLITS, "TEST", SESSIONS, 2, lookback=2)
    assert levels.day == MON
    assert levels.prior_close == pytest.approx(100.0)
    assert levels.prior_high == pytest.approx(105.0)
    assert levels.prior_low == pytest.approx(97.5)
    assert levels.premarket_high == pytest.approx(100.8)
    assert levels.premarket_low == pytest.approx(99.2)
    assert levels.or_volume_median == {15: pytest.approx(45000.0), 30: pytest.approx(45000.0)}


def test_day_levels_need_full_lookback_and_a_prior_session():
    summaries = session_summaries(split_by_day(minutes()), SESSIONS)
    assert day_levels(summaries, SPLITS, "TEST", SESSIONS, 2, lookback=3).or_volume_median == {15: None, 30: None}
    first = day_levels(summaries, SPLITS, "TEST", SESSIONS, 0, lookback=2)
    assert first == DayLevels(day=THU, or_volume_median={15: None, 30: None})


def test_history_minutes_use_clean_bars_and_adjust_for_splits():
    by_day = split_by_day(minutes())
    grids = {s.day: clean_grid(by_day.get(s.day), s) for s in SESSIONS}
    assert history_minutes(grids, SPLITS, "TEST", SESSIONS, 1, n_sessions=2) is None
    history = history_minutes(grids, SPLITS, "TEST", SESSIONS, 2, n_sessions=2)
    assert len(history) == 780
    fri_noon = history[history["ts"] == at(FRI, "12:00")].iloc[0]
    assert fri_noon["high"] == pytest.approx(105.0)
    fri_one = history[history["ts"] == at(FRI, "13:00")].iloc[0]
    assert bool(fri_one["filled"]) and fri_one["close"] == pytest.approx(100.0) and fri_one["high"] == pytest.approx(100.0)
    thu_open = history[history["ts"] == at(THU, "09:30")].iloc[0]
    assert thu_open["volume"] == 2000 and thu_open["close"] == pytest.approx(100.0)
