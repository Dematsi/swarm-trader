"""After-the-window levels for stage-1 setups (spec §5.1 hindsight rule, §6).

Covers prior-day close/high/low, filtered pre-market high/low, opening-range volume history, and
indicator warm-up history. All of them are split-adjusted to the signal day.

This is the only feature module allowed to read the hindsight columns (`high_clean`, `low_clean`).
It reads them only for bars whose cleaning window has closed before use: earlier sessions, and
pre-market bars read at or after 09:37 ET. The prior-day close is the raw close.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time

import numpy as np
import pandas as pd

from src.options_research.config import TZ_ET
from src.options_research.corporate_actions import adjustment_factors
from src.options_research.features import GRID_COLUMNS, session_grid
from src.options_research.market_calendar import Session

PREMARKET_START = time(4, 0)
PREMARKET_MIN_VOLUME = 100
EARLIEST_PREMARKET_READ = time(9, 37)
OR_MINUTES = (15, 30)
OR_VOLUME_LOOKBACK = 20
WARMUP_SESSIONS = 5
SUMMARY_COLUMNS = ["rth_close", "rth_high", "rth_low", "pm_high", "pm_low", "or15_volume", "or30_volume"]


@dataclass(frozen=True)
class DayLevels:
    day: date
    prior_close: float | None = None
    prior_high: float | None = None
    prior_low: float | None = None
    premarket_high: float | None = None
    premarket_low: float | None = None
    or_volume_median: dict[int, float | None] = field(default_factory=dict)


def assert_premarket_readable(decision_et: datetime) -> None:
    """Pre-market clean values depend on bars up to 09:36 (centered window), so they are final only from 09:37 ET."""
    if decision_et.time() < EARLIEST_PREMARKET_READ:
        raise ValueError(f"pre-market clean levels are not final until {EARLIEST_PREMARKET_READ} ET; asked at {decision_et.time()}")


def _price_relatives(splits: pd.DataFrame, symbol: str, days: list[date]) -> np.ndarray:
    """result[i] converts a price from days[i] into days[-1] terms."""
    factors = adjustment_factors(splits, symbol, pd.Series(days))
    return (factors / factors.iloc[-1]).to_numpy()


def _value(summaries: pd.DataFrame, day: date, column: str) -> float | None:
    if day not in summaries.index:
        return None
    value = summaries.at[day, column]
    return None if pd.isna(value) else float(value)


def session_summaries(by_day: dict[date, pd.DataFrame], sessions: list[Session]) -> pd.DataFrame:
    """Unadjusted per-session values: raw RTH close, clean RTH high/low, filtered clean pre-market high/low, OR volumes."""
    rows = []
    for session in sessions:
        row: dict = {"day": session.day}
        frame = by_day.get(session.day)
        if frame is not None and not frame.empty:
            et = frame["ts"].dt.tz_convert(TZ_ET)
            open_ts, close_ts = pd.Timestamp(session.open_et), pd.Timestamp(session.close_et)
            rth = frame[(et >= open_ts) & (et < close_ts)]
            pre = frame[(et.dt.time >= PREMARKET_START) & (et < open_ts) & (frame["volume"] >= PREMARKET_MIN_VOLUME)]
            if not rth.empty:
                rth_et = rth["ts"].dt.tz_convert(TZ_ET)
                row["rth_close"] = float(rth.sort_values("ts")["close"].iloc[-1])
                row["rth_high"] = rth["high_clean"].max()
                row["rth_low"] = rth["low_clean"].min()
                for minutes in OR_MINUTES:
                    row[f"or{minutes}_volume"] = float(rth.loc[rth_et < open_ts + pd.Timedelta(minutes=minutes), "volume"].sum())
            if not pre.empty:
                row["pm_high"] = pre["high_clean"].max()
                row["pm_low"] = pre["low_clean"].min()
        rows.append(row)
    return pd.DataFrame(rows).reindex(columns=["day"] + SUMMARY_COLUMNS).set_index("day")


def day_levels(summaries: pd.DataFrame, splits: pd.DataFrame, symbol: str, sessions: list[Session], index: int, lookback: int = OR_VOLUME_LOOKBACK) -> DayLevels:
    """Levels for sessions[index]: earlier sessions split-adjusted to that day, plus its own pre-market."""
    day = sessions[index].day
    premarket = {"premarket_high": _value(summaries, day, "pm_high"), "premarket_low": _value(summaries, day, "pm_low")}
    if index == 0:
        return DayLevels(day=day, or_volume_median={m: None for m in OR_MINUTES}, **premarket)
    window = [s.day for s in sessions[max(0, index - lookback): index]]
    relatives = _price_relatives(splits, symbol, window + [day])[:-1]
    prior = window[-1]

    def adjusted(column: str) -> float | None:
        value = _value(summaries, prior, column)
        return None if value is None else value * relatives[-1]

    medians: dict[int, float | None] = {}
    for minutes in OR_MINUTES:
        volumes = [_value(summaries, d, f"or{minutes}_volume") for d in window]
        complete = len(window) == lookback and all(v is not None for v in volumes)
        medians[minutes] = float(np.median([v / r for v, r in zip(volumes, relatives)])) if complete else None
    return DayLevels(day=day, prior_close=adjusted("rth_close"), prior_high=adjusted("rth_high"), prior_low=adjusted("rth_low"), or_volume_median=medians, **premarket)


def clean_grid(day_minutes: pd.DataFrame | None, session: Session) -> pd.DataFrame:
    """Regular-hours grid from clean high/low. Bars with an empty clean value are dropped; that minute repeats the previous close."""
    if day_minutes is None or day_minutes.empty:
        return pd.DataFrame(columns=GRID_COLUMNS)
    kept = day_minutes[day_minutes["high_clean"].notna() & day_minutes["low_clean"].notna()]
    return session_grid(kept.assign(high=kept["high_clean"], low=kept["low_clean"]), session)


def history_minutes(clean_grids: dict[date, pd.DataFrame], splits: pd.DataFrame, symbol: str, sessions: list[Session], index: int, n_sessions: int = WARMUP_SESSIONS) -> pd.DataFrame | None:
    """Earlier sessions' clean 1-min grids for indicator warm-up, split-adjusted to sessions[index].day. None if any is missing."""
    if index < n_sessions:
        return None
    earlier = sessions[index - n_sessions: index]
    relatives = _price_relatives(splits, symbol, [s.day for s in earlier] + [sessions[index].day])
    parts = []
    for session, relative in zip(earlier, relatives[:-1]):
        grid = clean_grids.get(session.day)
        if grid is None or grid.empty:
            return None
        grid = grid.copy()
        grid[["open", "high", "low", "close"]] = grid[["open", "high", "low", "close"]] * relative
        grid["volume"] = (grid["volume"] / relative).round().astype("int64")
        parts.append(grid)
    return pd.concat(parts, ignore_index=True)
