"""Point-in-time intraday features from raw 1-min bars (spec §6).

A value on the row for the bar starting at `ts` is known at decision time `ts + 1 min` and uses no
later bar. This module reads raw OHLCV only. Levels that need the hindsight (clean) columns live in
`levels.py`.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from src.options_research.config import TZ_ET
from src.options_research.market_calendar import Session

GRID_COLUMNS = ["ts", "open", "high", "low", "close", "volume", "filled"]
BAR_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]
FIVE_COLUMNS = ["ts", "end", "open", "high", "low", "close", "volume", "atr14", "rsi14", "adx14", "bb_up", "bb_lo", "kc_mid", "kc_up", "kc_lo", "squeeze"]
ONE_MINUTE = pd.Timedelta(minutes=1)
FIVE_MINUTES = pd.Timedelta(minutes=5)
ATR_N = 14
RSI_N = 14
ADX_N = 14
BB_N = 20
BB_K = 2.0
KC_N = 20
KC_K = 1.5


def split_by_day(minutes: pd.DataFrame) -> dict[date, pd.DataFrame]:
    """Group minute rows by their America/New_York calendar date."""
    if minutes.empty:
        return {}
    days = minutes["ts"].dt.tz_convert(TZ_ET).dt.date
    return {day: frame.reset_index(drop=True) for day, frame in minutes.groupby(days, sort=True)}


def session_grid(minutes: pd.DataFrame, session: Session) -> pd.DataFrame:
    """One row per regular-hours minute [open, close). Minutes without trades repeat the last close with volume 0."""
    index = pd.date_range(session.open_et, session.close_et, freq="1min", inclusive="left").tz_convert("UTC").as_unit("ns")
    bars = minutes[BAR_COLUMNS].copy()
    bars["ts"] = pd.to_datetime(bars["ts"], utc=True).dt.as_unit("ns")
    bars = bars[(bars["ts"] >= index[0]) & (bars["ts"] <= index[-1])].drop_duplicates("ts").set_index("ts")
    if bars.empty:
        return pd.DataFrame(columns=GRID_COLUMNS)
    grid = bars.reindex(index)
    filled = grid["close"].isna().to_numpy()
    # Leading minutes before the first trade of the session have no prior close to forward-fill, so they
    # take the first traded bar's open via this backward fill. That price is not known before the trade
    # happens, so it is a hindsight value for those leading minutes. It is acceptable here only because
    # every signal window starts at or after 09:46 ET, well after the open; revisit before using this grid
    # for thinner names or windows that can start earlier, where the first trade may land later still.
    close = grid["close"].ffill().fillna(grid["open"].bfill())
    for column in ("open", "high", "low"):
        grid[column] = grid[column].fillna(close)
    grid["close"] = close
    grid["volume"] = grid["volume"].fillna(0).astype("int64")
    grid["filled"] = filled
    return grid.rename_axis("ts").reset_index()[GRID_COLUMNS]


def add_vwap(grid: pd.DataFrame) -> pd.DataFrame:
    """Session VWAP of typical price (h+l+c)/3 and the volume-weighted σ of typical price around it."""
    out = grid.copy()
    typical = (out["high"] + out["low"] + out["close"]) / 3.0
    volume = out["volume"].astype(float)
    cumulative = volume.cumsum()
    cumulative = cumulative.where(cumulative > 0)
    vwap = (typical * volume).cumsum() / cumulative
    second_moment = (typical * typical * volume).cumsum() / cumulative
    out["vwap"] = vwap.fillna(typical)
    out["sigma"] = np.sqrt((second_moment - vwap**2).clip(lower=0.0)).fillna(0.0)
    return out


def five_minute_bars(grid: pd.DataFrame) -> pd.DataFrame:
    """5-min bars from 1-min rows; `end` is when the bar is complete. Empty bins (overnight) are dropped."""
    frame = grid.set_index("ts")
    agg = frame.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    counts = frame["close"].resample("5min").count()
    agg = agg[counts.to_numpy() > 0].rename_axis("ts").reset_index()
    agg["end"] = agg["ts"] + FIVE_MINUTES
    return agg[["ts", "end", "open", "high", "low", "close", "volume"]]


def wilder(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def true_range(bars: pd.DataFrame) -> pd.Series:
    prev_close = bars["close"].shift(1)
    ranges = pd.concat([bars["high"] - bars["low"], (bars["high"] - prev_close).abs(), (bars["low"] - prev_close).abs()], axis=1)
    return ranges.max(axis=1)


def rsi(close: pd.Series, n: int = RSI_N) -> pd.Series:
    delta = close.diff()
    gain = wilder(delta.clip(lower=0.0), n)
    loss = wilder((-delta).clip(lower=0.0), n)
    ratio = gain / loss.where(loss > 0)
    value = pd.Series(np.where(loss > 0, 100.0 - 100.0 / (1.0 + ratio), np.where(gain > 0, 100.0, 50.0)), index=close.index)
    return value.where(gain.notna() & loss.notna())


def adx(bars: pd.DataFrame, n: int = ADX_N) -> pd.Series:
    up = bars["high"].diff()
    down = -bars["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr = wilder(true_range(bars), n)
    plus_di = 100.0 * wilder(plus_dm, n) / atr
    minus_di = 100.0 * wilder(minus_dm, n) / atr
    total = plus_di + minus_di
    dx = (100.0 * (plus_di - minus_di).abs() / total.where(total > 0)).fillna(0.0).where(total.notna())
    return wilder(dx, n)


def add_indicators(five: pd.DataFrame) -> pd.DataFrame:
    out = five.copy()
    tr = true_range(out)
    out["atr14"] = wilder(tr, ATR_N)
    out["rsi14"] = rsi(out["close"], RSI_N)
    out["adx14"] = adx(out, ADX_N)
    mid = out["close"].rolling(BB_N).mean()
    sd = out["close"].rolling(BB_N).std(ddof=0)
    out["bb_up"] = mid + BB_K * sd
    out["bb_lo"] = mid - BB_K * sd
    out["kc_mid"] = out["close"].ewm(span=KC_N, adjust=False, min_periods=KC_N).mean()
    atr20 = wilder(tr, KC_N)
    out["kc_up"] = out["kc_mid"] + KC_K * atr20
    out["kc_lo"] = out["kc_mid"] - KC_K * atr20
    out["squeeze"] = ((out["bb_up"] < out["kc_up"]) & (out["bb_lo"] > out["kc_lo"])).astype(bool)
    return out[FIVE_COLUMNS]


def enrich_session(grid: pd.DataFrame, history: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add VWAP/σ and as-of 5-min indicators to today's grid; also return today's 5-min bars with indicators.

    `history` holds earlier sessions' 1-min rows (from `levels.history_minutes`), so indicators are warm
    at the open. A 5-min value reaches a 1-min row only once that 5-min bar is complete (`end <= ts + 1 min`).
    """
    today = add_vwap(grid)
    parts = [today[BAR_COLUMNS]] if history is None or history.empty else [history[BAR_COLUMNS], today[BAR_COLUMNS]]
    five = add_indicators(five_minute_bars(pd.concat(parts, ignore_index=True)))
    today["decision_ts"] = today["ts"] + ONE_MINUTE
    asof = five[["end", "atr14", "rsi14", "adx14"]].rename(columns={"end": "five_end", "atr14": "atr5"})
    merged = pd.merge_asof(today, asof, left_on="decision_ts", right_on="five_end", direction="backward").drop(columns=["five_end"])
    return merged, five[five["ts"] >= grid["ts"].iloc[0]].reset_index(drop=True)
