"""GAP_GO, GAP_FILL and PDL_BREAK (spec §6). Prior-day and pre-market levels come from `levels.DayLevels`."""

from __future__ import annotations

from datetime import time

import numpy as np

from src.options_research.config import TZ_ET
from src.options_research.levels import assert_premarket_readable
from src.options_research.setups.base import DEFAULT_WINDOW_END, LONG, SHORT, DayContext, first_true, grid_signal, opening_range, window_mask

GAP_THRESHOLD = 0.0075
GAP_GO_WINDOW = (time(9, 46), time(11, 30))
GAP_FILL_WINDOW = (time(9, 46), time(11, 0))
PDL_WINDOW = (time(9, 46), DEFAULT_WINDOW_END)
PDL_TRIGGER_ATR = 0.05
PDL_INVALIDATION_ATR = 0.1


def _window_str(bounds: tuple[time, time]) -> str:
    start, end = bounds
    return f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"


GAP_GO_PARAMS = {"gap": GAP_THRESHOLD, "window": _window_str(GAP_GO_WINDOW), "trigger": "close beyond filtered pre-market high/low", "invalidation": "close vs 09:30-09:45 opposite extreme"}
GAP_FILL_PARAMS = {"gap": GAP_THRESHOLD, "window": _window_str(GAP_FILL_WINDOW), "trigger": "close beyond 09:30-09:45 extreme toward prior close", "invalidation": "close vs 09:30-09:45 opposite extreme"}
PDL_PARAMS = {"window": _window_str(PDL_WINDOW), "trigger_atr": PDL_TRIGGER_ATR, "invalidation_atr": PDL_INVALIDATION_ATR, "levels": "prior RTH high/low, adjusted, clean"}


def gap(ctx: DayContext) -> float | None:
    prior = ctx.levels.prior_close
    if prior is None or ctx.grid.empty:
        return None
    return float(ctx.grid["open"].iloc[0]) / prior - 1.0


def detect_gap_go(ctx: DayContext) -> list[dict]:
    size, bounds = gap(ctx), opening_range(ctx, 15)
    if size is None or bounds is None:
        return []
    window = window_mask(ctx.grid["decision_ts"], ctx.session, *GAP_GO_WINDOW)
    hits = np.flatnonzero(window)
    if hits.size == 0:
        return []
    assert_premarket_readable(ctx.grid["decision_ts"].iloc[hits[0]].tz_convert(TZ_ET).to_pydatetime())
    high15, low15, _ = bounds
    close = ctx.grid["close"].to_numpy()
    signals = []
    if size >= GAP_THRESHOLD and ctx.levels.premarket_high is not None:
        i = first_true(window & (close > ctx.levels.premarket_high))
        if i is not None:
            signals.append(grid_signal(ctx, "GAP_GO", LONG, i, "level", "below", low15, "close>premarket_high"))
    if size <= -GAP_THRESHOLD and ctx.levels.premarket_low is not None:
        i = first_true(window & (close < ctx.levels.premarket_low))
        if i is not None:
            signals.append(grid_signal(ctx, "GAP_GO", SHORT, i, "level", "above", high15, "close<premarket_low"))
    return signals


def detect_gap_fill(ctx: DayContext) -> list[dict]:
    size, bounds = gap(ctx), opening_range(ctx, 15)
    if size is None or bounds is None:
        return []
    high15, low15, _ = bounds
    window = window_mask(ctx.grid["decision_ts"], ctx.session, *GAP_FILL_WINDOW)
    close = ctx.grid["close"].to_numpy()
    signals = []
    if size <= -GAP_THRESHOLD:
        i = first_true(window & (close > high15))
        if i is not None:
            signals.append(grid_signal(ctx, "GAP_FILL", LONG, i, "level", "below", low15, "close>or15_high"))
    if size >= GAP_THRESHOLD:
        i = first_true(window & (close < low15))
        if i is not None:
            signals.append(grid_signal(ctx, "GAP_FILL", SHORT, i, "level", "above", high15, "close<or15_low"))
    return signals


def detect_pdl_break(ctx: DayContext) -> list[dict]:
    window = window_mask(ctx.grid["decision_ts"], ctx.session, *PDL_WINDOW)
    close = ctx.grid["close"].to_numpy()
    atr = ctx.grid["atr5"].to_numpy(dtype=float)
    signals = []
    if ctx.levels.prior_high is not None:
        i = first_true(window & (close > ctx.levels.prior_high + PDL_TRIGGER_ATR * atr))
        if i is not None:
            signals.append(grid_signal(ctx, "PDL_BREAK", LONG, i, "level", "below", ctx.levels.prior_high - PDL_INVALIDATION_ATR * atr[i], "close>prior_high+0.05atr"))
    if ctx.levels.prior_low is not None:
        i = first_true(window & (close < ctx.levels.prior_low - PDL_TRIGGER_ATR * atr))
        if i is not None:
            signals.append(grid_signal(ctx, "PDL_BREAK", SHORT, i, "level", "above", ctx.levels.prior_low + PDL_INVALIDATION_ATR * atr[i], "close<prior_low-0.05atr"))
    return signals
