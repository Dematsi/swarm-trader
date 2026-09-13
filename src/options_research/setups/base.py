"""Shared plumbing for stage-1 setup detectors (spec §6).

A detector takes a `DayContext` and returns signal dicts with SIGNAL_COLUMNS keys for both
directions. Windows are evaluated on decision time T (ET, inclusive) and capped at close − 60 min,
the §7.5 last entry for 0DTE, so every signal is tradable in every contract variant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta

import numpy as np
import pandas as pd

from src.options_research.config import TZ_ET
from src.options_research.levels import DayLevels
from src.options_research.market_calendar import Session

LONG = "long"
SHORT = "short"
SIGNAL_COLUMNS = ["symbol", "day", "setup", "direction", "bar_ts", "decision_ts", "price", "atr5", "inval_kind", "inval_side", "inval_value", "trigger"]
DEFAULT_WINDOW_START = time(10, 0)
DEFAULT_WINDOW_END = time(15, 0)
LAST_ENTRY_BEFORE_CLOSE = timedelta(minutes=60)
COOLDOWN = pd.Timedelta(minutes=30)
MAX_PER_DAY = 2


@dataclass(frozen=True)
class DayContext:
    symbol: str
    session: Session
    grid: pd.DataFrame
    five: pd.DataFrame
    levels: DayLevels
    spy_grid: pd.DataFrame | None = None


def window_mask(decision_ts: pd.Series, session: Session, start: time, end: time) -> np.ndarray:
    latest = min(end, (session.close_et - LAST_ENTRY_BEFORE_CLOSE).time())
    clock = decision_ts.dt.tz_convert(TZ_ET).dt.time
    return ((clock >= start) & (clock <= latest)).to_numpy(dtype=bool)


def previous_run(flags) -> np.ndarray:
    """Length of the run of True values ending just before each position."""
    out = np.zeros(len(flags), dtype=np.int64)
    count = 0
    for i, flag in enumerate(flags):
        out[i] = count
        count = count + 1 if flag else 0
    return out


def first_true(mask) -> int | None:
    hits = np.flatnonzero(mask)
    return int(hits[0]) if hits.size else None


def with_cooldown(mask, decision_ts: pd.Series, cooldown: pd.Timedelta = COOLDOWN, max_per_day: int = MAX_PER_DAY) -> list[int]:
    chosen: list[int] = []
    last = None
    for i in np.flatnonzero(mask):
        decided = decision_ts.iloc[i]
        if last is not None and decided - last < cooldown:
            continue
        chosen.append(int(i))
        last = decided
        if len(chosen) == max_per_day:
            break
    return chosen


def opening_range(ctx: DayContext, minutes: int) -> tuple[float, float, float] | None:
    """(high, low, volume) of the regular-hours bars in the first `minutes` minutes."""
    end = pd.Timestamp(ctx.session.open_et) + pd.Timedelta(minutes=minutes)
    inside = ctx.grid[ctx.grid["ts"] < end]
    if inside.empty:
        return None
    return float(inside["high"].max()), float(inside["low"].min()), float(inside["volume"].sum())


def make_signal(ctx: DayContext, setup: str, direction: str, bar_ts, decision_ts, price, atr5, inval_kind: str, inval_side: str, inval_value, trigger: str) -> dict:
    return {
        "symbol": ctx.symbol,
        "day": ctx.session.day,
        "setup": setup,
        "direction": direction,
        "bar_ts": pd.Timestamp(bar_ts),
        "decision_ts": pd.Timestamp(decision_ts),
        "price": float(price),
        "atr5": float(atr5),
        "inval_kind": inval_kind,
        "inval_side": inval_side,
        "inval_value": float(inval_value),
        "trigger": trigger,
    }


def grid_signal(ctx: DayContext, setup: str, direction: str, i: int, inval_kind: str, inval_side: str, inval_value, trigger: str) -> dict:
    row = ctx.grid.iloc[i]
    return make_signal(ctx, setup, direction, row["ts"], row["decision_ts"], row["close"], row["atr5"], inval_kind, inval_side, inval_value, trigger)
