"""VWAP_RECLAIM and VWAP_PULLBACK (spec §6)."""

from __future__ import annotations

import numpy as np

from src.options_research.setups.base import (
    COOLDOWN,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    LONG,
    MAX_PER_DAY,
    SHORT,
    DayContext,
    first_true,
    grid_signal,
    previous_run,
    window_mask,
    with_cooldown,
)

RUN_BARS = 30
ATR_OFFSET = 0.1
SPY_SLOPE_BARS = 30
_WINDOW = f"{DEFAULT_WINDOW_START.strftime('%H:%M')}-{DEFAULT_WINDOW_END.strftime('%H:%M')}"
_COOLDOWN_MIN = int(COOLDOWN.total_seconds() // 60)
RECLAIM_PARAMS = {"run_bars": RUN_BARS, "atr_offset": ATR_OFFSET, "window": _WINDOW, "invalidation": "close vs VWAP -/+ 0.1 ATR5"}
PULLBACK_PARAMS = {"run_bars": RUN_BARS, "atr_offset": ATR_OFFSET, "spy_slope_bars": SPY_SLOPE_BARS, "cooldown_min": _COOLDOWN_MIN, "max_per_day": MAX_PER_DAY, "window": _WINDOW, "invalidation": "close vs VWAP -/+ 0.1 ATR5"}


def _arrays(ctx: DayContext, *columns: str) -> list[np.ndarray]:
    return [ctx.grid[column].to_numpy(dtype=float) for column in columns]


def detect_vwap_reclaim(ctx: DayContext) -> list[dict]:
    close, vwap, atr = _arrays(ctx, "close", "vwap", "atr5")
    window = window_mask(ctx.grid["decision_ts"], ctx.session, DEFAULT_WINDOW_START, DEFAULT_WINDOW_END)
    signals = []
    i = first_true(window & (previous_run(close < vwap) >= RUN_BARS) & (close >= vwap + ATR_OFFSET * atr))
    if i is not None:
        signals.append(grid_signal(ctx, "VWAP_RECLAIM", LONG, i, "vwap_atr", "below", -ATR_OFFSET, "close>=vwap+0.1atr after 30 closes below"))
    i = first_true(window & (previous_run(close > vwap) >= RUN_BARS) & (close <= vwap - ATR_OFFSET * atr))
    if i is not None:
        signals.append(grid_signal(ctx, "VWAP_RECLAIM", SHORT, i, "vwap_atr", "above", ATR_OFFSET, "close<=vwap-0.1atr after 30 closes above"))
    return signals


def spy_regime(ctx: DayContext) -> tuple[np.ndarray, np.ndarray]:
    """(up, down) per grid row: SPY close vs SPY VWAP, and SPY VWAP change over the previous 30 bars."""
    n = len(ctx.grid)
    if ctx.spy_grid is None or ctx.spy_grid.empty:
        return np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    spy = ctx.spy_grid.set_index("ts")[["close", "vwap"]].reindex(ctx.grid["ts"])
    slope = spy["vwap"] - spy["vwap"].shift(SPY_SLOPE_BARS)
    up = (spy["close"] > spy["vwap"]) & (slope > 0)
    down = (spy["close"] < spy["vwap"]) & (slope < 0)
    return up.to_numpy(dtype=bool), down.to_numpy(dtype=bool)


def detect_vwap_pullback(ctx: DayContext) -> list[dict]:
    close, low, high, vwap, atr = _arrays(ctx, "close", "low", "high", "vwap", "atr5")
    window = window_mask(ctx.grid["decision_ts"], ctx.session, DEFAULT_WINDOW_START, DEFAULT_WINDOW_END)
    up, down = spy_regime(ctx)
    decisions = ctx.grid["decision_ts"]
    longs = window & up & (previous_run(close > vwap) >= RUN_BARS) & (low <= vwap + ATR_OFFSET * atr) & (close > vwap)
    shorts = window & down & (previous_run(close < vwap) >= RUN_BARS) & (high >= vwap - ATR_OFFSET * atr) & (close < vwap)
    signals = [grid_signal(ctx, "VWAP_PULLBACK", LONG, i, "vwap_atr", "below", -ATR_OFFSET, "low<=vwap+0.1atr, close>vwap, SPY up") for i in with_cooldown(longs, decisions)]
    signals += [grid_signal(ctx, "VWAP_PULLBACK", SHORT, i, "vwap_atr", "above", ATR_OFFSET, "high>=vwap-0.1atr, close<vwap, SPY down") for i in with_cooldown(shorts, decisions)]
    return signals
