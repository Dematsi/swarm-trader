"""ORB15 / ORB30 opening range breakout (spec §6)."""

from __future__ import annotations

from datetime import time, timedelta

from src.options_research.setups.base import LONG, SHORT, DayContext, first_true, grid_signal, opening_range, window_mask

WINDOW_END = time(11, 30)
VOLUME_MULT = 1.2
PARAMS = {"window_end": "11:30", "volume_mult": VOLUME_MULT, "volume_lookback_sessions": 20, "trigger": "first 1-min close beyond OR", "invalidation": "close vs OR midpoint"}


def detect_orb(ctx: DayContext, minutes: int) -> list[dict]:
    median = ctx.levels.or_volume_median.get(minutes)
    bounds = opening_range(ctx, minutes)
    if median is None or bounds is None:
        return []
    high, low, volume = bounds
    if volume < VOLUME_MULT * median:
        return []
    start = (ctx.session.open_et + timedelta(minutes=minutes + 1)).time()
    window = window_mask(ctx.grid["decision_ts"], ctx.session, start, WINDOW_END)
    close = ctx.grid["close"].to_numpy()
    midpoint = (high + low) / 2.0
    setup = f"ORB{minutes}"
    signals = []
    i = first_true(window & (close > high))
    if i is not None:
        signals.append(grid_signal(ctx, setup, LONG, i, "level", "below", midpoint, "close>or_high"))
    i = first_true(window & (close < low))
    if i is not None:
        signals.append(grid_signal(ctx, setup, SHORT, i, "level", "above", midpoint, "close<or_low"))
    return signals
