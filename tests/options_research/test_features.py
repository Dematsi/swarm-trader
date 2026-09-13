from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.options_research.features import (
    FIVE_COLUMNS,
    add_indicators,
    add_vwap,
    adx,
    enrich_session,
    five_minute_bars,
    rsi,
    session_grid,
    split_by_day,
    true_range,
    wilder,
)
from src.options_research.market_calendar import get_session

DAY = date(2025, 6, 2)
SESSION = get_session(DAY)
PRIOR = get_session(date(2025, 5, 30))


def at(day, hhmm):
    return pd.Timestamp(f"{day} {hhmm}", tz="America/New_York").tz_convert("UTC")


def raw(rows, day=DAY):
    return pd.DataFrame(
        [{"symbol": "TEST", "ts": at(day, t), "open": o, "high": h, "low": l, "close": c, "volume": v} for t, o, h, l, c, v in rows]
    )


def random_minutes(session, seed):
    rng = np.random.default_rng(seed)
    ts = pd.date_range(session.open_et, session.close_et, freq="1min", inclusive="left").tz_convert("UTC")
    close = 100 + np.cumsum(rng.normal(0, 0.05, len(ts)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(0, 0.05, len(ts))
    low = np.minimum(open_, close) - rng.uniform(0, 0.05, len(ts))
    frame = pd.DataFrame({"symbol": "TEST", "ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": rng.integers(100, 5000, len(ts))})
    return frame.drop(index=rng.choice(len(frame), 5, replace=False)).reset_index(drop=True)


def bar_row(grid, day, hhmm):
    return grid[grid["ts"] == at(day, hhmm)].iloc[0]


def test_split_by_day_uses_eastern_dates():
    minutes = raw([("19:30", 1, 1, 1, 1, 1), ("09:30", 1, 1, 1, 1, 1)])
    minutes.loc[2] = {"symbol": "TEST", "ts": pd.Timestamp("2025-06-03T01:00Z"), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
    groups = split_by_day(minutes)
    assert list(groups) == [DAY]
    assert len(groups[DAY]) == 3


def test_session_grid_fills_missing_minutes():
    minutes = raw([("08:00", 1, 1, 1, 1, 1), ("09:31", 10, 11, 9, 10.5, 100), ("09:33", 10.6, 10.8, 10.4, 10.7, 50)])
    grid = session_grid(minutes, SESSION)
    assert len(grid) == 390
    first = bar_row(grid, DAY, "09:30")
    assert bool(first["filled"]) and first["open"] == first["high"] == first["low"] == first["close"] == 10.0 and first["volume"] == 0
    gap = bar_row(grid, DAY, "09:32")
    assert bool(gap["filled"]) and gap["open"] == gap["low"] == gap["close"] == 10.5 and gap["volume"] == 0
    traded = bar_row(grid, DAY, "09:33")
    assert not bool(traded["filled"]) and traded["close"] == 10.7 and traded["volume"] == 50
    assert grid["ts"].min() == at(DAY, "09:30")


def test_session_grid_empty_when_no_regular_hours_bars():
    assert session_grid(raw([("08:00", 1, 1, 1, 1, 1)]), SESSION).empty


def test_add_vwap_is_volume_weighted_typical_price():
    grid = pd.DataFrame({"high": [10.0, 12.0], "low": [10.0, 12.0], "close": [10.0, 12.0], "volume": [100, 300]})
    out = add_vwap(grid)
    assert out["vwap"].tolist() == pytest.approx([10.0, 11.5])
    assert out["sigma"].tolist() == pytest.approx([0.0, np.sqrt(0.75)])


def test_five_minute_bars_aggregate_and_mark_end():
    grid = session_grid(random_minutes(SESSION, 1), SESSION)
    five = five_minute_bars(grid)
    assert len(five) == 78
    first = grid.iloc[:5]
    assert five.iloc[0]["open"] == first["open"].iloc[0] and five.iloc[0]["close"] == first["close"].iloc[-1]
    assert five.iloc[0]["high"] == first["high"].max() and five.iloc[0]["volume"] == first["volume"].sum()
    assert five.iloc[0]["end"] == at(DAY, "09:35")


def test_true_range_and_atr_of_constant_range():
    bars = pd.DataFrame({"high": [102.0] * 30, "low": [100.0] * 30, "close": [101.0] * 30})
    assert true_range(bars).tolist() == pytest.approx([2.0] * 30)
    atr = wilder(true_range(bars), 14)
    assert atr.iloc[:13].isna().all() and atr.iloc[-1] == pytest.approx(2.0)


def test_rsi_extremes():
    rising = pd.Series(np.arange(40, dtype=float))
    assert rsi(rising, 14).iloc[-1] == pytest.approx(100.0)
    assert rsi(-rising, 14).iloc[-1] == pytest.approx(0.0)


def test_adx_of_steady_uptrend_is_100():
    i = np.arange(60, dtype=float)
    bars = pd.DataFrame({"high": 11 + i, "low": 10 + i, "close": 10.5 + i})
    assert adx(bars, 14).iloc[-1] == pytest.approx(100.0)


def test_flat_closes_are_in_squeeze():
    five = pd.DataFrame({"ts": pd.date_range("2025-06-02 13:30", periods=40, freq="5min", tz="UTC"), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1})
    five["end"] = five["ts"] + pd.Timedelta(minutes=5)
    out = add_indicators(five)
    assert list(out.columns) == FIVE_COLUMNS
    assert bool(out["squeeze"].iloc[-1])
    assert out["kc_up"].iloc[-1] == pytest.approx(103.0)


def test_enrich_session_attaches_five_minute_values_only_when_complete():
    history = session_grid(random_minutes(PRIOR, 2), PRIOR)
    today = session_grid(random_minutes(SESSION, 3), SESSION)
    grid, five_today = enrich_session(today, history)
    everything = add_indicators(five_minute_bars(pd.concat([history, today], ignore_index=True)))
    assert five_today["ts"].min() == at(DAY, "09:30")
    first_today_bar = everything[everything["end"] == at(DAY, "09:35")].iloc[0]
    last_history_bar = everything[everything["end"] == at(PRIOR.day, "16:00")].iloc[0]
    assert bar_row(grid, DAY, "09:34")["atr5"] == pytest.approx(first_today_bar["atr14"])
    assert bar_row(grid, DAY, "09:33")["atr5"] == pytest.approx(last_history_bar["atr14"])
    assert (grid["decision_ts"] == grid["ts"] + pd.Timedelta(minutes=1)).all()


@pytest.mark.parametrize("cut", ["09:40", "10:17", "12:03", "15:31"])
def test_enrich_session_is_point_in_time(cut):
    history = session_grid(random_minutes(PRIOR, 4), PRIOR)
    minutes = random_minutes(SESSION, 5)
    base_grid, base_five = enrich_session(session_grid(minutes, SESSION), history)
    cut_ts = at(DAY, cut)
    rng = np.random.default_rng(9)
    later = minutes["ts"] >= cut_ts
    for column in ("open", "high", "low", "close"):
        minutes.loc[later, column] = minutes.loc[later, column] * rng.uniform(0.9, 1.1, int(later.sum()))
    minutes.loc[later, "high"] = minutes.loc[later, ["open", "high", "low", "close"]].max(axis=1)
    minutes.loc[later, "low"] = minutes.loc[later, ["open", "high", "low", "close"]].min(axis=1)
    minutes.loc[later, "volume"] = rng.integers(1, 10000, int(later.sum()))
    new_grid, new_five = enrich_session(session_grid(minutes, SESSION), history)
    known = base_grid["decision_ts"] <= cut_ts
    columns = ["vwap", "sigma", "atr5", "rsi14", "adx14"]
    pd.testing.assert_frame_equal(base_grid.loc[known, columns], new_grid.loc[known, columns])
    done = base_five["end"] <= cut_ts
    pd.testing.assert_frame_equal(base_five.loc[done].reset_index(drop=True), new_five.loc[new_five["end"] <= cut_ts].reset_index(drop=True))
