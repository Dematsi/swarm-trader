"""Synthetic DayContext builders and the point-in-time check for setup detectors (spec §10).

`assert_point_in_time` perturbs every 1-min row starting at or after a cut time T, and every
5-min bar ending after T. It then requires every signal decided at or before T to stay identical.
"""

from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

from src.options_research.features import FIVE_COLUMNS
from src.options_research.levels import DayLevels
from src.options_research.market_calendar import get_session
from src.options_research.setups.base import DayContext

DAY = date(2025, 6, 2)
SESSION = get_session(DAY)
MINUTES = pd.date_range(SESSION.open_et, SESSION.close_et, freq="1min", inclusive="left").tz_convert("UTC").as_unit("ns")
FIVES = pd.date_range(SESSION.open_et, SESSION.close_et, freq="5min", inclusive="left").tz_convert("UTC").as_unit("ns")
TIME_COLUMNS = {"ts", "end", "decision_ts"}


def at(hhmm: str) -> pd.Timestamp:
    return pd.Timestamp(f"{DAY} {hhmm}", tz="America/New_York").tz_convert("UTC")


def idx(hhmm: str) -> int:
    return int(np.flatnonzero(MINUTES == at(hhmm))[0])


def five_idx(hhmm: str) -> int:
    return int(np.flatnonzero(FIVES == at(hhmm))[0])


def _full(value, n: int) -> np.ndarray:
    return np.broadcast_to(np.asarray(value, dtype=float), (n,)).copy()


def make_grid(close=100.0, *, vwap=100.0, sigma=0.5, atr5=1.0, rsi14=50.0, adx14=25.0, volume=1000, spread=0.05) -> pd.DataFrame:
    n = len(MINUTES)
    closes = _full(close, n)
    grid = pd.DataFrame({"ts": MINUTES, "open": closes, "high": closes + spread, "low": closes - spread, "close": closes, "volume": np.full(n, volume, dtype=np.int64), "filled": False})
    grid["decision_ts"] = grid["ts"] + pd.Timedelta(minutes=1)
    for name, value in {"vwap": vwap, "sigma": sigma, "atr5": atr5, "rsi14": rsi14, "adx14": adx14}.items():
        grid[name] = _full(value, n)
    return grid


def set_bar(grid: pd.DataFrame, hhmm: str, close: float, high: float | None = None, low: float | None = None) -> None:
    i = idx(hhmm)
    grid.loc[i, ["open", "close"]] = close
    grid.loc[i, "high"] = close + 0.05 if high is None else high
    grid.loc[i, "low"] = close - 0.05 if low is None else low


def make_five(close=100.0, *, bb_up=101.0, bb_lo=99.0, kc_mid=100.0, atr14=1.0) -> pd.DataFrame:
    n = len(FIVES)
    closes = _full(close, n)
    frame = pd.DataFrame({
        "ts": FIVES, "end": FIVES + pd.Timedelta(minutes=5), "open": closes, "high": closes + 0.1, "low": closes - 0.1, "close": closes,
        "volume": np.full(n, 5000, dtype=np.int64), "atr14": _full(atr14, n), "rsi14": _full(50.0, n), "adx14": _full(25.0, n),
        "bb_up": _full(bb_up, n), "bb_lo": _full(bb_lo, n), "kc_mid": _full(kc_mid, n), "kc_up": _full(kc_mid, n) + 2.0, "kc_lo": _full(kc_mid, n) - 2.0,
        "squeeze": np.zeros(n, dtype=bool),
    })
    return frame[FIVE_COLUMNS]


def make_ctx(grid=None, *, levels=None, five=None, spy_grid=None, symbol="TEST") -> DayContext:
    return DayContext(
        symbol=symbol,
        session=SESSION,
        grid=make_grid() if grid is None else grid,
        five=pd.DataFrame(columns=FIVE_COLUMNS) if five is None else five,
        levels=levels or DayLevels(day=DAY),
        spy_grid=spy_grid,
    )


def _perturb(frame, time_column, cut, rng, strict):
    if frame is None or frame.empty:
        return frame
    out = frame.copy()
    later = (out[time_column] > cut) if strict else (out[time_column] >= cut)
    count = int(later.sum())
    for column in out.columns:
        if column in TIME_COLUMNS:
            continue
        if out[column].dtype == bool:
            values = out[column].to_numpy().copy()
            values[later.to_numpy()] = rng.random(count) < 0.5
            out[column] = values
        elif np.issubdtype(out[column].dtype, np.number):
            values = out[column].astype(float).to_numpy().copy()
            values[later.to_numpy()] = values[later.to_numpy()] * rng.uniform(0.95, 1.05, count)
            out[column] = values
    return out


def signal_key(signal: dict) -> tuple:
    return (signal["setup"], signal["direction"], signal["decision_ts"], round(signal["price"], 9), signal["inval_kind"], signal["inval_side"], round(signal["inval_value"], 9))


def assert_point_in_time(detect, ctx: DayContext, extra_cuts=("10:15", "11:45", "14:30"), seed: int = 0) -> list[dict]:
    base = detect(ctx)
    cuts = sorted({s["decision_ts"] for s in base} | {at(c) for c in extra_cuts})
    rng = np.random.default_rng(seed)
    for cut in cuts:
        perturbed = replace(
            ctx,
            grid=_perturb(ctx.grid, "ts", cut, rng, strict=False),
            five=_perturb(ctx.five, "end", cut, rng, strict=True),
            spy_grid=_perturb(ctx.spy_grid, "ts", cut, rng, strict=False),
        )
        expected = sorted(signal_key(s) for s in base if s["decision_ts"] <= cut)
        actual = sorted(signal_key(s) for s in detect(perturbed) if s["decision_ts"] <= cut)
        assert actual == expected, f"signals decided by {cut} changed after perturbing later bars"
    return base
