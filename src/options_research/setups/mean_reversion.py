"""MEANREV fade (spec §6)."""

from __future__ import annotations

from src.options_research.setups.base import DEFAULT_WINDOW_END, DEFAULT_WINDOW_START, LONG, SHORT, DayContext, grid_signal, window_mask, with_cooldown

ADX_MAX = 20.0
SIGMA_MULT = 2.5
RSI_LOW = 25.0
RSI_HIGH = 75.0
INVALIDATION_ATR = 0.1
PARAMS = {"adx_max": ADX_MAX, "sigma_mult": SIGMA_MULT, "rsi_low": RSI_LOW, "rsi_high": RSI_HIGH, "invalidation_atr": INVALIDATION_ATR, "cooldown_min": 30, "max_per_day": 2, "window": "10:00-15:00"}


def detect_meanrev(ctx: DayContext) -> list[dict]:
    grid = ctx.grid
    close, low, high = (grid[c].to_numpy(dtype=float) for c in ("close", "low", "high"))
    vwap, sigma, rsi, adx, atr = (grid[c].to_numpy(dtype=float) for c in ("vwap", "sigma", "rsi14", "adx14", "atr5"))
    window = window_mask(grid["decision_ts"], ctx.session, DEFAULT_WINDOW_START, DEFAULT_WINDOW_END)
    calm = adx < ADX_MAX
    longs = window & calm & (close <= vwap - SIGMA_MULT * sigma) & (rsi <= RSI_LOW)
    shorts = window & calm & (close >= vwap + SIGMA_MULT * sigma) & (rsi >= RSI_HIGH)
    signals = [grid_signal(ctx, "MEANREV", LONG, i, "level", "below", low[i] - INVALIDATION_ATR * atr[i], "close<=vwap-2.5sigma, rsi<=25, adx<20") for i in with_cooldown(longs, grid["decision_ts"])]
    signals += [grid_signal(ctx, "MEANREV", SHORT, i, "level", "above", high[i] + INVALIDATION_ATR * atr[i], "close>=vwap+2.5sigma, rsi>=75, adx<20") for i in with_cooldown(shorts, grid["decision_ts"])]
    return signals
