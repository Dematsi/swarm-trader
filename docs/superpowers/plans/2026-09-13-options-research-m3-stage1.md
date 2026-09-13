# Options Research M3 (Features, 9 Setups, Stage-1 Evaluation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate point-in-time signals for the 9 pre-registered intraday setups (long and short) on
the 12 underlyings over the stage-1 development period. Measure forward stock outcomes and report
which setup × direction pairs pass the spec §8.3 stage-1 criteria.

**Architecture:**
- **`features.py`**: per-session raw features.
  - A regular-hours 1-min grid, VWAP/σ, and 5-min bars with Wilder ATR/RSI/ADX, Bollinger and
    Keltner.
  - 5-min values are attached to a 1-min row only after the 5-min bar completes.
- **`levels.py`**: after-the-window levels.
  - Prior-day close/high/low, filtered pre-market high/low, opening-range volume history, and
    indicator warm-up history.
  - All split-adjusted to the signal day. It is the only feature module allowed to read the
    hindsight columns.
- **`setups/`**: detectors taking a `DayContext` and returning signal dicts.
- **`stage1.py`**: runs the detectors per ticker-day (resumable, per-symbol files), adds forward
  outcomes, and tags events and splits.
- **`evaluate.py`**: day-block bootstrap, year consistency and cost-aware break-even.
- **`ledger.py`**: records every evaluated configuration.
- **Reporting**: `reports.m3_report` plus CLI commands `stage1` and `report-m3`.

**Tech Stack:** Python 3.12 via uv; pandas 2.3, numpy 1.26, duckdb 1.5, pyarrow, exchange-calendars
(all installed). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-options-edge-research-design.md`. Read §5.1 (hindsight
rule, splits, pre-market volume filter), §5.2 (events), §5.6 (cost model), §6 (setups), §7.5
(cutoffs), §8 (stage 1), §9.1 (holdout), §9.3 (ledger) and §10 (tests).

## Global Constraints

- **Tooling:**
  - Run from the repo root `C:\Users\tsedi\swarm-trader-fork` with `~/.local/bin/uv`, in Git Bash.
  - Prefix commands with `PYTHONIOENCODING=utf-8` when output may contain non-ASCII.
  - Unit tests: `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py`.
- **Isolation:** `src/options_research/` must NOT import from root scripts, `src/agents`,
  `src/alpaca_integration.py` or `src/accounts.py`.
  - M3 makes no network calls, needs no Alpaca, FRED or DB access, and never reads `.env`.
- **Data access:** stock minutes are read only through `store.load_stock_minutes`.
  - `tests/options_research/test_data_access.py` enforces this. Only the allowlist edits named in
    Tasks 2 and 6 are permitted.
  - Hindsight columns (`bad_high`, `bad_low`, `high_clean`, `low_clean`) may be referenced only in
    `levels.py` among feature code.
  - Feature and setup code never imports `quality` or `print_checks`.
- **Holdout (spec §9.1):**
  - Stage-1 period is `config.STAGE1_DEV` = 2021-06-18 → 2025-12-31.
  - No signal, feature or return may be computed on dates ≥ 2026-01-02.
  - The only `holdout=True` read in M3 is the cost-calibration spot level in `evaluate.calibration_spots`
    (2026-08-21 → 2026-09-11 closes). It carries a comment naming the exception.
- **Timestamps:**
  - Bars are keyed by UTC **bar start** `ts`. A signal on the bar starting at `t` is known at
    **decision time `T = t + 1 min`**.
  - A 5-min bar is usable at `T` only when its `end ≤ T`.
  - All session windows are compared on `T` in `America/New_York`, inclusive at both ends.
- **Pre-registered setup parameters** are the exact values in spec §6. The table in "Pre-registered
  interpretations" below is binding. Changing any value means a new ledger configuration.
- **Tests:**
  - TDD, offline, synthetic fixtures.
  - Real-data checks are marked `@pytest.mark.integration` and skipped when the lake is absent.
- **Commits:**
  - Each commit ends with `Co-Authored-By: <your actual model name> <noreply@anthropic.com>`, then
    exactly `Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx`.
  - Never commit `data/`. Do not push.

## Pre-registered interpretations (binding; spec §6/§8 leave these open)

| Topic | Rule |
|---|---|
| Missing minutes | The RTH grid has one row per minute in [open, close). A minute with no trades repeats the last close for O/H/L/C with volume 0 (`filled=True`). Leading gaps use the first traded open. |
| Indicator history | 5-min indicators (ATR14 = ATR5, RSI14, ADX14, BB20/2, KC20/1.5×ATR20, EMA20 midline) run over the previous **5 sessions** plus today, regular hours only. Earlier sessions use clean high/low, drop bars whose clean value is empty, and are split-adjusted to the signal day. Today is raw. Days with fewer than 5 earlier sessions in the loaded range produce no signals. |
| Wilder smoothing | `ewm(alpha=1/n, adjust=False, min_periods=n)`. True range of the first bar is high − low. Bollinger σ uses `ddof=0`. |
| Pre-market high/low | Bars 04:00 ≤ ET < open with volume ≥ 100, using `high_clean`/`low_clean` (empty values ignored). Readable only at T ≥ 09:37 ET (`levels.assert_premarket_readable`). |
| Prior-day levels | Prior RTH close is the **raw** close of the prior session's last RTH bar. Prior RTH high/low is the max/min of clean high/low over its RTH bars. Both are multiplied by `adjustment_factors(prior)/adjustment_factors(day)`. |
| Gap | First grid row's open / adjusted prior close − 1. |
| OR volume history | OR volume of each of the previous 20 sessions × `adjustment_factors(day)/adjustment_factors(prior)`. The median needs all 20 present, otherwise the ORB signal is skipped. |
| Windows (decision time T) | ORB15 [09:46, 11:30]; ORB30 [10:01, 11:30]; GAP_GO [09:46, 11:30]; GAP_FILL [09:46, 11:00]; PDL_BREAK [09:46, 15:00]; others [10:00, 15:00]. Every end is capped at close − 60 min (half days). |
| "≥ 30 consecutive closes" | The 30 closes immediately **before** the trigger bar (the run may start at 09:30). VWAP_RECLAIM triggers when the preceding below-VWAP run is ≥ 30 and the bar closes ≥ VWAP + 0.1 × ATR5. Short mirrors. |
| SPY regime (VWAP_PULLBACK) | Up: SPY close > SPY VWAP and SPY VWAP(t) − SPY VWAP(t − 30 rows) > 0, same bar. Down mirrors with < and < 0. |
| MEANREV short mirror | ADX < 20, close ≥ VWAP + 2.5σ, RSI ≥ 75. |
| SQUEEZE | Consecutive squeeze count uses today's 5-min bars only; the 6 bars before the trigger bar must all be in squeeze. Decision time is the trigger bar's end. |
| Cooldown / max | VWAP_PULLBACK and MEANREV: candidates less than 30 min after the previous emitted signal (same setup, direction, day) are skipped; at most 2 per day. Every other setup: the first trigger per direction per day. |
| Invalidation record | `inval_kind` ∈ {`level`, `vwap_atr`, `kc_mid`}, `inval_side` ∈ {`below`, `above`} (invalid when a close is below/above), `inval_value` = price level, signed ATR multiple (e.g. −0.1), or 0.0 for `kc_mid`. ATR5 is frozen at the signal. |
| Forward returns | Entry = open of the 1-min bar starting at T. Exit at horizon h = open of the bar starting at T + h; if that is at or after the close, the last RTH close. Hard exit = §7.5 non-0DTE hard exit (close − 15 min). Return is signed by direction. MFE/MAE use highs/lows of bars [T, T + 60 min) within the session. |
| Break-even (cost-aware test) | NEAR DTE = calendar days to that week's Friday (the prior session if Friday is a holiday). `h_cal` = `CostModel.base_half_spread(symbol, dte, otm=0.0, premium=<ATM level-3 cell mid for that DTE bucket>, tod=T)`. Scaled to the signal price by `price / calibration_spot`, where the spot is the median RTH close 2026-08-21 → 2026-09-11. Fee per share = fees_per_side / 100. `be_frac = (2·h + 2·fee) / (0.5 · price)`. Pooled break-even = median over tickers of each ticker's median `be_frac`. Pass when mean `ret_60` ≥ 1.5 × pooled break-even. |
| Bootstrap | Resample trading days with replacement (10,000 resamples, seed 20260912); statistic = total return / total count of the resampled days; t = mean / std(bootstrap means, ddof=1). |
| Year consistency | Calendar years 2021–2025: pass when ≥ 4 years have mean `ret_60` > 0. |
| Event tags | `event_in_window`: a Tier "1"/"2" event with a `time_et` inside [T − 15 min, T + 70 min]. `earnings_reaction`: `earnings_amc` for the ticker on the previous session, or `earnings_bmo` on the day. `event_day` = any Tier 1/2 event that day, or `earnings_reaction`. |
| Split tag | `near_split`: the signal day is the split session, or the session before or after it, for that symbol. |
| Ledger | `reports/options_research/ledger.jsonl`, one JSON object per setup × direction evaluation. Skipped when an entry with the same (stage, setup, direction, config_hash, dataset_version) exists. Expected false passes = entries × 0.00135 (one-sided p at t = 3). |

## File Structure

```
src/options_research/
  features.py            (T1) grid, VWAP/σ, 5-min bars, indicators, enrich_session, split_by_day
  levels.py              (T2) DayLevels, session_summaries, day_levels, clean_grid, history_minutes
  setups/__init__.py     (T3, replaced in T4/T5) SETUPS registry, SETUP_PARAMS, detect_all
  setups/base.py         (T3) DayContext, SIGNAL_COLUMNS, windows, run lengths, cooldown, make_signal
  setups/orb.py          (T3) ORB15/ORB30
  setups/gaps_levels.py  (T3) GAP_GO, GAP_FILL, PDL_BREAK
  setups/vwap.py         (T4) VWAP_RECLAIM, VWAP_PULLBACK
  setups/mean_reversion.py (T4) MEANREV
  setups/squeeze.py      (T5) SQUEEZE
  stage1.py              (T6) forward_outcomes, tag_events, tag_splits, signals_for_symbol, run_stage1
  evaluate.py            (T7) bootstrap, break-even, evaluation tables, calibration_spots
  ledger.py              (T7) config hash, dataset version, append/read
  reports.py             (T8) m3_report
  cli.py                 (T8) stage1, report-m3
tests/options_research/
  setup_helpers.py       (T3) make_grid, make_five, make_ctx, assert_point_in_time
  test_features.py (T1) test_levels.py (T2) test_setups_levels.py (T3) test_setups_vwap.py (T4)
  test_setups_squeeze.py (T5) test_stage1.py (T6) test_evaluate.py + test_ledger.py (T7)
  test_reports_cli.py (T8, append) test_integration_stage1.py (T8)
```

---
### Task 1: Point-in-time intraday features (`features.py`)

**Files:**
- Create: `src/options_research/features.py`
- Test: `tests/options_research/test_features.py`

**Interfaces:**
- Consumes: `market_calendar.Session` (fields `day`, `open_et`, `close_et`) and `config.TZ_ET`.
- Produces:
  - Column lists:
    - `GRID_COLUMNS = ["ts", "open", "high", "low", "close", "volume", "filled"]`
    - `FIVE_COLUMNS = ["ts", "end", "open", "high", "low", "close", "volume", "atr14", "rsi14", "adx14", "bb_up", "bb_lo", "kc_mid", "kc_up", "kc_lo", "squeeze"]`
  - `split_by_day(minutes: pd.DataFrame) -> dict[date, pd.DataFrame]`, keyed by ET date.
  - `session_grid(minutes: pd.DataFrame, session: Session) -> pd.DataFrame` with GRID_COLUMNS; `ts` is UTC, ns resolution.
  - `add_vwap(grid) -> pd.DataFrame`, which adds `vwap` and `sigma`.
  - `five_minute_bars(grid) -> pd.DataFrame` with columns ts, end, open, high, low, close, volume.
  - Indicators:
    - `wilder(series, n) -> pd.Series`
    - `true_range(bars) -> pd.Series`
    - `rsi(close, n) -> pd.Series`
    - `adx(bars, n) -> pd.Series`
  - `add_indicators(five) -> pd.DataFrame` with FIVE_COLUMNS.
  - `enrich_session(grid, history: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]`. It returns:
    - today's grid plus `decision_ts`, `vwap`, `sigma`, `atr5`, `rsi14`, `adx14`
    - today's 5-min bars with FIVE_COLUMNS

- [ ] **Step 1: Write the failing tests**

Create `tests/options_research/test_features.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/options_research/test_features.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'src.options_research.features'`.

- [ ] **Step 3: Implement**

Create `src/options_research/features.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/options_research/test_features.py -q`
Expected: all pass.

If `merge_asof` raises about incompatible keys, make both `decision_ts` and `five_end`
`datetime64[ns, UTC]` with `.dt.as_unit("ns")`. Do not loosen any assertion.

Run: `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py`
Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add src/options_research/features.py tests/options_research/test_features.py
git commit -F- <<'EOF'
feat(options_research): point-in-time intraday features (grid, VWAP/sigma, 5-min Wilder indicators)

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 2: After-the-window levels (`levels.py`)

**Files:**
- Create: `src/options_research/levels.py`
- Modify: `tests/options_research/test_data_access.py` (add `"levels.py"` to `HINDSIGHT_COLUMN_USERS`; no other allowlist change)
- Test: `tests/options_research/test_levels.py`

**Interfaces:**
- **Consumes:**
  - `features.split_by_day`, `features.session_grid`, `features.GRID_COLUMNS` (Task 1)
  - `corporate_actions.adjustment_factors(splits, symbol, days: pd.Series) -> pd.Series`: a price on `days[i]` × factor expresses it in latest terms
  - `market_calendar.Session`
- **Produces:**
  - `DayLevels(day, prior_close, prior_high, prior_low, premarket_high, premarket_low, or_volume_median: dict[int, float | None])`
  - `assert_premarket_readable(decision_et: datetime) -> None`, which raises `ValueError` before 09:37 ET
  - `session_summaries(by_day: dict[date, pd.DataFrame], sessions: list[Session]) -> pd.DataFrame`, indexed by day with columns `rth_close, rth_high, rth_low, pm_high, pm_low, or15_volume, or30_volume` (unadjusted)
  - `day_levels(summaries, splits, symbol, sessions, index, lookback=20) -> DayLevels`
  - `clean_grid(day_minutes: pd.DataFrame | None, session) -> pd.DataFrame` (GRID_COLUMNS)
  - `history_minutes(clean_grids: dict[date, pd.DataFrame], splits, symbol, sessions, index, n_sessions=5) -> pd.DataFrame | None`
  - Input minute frames are `store.load_stock_minutes(..., clean=True)` rows: they include `high_clean`/`low_clean`.

- [ ] **Step 1: Write the failing tests**

Create `tests/options_research/test_levels.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/options_research/test_levels.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'src.options_research.levels'`.

- [ ] **Step 3: Implement**

Create `src/options_research/levels.py`:

```python
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
```

In `tests/options_research/test_data_access.py`, change the `HINDSIGHT_COLUMN_USERS` line to:

```python
HINDSIGHT_COLUMN_USERS = {"quality.py", "stocks.py", "store.py", "print_checks.py", "reports.py", "levels.py"}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/options_research/test_levels.py tests/options_research/test_data_access.py -q`
Expected: all pass.

Run: `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py`
Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add src/options_research/levels.py tests/options_research/test_levels.py tests/options_research/test_data_access.py
git commit -F- <<'EOF'
feat(options_research): split-adjusted after-the-window levels; levels.py is the only feature reader of clean columns

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 3: Setup plumbing, point-in-time test helper, ORB and gap/level setups

**Files:**
- Create: `src/options_research/setups/base.py`
- Create: `src/options_research/setups/orb.py`
- Create: `src/options_research/setups/gaps_levels.py`
- Create: `src/options_research/setups/__init__.py`
- Create: `tests/options_research/setup_helpers.py`
- Test: `tests/options_research/test_setups_levels.py`

**Interfaces:**
- **Consumes:**
  - From Task 1: `features.FIVE_COLUMNS`.
  - From Task 2: `levels.DayLevels`, `levels.assert_premarket_readable`.
  - From `market_calendar`: `Session`, `get_session`.
  - Grid columns from `features.enrich_session`: `ts, decision_ts, open, high, low, close, volume, filled, vwap, sigma, atr5, rsi14, adx14`.
- **Produces, in `setups/base.py`:**
  - Direction constants: `LONG = "long"`, `SHORT = "short"`.
  - `SIGNAL_COLUMNS = ["symbol", "day", "setup", "direction", "bar_ts", "decision_ts", "price", "atr5", "inval_kind", "inval_side", "inval_value", "trigger"]`.
  - `DayContext(symbol, session, grid, five, levels, spy_grid=None)`, a frozen dataclass.
  - Window and trigger helpers:
    - `window_mask(decision_ts: pd.Series, session, start: time, end: time) -> np.ndarray`
    - `previous_run(flags) -> np.ndarray`
    - `first_true(mask) -> int | None`
    - `with_cooldown(mask, decision_ts) -> list[int]`
  - Signal builders:
    - `opening_range(ctx, minutes) -> tuple[float, float, float] | None` (high, low, volume)
    - `make_signal(...) -> dict`
    - `grid_signal(ctx, setup, direction, i, inval_kind, inval_side, inval_value, trigger) -> dict`
- **Produces, detectors:**
  - `setups/orb.py`: `detect_orb(ctx, minutes)`, `PARAMS`.
  - `setups/gaps_levels.py`: `detect_gap_go`, `detect_gap_fill`, `detect_pdl_break`, `gap(ctx)`, and `GAP_GO_PARAMS`, `GAP_FILL_PARAMS`, `PDL_PARAMS`.
  - `setups/__init__.py`: `SETUPS: dict[str, Callable]`, `SETUP_PARAMS: dict[str, dict]`, `detect_all(ctx) -> list[dict]`. Tasks 4 and 5 replace this file with the full 9-setup version.
- **Produces, test helper** `tests/options_research/setup_helpers.py`:
  - Fixtures: `DAY`, `SESSION`, `at(hhmm)`, `idx(hhmm)`, `five_idx(hhmm)`
  - Builders: `make_grid(...)`, `make_five(...)`, `make_ctx(...)`
  - Check: `assert_point_in_time(detect, ctx) -> list[dict]`

- [ ] **Step 1: Write the test helper and the failing tests**

Create `tests/options_research/setup_helpers.py`:

```python
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
```

Create `tests/options_research/test_setups_levels.py`:

```python
from datetime import date, time

import numpy as np
import pandas as pd

from src.options_research.levels import DayLevels
from src.options_research.market_calendar import get_session
from src.options_research.setups import SETUPS, detect_all
from src.options_research.setups.base import SIGNAL_COLUMNS, previous_run, window_mask, with_cooldown
from src.options_research.setups.gaps_levels import detect_gap_fill, detect_gap_go, detect_pdl_break
from src.options_research.setups.orb import detect_orb
from tests.options_research.setup_helpers import DAY, assert_point_in_time, at, make_ctx, make_grid, set_bar


def summary(signals):
    return [(s["setup"], s["direction"], s["decision_ts"], round(s["inval_value"], 6), s["inval_side"]) for s in signals]


def test_window_mask_is_inclusive_and_capped_one_hour_before_a_half_day_close():
    half = get_session(date(2025, 11, 28))
    decisions = pd.Series(pd.to_datetime(["2025-11-28 10:00", "2025-11-28 12:00", "2025-11-28 12:01"]).tz_localize("America/New_York").tz_convert("UTC"))
    assert window_mask(decisions, half, time(10, 0), time(15, 0)).tolist() == [True, True, False]


def test_previous_run_counts_the_run_before_each_bar():
    assert previous_run(np.array([True, True, False, True])).tolist() == [0, 1, 2, 0]


def test_with_cooldown_skips_within_30_minutes_and_caps_at_two():
    decisions = pd.Series([at(t) for t in ("10:00", "10:10", "10:31", "11:05", "12:00")])
    assert with_cooldown(np.ones(5, dtype=bool), decisions) == [0, 2]


def orb_levels(median=10000.0):
    return DayLevels(day=DAY, or_volume_median={15: median, 30: median})


def test_orb_long_on_first_close_above_the_range():
    grid = make_grid()
    set_bar(grid, "10:05", 100.5)
    ctx = make_ctx(grid, levels=orb_levels())
    assert summary(assert_point_in_time(lambda c: detect_orb(c, 15), ctx)) == [("ORB15", "long", at("10:06"), 100.0, "below")]
    assert summary(assert_point_in_time(lambda c: detect_orb(c, 30), ctx)) == [("ORB30", "long", at("10:06"), 100.0, "below")]


def test_orb_short_and_filters():
    grid = make_grid()
    set_bar(grid, "10:20", 99.4)
    assert summary(detect_orb(make_ctx(grid, levels=orb_levels()), 15)) == [("ORB15", "short", at("10:21"), 100.0, "above")]
    assert detect_orb(make_ctx(grid, levels=orb_levels(13000.0)), 15) == []
    assert detect_orb(make_ctx(grid, levels=DayLevels(day=DAY, or_volume_median={15: None, 30: None})), 15) == []
    late = make_grid()
    set_bar(late, "11:40", 100.5)
    assert detect_orb(make_ctx(late, levels=orb_levels()), 15) == []


def test_gap_up_go_long_and_fill_short():
    grid = make_grid()
    set_bar(grid, "10:05", 100.5)
    set_bar(grid, "10:30", 99.5)
    ctx = make_ctx(grid, levels=DayLevels(day=DAY, prior_close=99.0, premarket_high=100.3, premarket_low=99.8))
    assert summary(assert_point_in_time(detect_gap_go, ctx)) == [("GAP_GO", "long", at("10:06"), 99.95, "below")]
    assert summary(assert_point_in_time(detect_gap_fill, ctx)) == [("GAP_FILL", "short", at("10:31"), 100.05, "above")]


def test_gap_down_go_short_and_fill_long():
    grid = make_grid()
    set_bar(grid, "10:05", 99.5)
    set_bar(grid, "10:40", 100.5)
    ctx = make_ctx(grid, levels=DayLevels(day=DAY, prior_close=101.0, premarket_high=100.4, premarket_low=99.7))
    assert summary(detect_gap_go(ctx)) == [("GAP_GO", "short", at("10:06"), 100.05, "above")]
    assert summary(detect_gap_fill(ctx)) == [("GAP_FILL", "long", at("10:41"), 99.95, "below")]


def test_small_gap_and_late_fill_produce_nothing():
    grid = make_grid()
    set_bar(grid, "10:05", 100.5)
    assert detect_gap_go(make_ctx(grid, levels=DayLevels(day=DAY, prior_close=99.9, premarket_high=100.3))) == []
    late = make_grid()
    set_bar(late, "11:10", 99.5)
    assert detect_gap_fill(make_ctx(late, levels=DayLevels(day=DAY, prior_close=99.0))) == []


def test_prior_day_level_breaks_need_the_atr_buffer():
    grid = make_grid()
    set_bar(grid, "11:00", 100.34)
    set_bar(grid, "12:00", 100.4)
    set_bar(grid, "13:00", 98.9)
    ctx = make_ctx(grid, levels=DayLevels(day=DAY, prior_high=100.3, prior_low=99.0))
    assert summary(assert_point_in_time(detect_pdl_break, ctx)) == [
        ("PDL_BREAK", "long", at("12:01"), 100.2, "below"),
        ("PDL_BREAK", "short", at("13:01"), 99.1, "above"),
    ]


def test_registry_and_signal_shape():
    assert set(SETUPS) == {"ORB15", "ORB30", "GAP_GO", "GAP_FILL", "PDL_BREAK"}
    assert detect_all(make_ctx()) == []
    grid = make_grid()
    set_bar(grid, "10:05", 100.5)
    signals = detect_all(make_ctx(grid, levels=orb_levels()))
    assert signals and all(list(s) == SIGNAL_COLUMNS for s in signals)
    assert all(s["symbol"] == "TEST" and s["day"] == DAY and s["bar_ts"] == s["decision_ts"] - pd.Timedelta(minutes=1) for s in signals)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/options_research/test_setups_levels.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'src.options_research.setups'`.

- [ ] **Step 3: Implement**

Create `src/options_research/setups/base.py`:

```python
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
```

Create `src/options_research/setups/orb.py`:

```python
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
```

Create `src/options_research/setups/gaps_levels.py`:

```python
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
GAP_GO_PARAMS = {"gap": GAP_THRESHOLD, "window": "09:46-11:30", "trigger": "close beyond filtered pre-market high/low", "invalidation": "close vs 09:30-09:45 opposite extreme"}
GAP_FILL_PARAMS = {"gap": GAP_THRESHOLD, "window": "09:46-11:00", "trigger": "close beyond 09:30-09:45 extreme toward prior close", "invalidation": "close vs 09:30-09:45 opposite extreme"}
PDL_PARAMS = {"window": "09:46-15:00", "trigger_atr": PDL_TRIGGER_ATR, "invalidation_atr": PDL_INVALIDATION_ATR, "levels": "prior RTH high/low, adjusted, clean"}


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
```

Create `src/options_research/setups/__init__.py`:

```python
"""Stage-1 setup registry (spec §6): setup ID -> detector(DayContext) -> signal dicts (both directions)."""

from __future__ import annotations

from collections.abc import Callable

from src.options_research.setups import gaps_levels, orb
from src.options_research.setups.base import DayContext

SETUPS: dict[str, Callable[[DayContext], list[dict]]] = {
    "ORB15": lambda ctx: orb.detect_orb(ctx, 15),
    "ORB30": lambda ctx: orb.detect_orb(ctx, 30),
    "GAP_GO": gaps_levels.detect_gap_go,
    "GAP_FILL": gaps_levels.detect_gap_fill,
    "PDL_BREAK": gaps_levels.detect_pdl_break,
}

SETUP_PARAMS: dict[str, dict] = {
    "ORB15": {**orb.PARAMS, "or_minutes": 15},
    "ORB30": {**orb.PARAMS, "or_minutes": 30},
    "GAP_GO": gaps_levels.GAP_GO_PARAMS,
    "GAP_FILL": gaps_levels.GAP_FILL_PARAMS,
    "PDL_BREAK": gaps_levels.PDL_PARAMS,
}


def detect_all(ctx: DayContext) -> list[dict]:
    return [signal for detect in SETUPS.values() for signal in detect(ctx)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/options_research/test_setups_levels.py tests/options_research/test_data_access.py -q`
Expected: all pass.

Run: `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py`
Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add src/options_research/setups tests/options_research/setup_helpers.py tests/options_research/test_setups_levels.py
git commit -F- <<'EOF'
feat(options_research): setup plumbing, point-in-time check, ORB15/ORB30, GAP_GO, GAP_FILL, PDL_BREAK

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 4: VWAP_RECLAIM, VWAP_PULLBACK and MEANREV

**Files:**
- Create: `src/options_research/setups/vwap.py`
- Create: `src/options_research/setups/mean_reversion.py`
- Modify: `src/options_research/setups/__init__.py` (replace the whole file with the version below)
- Test: `tests/options_research/test_setups_vwap.py`

**Interfaces:**
- **Consumes (Task 3, `setups/base.py`):**
  - `LONG`, `SHORT`, `DEFAULT_WINDOW_START`, `DEFAULT_WINDOW_END`
  - `DayContext`
  - `window_mask`, `previous_run`, `first_true`, `with_cooldown`, `grid_signal`
- **Consumes (test helpers):**
  - `tests/options_research/setup_helpers.py`: `make_grid`, `make_ctx`, `set_bar`, `idx`, `at`, `assert_point_in_time`
- **Consumes (grid columns):**
  - `close`, `low`, `high`, `vwap`, `sigma`, `atr5`, `rsi14`, `adx14`, `decision_ts`
  - `ctx.spy_grid` columns: `ts`, `close`, `vwap`
- **Produces:**
  - `setups/vwap.py`: `detect_vwap_reclaim(ctx)`, `detect_vwap_pullback(ctx)`, `spy_regime(ctx) -> tuple[np.ndarray, np.ndarray]`, `RECLAIM_PARAMS`, `PULLBACK_PARAMS`
  - `setups/mean_reversion.py`: `detect_meanrev(ctx)`, `PARAMS`
  - `SETUPS` / `SETUP_PARAMS` with 8 IDs

- [ ] **Step 1: Write the failing tests**

Create `tests/options_research/test_setups_vwap.py`:

```python
import numpy as np

from src.options_research.setups import SETUPS
from src.options_research.setups.mean_reversion import detect_meanrev
from src.options_research.setups.vwap import detect_vwap_pullback, detect_vwap_reclaim, spy_regime
from tests.options_research.setup_helpers import assert_point_in_time, at, idx, make_ctx, make_grid, set_bar


def summary(signals):
    return [(s["setup"], s["direction"], s["decision_ts"], round(s["inval_value"], 6), s["inval_side"]) for s in signals]


def test_vwap_reclaim_long_after_30_closes_below():
    closes = np.full(390, 100.5)
    closes[: idx("10:15")] = 99.5
    closes[idx("10:15")] = 100.2
    ctx = make_ctx(make_grid(close=closes))
    assert summary(assert_point_in_time(detect_vwap_reclaim, ctx)) == [("VWAP_RECLAIM", "long", at("10:16"), -0.1, "below")]


def test_vwap_reclaim_run_resets_on_a_close_at_or_above_vwap():
    closes = np.full(390, 100.5)
    closes[: idx("10:10")] = 99.5
    closes[idx("10:10")] = 100.05
    closes[idx("10:11"): idx("10:15")] = 99.5
    closes[idx("10:15")] = 100.2
    assert detect_vwap_reclaim(make_ctx(make_grid(close=closes))) == []


def test_vwap_reclaim_short_mirror():
    closes = np.full(390, 99.5)
    closes[: idx("10:15")] = 100.5
    closes[idx("10:15")] = 99.8
    ctx = make_ctx(make_grid(close=closes))
    assert summary(assert_point_in_time(detect_vwap_reclaim, ctx)) == [("VWAP_RECLAIM", "short", at("10:16"), 0.1, "above")]


def spy(close, slope):
    return make_grid(close=close, vwap=100.0 + slope * np.arange(390))


def test_spy_regime_needs_price_and_slope():
    up, down = spy_regime(make_ctx(spy_grid=spy(101.0, 0.001)))
    assert not up[: idx("10:00")].all() and up[idx("10:00"):].all() and not down.any()
    up, down = spy_regime(make_ctx(spy_grid=spy(101.0, 0.0)))
    assert not up.any() and not down.any()
    up, down = spy_regime(make_ctx())
    assert not up.any() and not down.any()


def test_vwap_pullback_long_with_cooldown_and_daily_cap():
    grid = make_grid(close=100.5)
    for t in ("10:30", "10:45", "11:10", "12:00"):
        set_bar(grid, t, 100.2, low=100.05)
    ctx = make_ctx(grid, spy_grid=spy(101.0, 0.001))
    assert summary(assert_point_in_time(detect_vwap_pullback, ctx)) == [
        ("VWAP_PULLBACK", "long", at("10:31"), -0.1, "below"),
        ("VWAP_PULLBACK", "long", at("11:11"), -0.1, "below"),
    ]
    assert detect_vwap_pullback(make_ctx(grid, spy_grid=spy(101.0, 0.0))) == []


def test_vwap_pullback_short_mirror():
    grid = make_grid(close=99.5)
    set_bar(grid, "10:30", 99.8, high=99.95)
    ctx = make_ctx(grid, spy_grid=spy(99.0, -0.001))
    assert summary(assert_point_in_time(detect_vwap_pullback, ctx)) == [("VWAP_PULLBACK", "short", at("10:31"), 0.1, "above")]


def test_meanrev_long_short_adx_filter_cooldown_and_cap():
    grid = make_grid(close=100.0, sigma=0.4, adx14=15.0)
    for t, close, rsi in (("11:00", 98.9, 20.0), ("11:10", 98.8, 22.0), ("11:40", 98.7, 21.0), ("12:30", 98.6, 20.0), ("13:00", 101.1, 80.0)):
        set_bar(grid, t, close)
        grid.loc[idx(t), "rsi14"] = rsi
    ctx = make_ctx(grid)
    assert summary(assert_point_in_time(detect_meanrev, ctx)) == [
        ("MEANREV", "long", at("11:01"), 98.75, "below"),
        ("MEANREV", "long", at("11:41"), 98.55, "below"),
        ("MEANREV", "short", at("13:01"), 101.25, "above"),
    ]
    trending = grid.copy()
    trending["adx14"] = 25.0
    assert detect_meanrev(make_ctx(trending)) == []


def test_registry_has_eight_setups_so_far():
    assert set(SETUPS) == {"ORB15", "ORB30", "GAP_GO", "GAP_FILL", "PDL_BREAK", "VWAP_RECLAIM", "VWAP_PULLBACK", "MEANREV"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/options_research/test_setups_vwap.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'src.options_research.setups.mean_reversion'`.

- [ ] **Step 3: Implement**

Create `src/options_research/setups/vwap.py`:

```python
"""VWAP_RECLAIM and VWAP_PULLBACK (spec §6)."""

from __future__ import annotations

import numpy as np

from src.options_research.setups.base import (
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    LONG,
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
RECLAIM_PARAMS = {"run_bars": RUN_BARS, "atr_offset": ATR_OFFSET, "window": "10:00-15:00", "invalidation": "close vs VWAP -/+ 0.1 ATR5"}
PULLBACK_PARAMS = {"run_bars": RUN_BARS, "atr_offset": ATR_OFFSET, "spy_slope_bars": SPY_SLOPE_BARS, "cooldown_min": 30, "max_per_day": 2, "window": "10:00-15:00", "invalidation": "close vs VWAP -/+ 0.1 ATR5"}


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
```

Create `src/options_research/setups/mean_reversion.py`:

```python
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
```

Replace `src/options_research/setups/__init__.py` with:

```python
"""Stage-1 setup registry (spec §6): setup ID -> detector(DayContext) -> signal dicts (both directions)."""

from __future__ import annotations

from collections.abc import Callable

from src.options_research.setups import gaps_levels, mean_reversion, orb, vwap
from src.options_research.setups.base import DayContext

SETUPS: dict[str, Callable[[DayContext], list[dict]]] = {
    "ORB15": lambda ctx: orb.detect_orb(ctx, 15),
    "ORB30": lambda ctx: orb.detect_orb(ctx, 30),
    "VWAP_RECLAIM": vwap.detect_vwap_reclaim,
    "VWAP_PULLBACK": vwap.detect_vwap_pullback,
    "MEANREV": mean_reversion.detect_meanrev,
    "GAP_GO": gaps_levels.detect_gap_go,
    "GAP_FILL": gaps_levels.detect_gap_fill,
    "PDL_BREAK": gaps_levels.detect_pdl_break,
}

SETUP_PARAMS: dict[str, dict] = {
    "ORB15": {**orb.PARAMS, "or_minutes": 15},
    "ORB30": {**orb.PARAMS, "or_minutes": 30},
    "VWAP_RECLAIM": vwap.RECLAIM_PARAMS,
    "VWAP_PULLBACK": vwap.PULLBACK_PARAMS,
    "MEANREV": mean_reversion.PARAMS,
    "GAP_GO": gaps_levels.GAP_GO_PARAMS,
    "GAP_FILL": gaps_levels.GAP_FILL_PARAMS,
    "PDL_BREAK": gaps_levels.PDL_PARAMS,
}


def detect_all(ctx: DayContext) -> list[dict]:
    return [signal for detect in SETUPS.values() for signal in detect(ctx)]
```

In `tests/options_research/test_setups_levels.py`, the registry assertion from Task 3 no longer holds. Change its first line to:

```python
    assert {"ORB15", "ORB30", "GAP_GO", "GAP_FILL", "PDL_BREAK"} <= set(SETUPS)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/options_research/test_setups_vwap.py tests/options_research/test_setups_levels.py -q`
Expected: all pass.

Run: `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py`
Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add src/options_research/setups tests/options_research/test_setups_vwap.py tests/options_research/test_setups_levels.py
git commit -F- <<'EOF'
feat(options_research): VWAP_RECLAIM, VWAP_PULLBACK (SPY regime) and MEANREV setups

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 5: SQUEEZE and the complete 9-setup registry

**Files:**
- Create: `src/options_research/setups/squeeze.py`
- Modify: `src/options_research/setups/__init__.py` (replace the whole file with the version below)
- Modify: `tests/options_research/test_setups_vwap.py` (registry assertion becomes a subset check)
- Test: `tests/options_research/test_setups_squeeze.py`

**Interfaces:**
- Consumes: `setups/base.py` (`make_signal`, `previous_run`, `first_true`, `window_mask`, `DEFAULT_WINDOW_START/END`, `LONG`, `SHORT`, `DayContext`).
- Consumes: `ctx.five` columns `ts, end, close, atr14, bb_up, bb_lo, kc_mid, squeeze` (Task 1 `FIVE_COLUMNS`).
- Consumes: test helpers `make_five`, `five_idx`, `make_ctx`, `at`, `assert_point_in_time`.
- Produces: `detect_squeeze(ctx)`, `squeeze.PARAMS`.
- Produces: final `SETUPS` / `SETUP_PARAMS` with exactly 9 IDs: `ORB15, ORB30, VWAP_RECLAIM, VWAP_PULLBACK, MEANREV, GAP_GO, GAP_FILL, PDL_BREAK, SQUEEZE`.
- Produces: `detect_all(ctx)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/options_research/test_setups_squeeze.py`:

```python
from src.options_research.setups import SETUP_PARAMS, SETUPS, detect_all
from src.options_research.setups.squeeze import detect_squeeze
from tests.options_research.setup_helpers import assert_point_in_time, at, five_idx, make_ctx, make_five


def summary(signals):
    return [(s["setup"], s["direction"], s["decision_ts"], s["bar_ts"], s["inval_kind"], s["inval_side"]) for s in signals]


def squeezed(first: str, last: str):
    five = make_five()
    five.loc[five_idx(first): five_idx(last), "squeeze"] = True
    return five


def test_squeeze_long_after_six_squeeze_bars_decides_at_bar_end():
    five = squeezed("09:30", "09:55")
    five.loc[five_idx("10:00"), "close"] = 101.5
    ctx = make_ctx(five=five)
    assert summary(assert_point_in_time(detect_squeeze, ctx)) == [("SQUEEZE", "long", at("10:05"), at("10:00"), "kc_mid", "below")]


def test_squeeze_short_mirror():
    five = squeezed("11:00", "11:25")
    five.loc[five_idx("11:30"), "close"] = 98.5
    ctx = make_ctx(five=five)
    assert summary(assert_point_in_time(detect_squeeze, ctx)) == [("SQUEEZE", "short", at("11:35"), at("11:30"), "kc_mid", "above")]


def test_squeeze_needs_six_bars_and_the_window():
    five = squeezed("09:35", "09:55")
    five.loc[five_idx("10:00"), "close"] = 101.5
    assert detect_squeeze(make_ctx(five=five)) == []
    late = squeezed("14:30", "14:55")
    late.loc[five_idx("15:00"), "close"] = 101.5
    assert detect_squeeze(make_ctx(five=late)) == []
    assert detect_squeeze(make_ctx()) == []


def test_registry_is_complete():
    assert set(SETUPS) == {"ORB15", "ORB30", "VWAP_RECLAIM", "VWAP_PULLBACK", "MEANREV", "GAP_GO", "GAP_FILL", "PDL_BREAK", "SQUEEZE"}
    assert set(SETUP_PARAMS) == set(SETUPS)
    assert detect_all(make_ctx()) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/options_research/test_setups_squeeze.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'src.options_research.setups.squeeze'`.

- [ ] **Step 3: Implement**

Create `src/options_research/setups/squeeze.py`:

```python
"""SQUEEZE breakout on 5-min bars (spec §6). Decision time is the trigger bar's end."""

from __future__ import annotations

from src.options_research.setups.base import DEFAULT_WINDOW_END, DEFAULT_WINDOW_START, LONG, SHORT, DayContext, first_true, make_signal, previous_run, window_mask

MIN_SQUEEZE_BARS = 6
PARAMS = {
    "bollinger": "20 bars, 2 sigma (ddof=0)",
    "keltner": "EMA20 +/- 1.5 x Wilder ATR20",
    "min_squeeze_bars": MIN_SQUEEZE_BARS,
    "squeeze_count": "today's 5-min bars only",
    "window": "10:00-15:00 on 5-min bar end",
    "invalidation": "5-min close vs KC midline",
}


def detect_squeeze(ctx: DayContext) -> list[dict]:
    five = ctx.five
    if five.empty:
        return []
    window = window_mask(five["end"], ctx.session, DEFAULT_WINDOW_START, DEFAULT_WINDOW_END)
    ready = previous_run(five["squeeze"].to_numpy(dtype=bool)) >= MIN_SQUEEZE_BARS
    close = five["close"].to_numpy(dtype=float)
    candidates = (
        (LONG, close > five["bb_up"].to_numpy(dtype=float), "below", "5m close>bb_up after 6 squeeze bars"),
        (SHORT, close < five["bb_lo"].to_numpy(dtype=float), "above", "5m close<bb_lo after 6 squeeze bars"),
    )
    signals = []
    for direction, hit, side, trigger in candidates:
        i = first_true(window & ready & hit)
        if i is not None:
            row = five.iloc[i]
            signals.append(make_signal(ctx, "SQUEEZE", direction, row["ts"], row["end"], row["close"], row["atr14"], "kc_mid", side, 0.0, trigger))
    return signals
```

Replace `src/options_research/setups/__init__.py` with:

```python
"""Stage-1 setup registry (spec §6): setup ID -> detector(DayContext) -> signal dicts (both directions)."""

from __future__ import annotations

from collections.abc import Callable

from src.options_research.setups import gaps_levels, mean_reversion, orb, squeeze, vwap
from src.options_research.setups.base import DayContext

SETUPS: dict[str, Callable[[DayContext], list[dict]]] = {
    "ORB15": lambda ctx: orb.detect_orb(ctx, 15),
    "ORB30": lambda ctx: orb.detect_orb(ctx, 30),
    "VWAP_RECLAIM": vwap.detect_vwap_reclaim,
    "VWAP_PULLBACK": vwap.detect_vwap_pullback,
    "MEANREV": mean_reversion.detect_meanrev,
    "GAP_GO": gaps_levels.detect_gap_go,
    "GAP_FILL": gaps_levels.detect_gap_fill,
    "PDL_BREAK": gaps_levels.detect_pdl_break,
    "SQUEEZE": squeeze.detect_squeeze,
}

SETUP_PARAMS: dict[str, dict] = {
    "ORB15": {**orb.PARAMS, "or_minutes": 15},
    "ORB30": {**orb.PARAMS, "or_minutes": 30},
    "VWAP_RECLAIM": vwap.RECLAIM_PARAMS,
    "VWAP_PULLBACK": vwap.PULLBACK_PARAMS,
    "MEANREV": mean_reversion.PARAMS,
    "GAP_GO": gaps_levels.GAP_GO_PARAMS,
    "GAP_FILL": gaps_levels.GAP_FILL_PARAMS,
    "PDL_BREAK": gaps_levels.PDL_PARAMS,
    "SQUEEZE": squeeze.PARAMS,
}


def detect_all(ctx: DayContext) -> list[dict]:
    return [signal for detect in SETUPS.values() for signal in detect(ctx)]
```

In `tests/options_research/test_setups_vwap.py`, change the body of `test_registry_has_eight_setups_so_far` to:

```python
    assert {"ORB15", "ORB30", "GAP_GO", "GAP_FILL", "PDL_BREAK", "VWAP_RECLAIM", "VWAP_PULLBACK", "MEANREV"} <= set(SETUPS)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/options_research/test_setups_squeeze.py tests/options_research/test_setups_vwap.py tests/options_research/test_setups_levels.py -q`
Expected: all pass.

Run: `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py`
Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add src/options_research/setups tests/options_research/test_setups_squeeze.py tests/options_research/test_setups_vwap.py
git commit -F- <<'EOF'
feat(options_research): SQUEEZE setup; registry complete with the 9 pre-registered setups

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 6: Stage-1 pipeline — outcomes, event/split tags, resumable per-symbol run (`stage1.py`)

**Files:**
- Create: `src/options_research/stage1.py`
- Modify: `tests/options_research/test_data_access.py` (add `"stage1.py"` to `PARQUET_READERS`; no other allowlist change)
- Test: `tests/options_research/test_stage1.py`

**Interfaces:**
- **Consumes:**
  - `features.split_by_day`, `session_grid`, `add_vwap`, `enrich_session`.
  - `levels.session_summaries`, `day_levels`, `clean_grid`, `history_minutes`.
  - `setups.detect_all`; `setups.base.SIGNAL_COLUMNS`, `DayContext`, `LONG`.
  - `store.load_stock_minutes(symbols, start, end, holdout=False, root=None, clean=False)`.
  - `corporate_actions.load_splits(root)`.
  - `events_sources.load_events(root)`, with columns `date, time_et, type, tier, source, ticker`. Tier values are `"1"`, `"2"`, `"market"` and `"earnings"`; `time_et` is `"HH:MM"` or None.
  - `market_calendar.sessions_between`, `entry_exit_cutoffs`, `ET`.
- **Produces:**
  - Column lists:
    - `OUTCOME_COLUMNS = ["entry_price", "ret_30", "ret_60", "ret_hard", "mfe_60", "mae_60"]`
    - `TAG_COLUMNS = ["day_events", "earnings_reaction", "event_day", "event_in_window", "near_split"]`
    - `STAGE1_COLUMNS = SIGNAL_COLUMNS + OUTCOME_COLUMNS + TAG_COLUMNS`
  - Transforms:
    - `forward_outcomes(signals, grid, session) -> pd.DataFrame`
    - `tag_events(signals, events, sessions) -> pd.DataFrame`
    - `tag_splits(signals, splits, sessions) -> pd.DataFrame`
    - `signals_for_symbol(symbol, minutes, spy_minutes, sessions, splits) -> pd.DataFrame`
  - Runs:
    - `run_stage1(symbols=UNIVERSE, start=STAGE1_DEV[0], end=STAGE1_DEV[1], workers=4, overwrite=False, root=None) -> dict`
    - `combine_stage1(symbols, start, end, root=None) -> pd.DataFrame`
  - Storage:
    - `load_signals(root=None) -> pd.DataFrame`
    - `signals_path(root=None) -> Path`, i.e. `<lake>/signals/stage1/signals.parquet`
    - `symbol_signals_path(symbol, root=None) -> Path`

- [ ] **Step 1: Write the failing tests**

Create `tests/options_research/test_stage1.py`:

```python
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.options_research.corporate_actions import SPLIT_COLUMNS
from src.options_research.events_rules import EVENT_COLUMNS
from src.options_research.market_calendar import get_session, sessions_between
from src.options_research.stage1 import (
    STAGE1_COLUMNS,
    forward_outcomes,
    load_signals,
    run_stage1,
    signals_for_symbol,
    symbol_signals_path,
    tag_events,
    tag_splits,
)
from src.options_research.store import HoldoutAccessError
from src.options_research.stocks import STOCK_COLUMNS
from tests.options_research.setup_helpers import DAY, SESSION, at, make_grid

FRI = date(2025, 5, 30)
START = date(2025, 5, 22)
NO_SPLITS = pd.DataFrame(columns=SPLIT_COLUMNS)


def signal(direction, decision, symbol="TEST", day=DAY, setup="PDL_BREAK"):
    return {"symbol": symbol, "day": day, "setup": setup, "direction": direction, "decision_ts": decision}


def test_forward_outcomes_signed_returns_and_excursions():
    closes = 100 + 0.01 * np.arange(390)
    grid = make_grid(close=closes)
    signals = pd.DataFrame([signal("long", at("10:00")), signal("short", at("10:00")), signal("long", at("15:30")), signal("long", at("16:00"))])
    out = forward_outcomes(signals, grid, SESSION)
    long, short, late, closed = (out.iloc[i] for i in range(4))
    assert long["entry_price"] == pytest.approx(100.30)
    assert long["ret_30"] == pytest.approx(100.60 / 100.30 - 1)
    assert long["ret_60"] == pytest.approx(100.90 / 100.30 - 1)
    assert long["ret_hard"] == pytest.approx(103.75 / 100.30 - 1)
    assert long["mfe_60"] == pytest.approx(100.94 / 100.30 - 1)
    assert long["mae_60"] == pytest.approx(100.25 / 100.30 - 1)
    assert short["ret_60"] == pytest.approx(-(100.90 / 100.30 - 1))
    assert short["mfe_60"] == pytest.approx(1 - 100.25 / 100.30)
    assert short["mae_60"] == pytest.approx(1 - 100.94 / 100.30)
    assert late["ret_60"] == pytest.approx(103.89 / 103.60 - 1)
    assert closed[["entry_price", "ret_60"]].isna().all()


def test_tag_events_windows_earnings_and_day_events():
    events = pd.DataFrame(
        [
            {"date": DAY, "time_et": "10:00", "type": "ism_manufacturing", "tier": "2", "source": "rule", "ticker": None},
            {"date": DAY, "time_et": "08:30", "type": "cpi", "tier": "1", "source": "fred", "ticker": None},
            {"date": DAY, "time_et": None, "type": "opex", "tier": "market", "source": "rule", "ticker": None},
            {"date": DAY, "time_et": None, "type": "earnings_amc", "tier": "earnings", "source": "yfinance", "ticker": "OTHER"},
            {"date": FRI, "time_et": None, "type": "earnings_amc", "tier": "earnings", "source": "yfinance", "ticker": "TEST"},
        ],
        columns=EVENT_COLUMNS,
    )
    sessions = [get_session(FRI), SESSION]
    signals = pd.DataFrame([signal("long", at("09:50")), signal("long", at("11:15")), signal("long", at("11:15"), day=FRI)])
    out = tag_events(signals, events, sessions)
    assert out["event_in_window"].tolist() == [True, False, False]
    assert out["day_events"].tolist() == ["cpi,ism_manufacturing,opex", "cpi,ism_manufacturing,opex", "earnings_amc"]
    assert out["earnings_reaction"].tolist() == [True, True, False]
    assert out["event_day"].tolist() == [True, True, False]


def test_tag_splits_marks_the_split_session_and_its_neighbours():
    sessions = sessions_between(date(2025, 5, 29), date(2025, 6, 3))
    splits = pd.DataFrame([{"symbol": "TEST", "day": FRI, "ratio": 2.0, "factor": 0.5}], columns=SPLIT_COLUMNS)
    days = [s.day for s in sessions]
    signals = pd.DataFrame([signal("long", at("10:00"), day=d) for d in days] + [signal("long", at("10:00"), symbol="OTHER", day=FRI)])
    assert tag_splits(signals, splits, sessions)["near_split"].tolist() == [True, True, True, False, False]


def synthetic_minutes(symbol, sessions, breakout_day=None):
    rows = []
    for session in sessions:
        ts = pd.date_range(session.open_et, session.close_et, freq="1min", inclusive="left").tz_convert("UTC")
        close = np.full(len(ts), 100.0)
        if session.day == breakout_day:
            close[150:] = 101.0
        rows.append(pd.DataFrame({
            "symbol": symbol, "ts": ts, "open": close, "high": close + 0.05, "low": close - 0.05, "close": close, "volume": 1000, "transactions": 10,
            "bad_high": False, "bad_low": False, "high_clean": close + 0.05, "low_clean": close - 0.05, "source": "zip",
        }))
    return pd.concat(rows, ignore_index=True)[STOCK_COLUMNS]


def test_signals_for_symbol_wires_levels_features_setups_and_outcomes():
    sessions = sessions_between(START, DAY)
    minutes = synthetic_minutes("TEST", sessions, breakout_day=DAY)
    spy = synthetic_minutes("SPY", sessions)
    out = signals_for_symbol("TEST", minutes, spy, sessions, NO_SPLITS)
    assert set(out["day"]) == {DAY}
    pdl = out[(out["setup"] == "PDL_BREAK") & (out["direction"] == "long")].iloc[0]
    assert pdl["decision_ts"] == at("12:01")
    assert pdl["entry_price"] == pytest.approx(101.0)
    assert pdl["ret_60"] == pytest.approx(0.0)


def write_lake(root, sessions):
    for symbol, breakout in (("NVDA", DAY), ("SPY", None)):
        minutes = synthetic_minutes(symbol, sessions, breakout_day=breakout)
        for session in sessions:
            day_rows = minutes[minutes["ts"].dt.tz_convert("America/New_York").dt.date == session.day]
            path = root / "stock_1m" / symbol / str(session.day.year) / f"{session.day.isoformat()}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            day_rows.to_parquet(path, index=False)
    (root / "calendar").mkdir(parents=True)
    pd.DataFrame(columns=EVENT_COLUMNS).astype(object).to_parquet(root / "calendar" / "events.parquet", index=False)
    (root / "corporate_actions").mkdir(parents=True)
    pd.DataFrame(columns=SPLIT_COLUMNS).astype({"ratio": float, "factor": float}).to_parquet(root / "corporate_actions" / "splits.parquet", index=False)


def test_run_stage1_writes_resumable_symbol_files_and_tagged_signals(tmp_path):
    write_lake(tmp_path, sessions_between(START, DAY))
    first = run_stage1(["NVDA"], START, DAY, workers=1, root=tmp_path)
    assert first["computed"] == ["NVDA"] and first["signals"] > 0
    assert symbol_signals_path("NVDA", tmp_path).exists()
    signals = load_signals(tmp_path)
    assert list(signals.columns) == STAGE1_COLUMNS
    assert set(signals["day"]) == {DAY}
    assert not signals["near_split"].any() and not signals["event_in_window"].any()
    second = run_stage1(["NVDA"], START, DAY, workers=1, root=tmp_path)
    assert second["computed"] == [] and second["skipped"] == ["NVDA"]


def test_run_stage1_refuses_the_holdout(tmp_path):
    write_lake(tmp_path, sessions_between(START, DAY))
    with pytest.raises(HoldoutAccessError):
        run_stage1(["NVDA"], START, date(2026, 1, 5), workers=1, root=tmp_path, overwrite=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/options_research/test_stage1.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'src.options_research.stage1'`.

- [ ] **Step 3: Implement**

Create `src/options_research/stage1.py`:

```python
"""Stage-1 signal generation and forward stock outcomes (spec §6, §8).

Per symbol and session, the pipeline goes:
- build today's raw grid and features plus the split-adjusted after-window levels
- run every setup
- attach forward returns measured from the open of the bar starting at decision time

Per-symbol results are cached so an interrupted run resumes. The combined file adds event and split
tags. Only `store.load_stock_minutes` reads stock minutes, so the holdout guard applies.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, time
from pathlib import Path

import numpy as np
import pandas as pd

from src.options_research.config import STAGE1_DEV, UNIVERSE, lake_root
from src.options_research.corporate_actions import load_splits
from src.options_research.events_sources import load_events
from src.options_research.features import add_vwap, enrich_session, session_grid, split_by_day
from src.options_research.levels import clean_grid, day_levels, history_minutes, session_summaries
from src.options_research.market_calendar import ET, Session, entry_exit_cutoffs, sessions_between
from src.options_research.setups import detect_all
from src.options_research.setups.base import LONG, SIGNAL_COLUMNS, DayContext
from src.options_research.store import load_stock_minutes

HORIZONS = (30, 60)
EXCURSION_MINUTES = 60
OUTCOME_COLUMNS = ["entry_price", "ret_30", "ret_60", "ret_hard", "mfe_60", "mae_60"]
TAG_COLUMNS = ["day_events", "earnings_reaction", "event_day", "event_in_window", "near_split"]
STAGE1_COLUMNS = SIGNAL_COLUMNS + OUTCOME_COLUMNS + TAG_COLUMNS
INTRADAY_TIERS = {"1", "2"}
EVENT_BEFORE = pd.Timedelta(minutes=15)
EVENT_AFTER = pd.Timedelta(minutes=70)


def stage1_dir(root: Path | None = None) -> Path:
    return (root or lake_root()) / "signals" / "stage1"


def symbol_signals_path(symbol: str, root: Path | None = None) -> Path:
    return stage1_dir(root) / f"{symbol}.parquet"


def signals_path(root: Path | None = None) -> Path:
    return stage1_dir(root) / "signals.parquet"


def _write_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def forward_outcomes(signals: pd.DataFrame, grid: pd.DataFrame, session: Session) -> pd.DataFrame:
    """Signed forward returns from the open of the bar starting at T (spec §8.1); MFE/MAE over [T, T+60)."""
    out = signals.copy()
    position = pd.Series(np.arange(len(grid)), index=grid["ts"])
    opens, highs, lows = (grid[c].to_numpy(dtype=float) for c in ("open", "high", "low"))
    last_close = float(grid["close"].iloc[-1])
    hard_exit = pd.Timestamp(entry_exit_cutoffs(session.day, is_0dte=False)[1]).tz_convert("UTC")

    def exit_price(ts: pd.Timestamp) -> float:
        j = position.get(ts)
        return opens[j] if j is not None else last_close

    rows = []
    for decision, direction in zip(out["decision_ts"], out["direction"]):
        start = position.get(decision)
        if start is None:
            rows.append([np.nan] * len(OUTCOME_COLUMNS))
            continue
        entry = opens[start]
        sign = 1.0 if direction == LONG else -1.0
        values = [entry] + [sign * (exit_price(decision + pd.Timedelta(minutes=h)) / entry - 1.0) for h in HORIZONS]
        values.append(sign * (exit_price(hard_exit) / entry - 1.0) if hard_exit > decision else np.nan)
        stop = min(start + EXCURSION_MINUTES, len(grid))
        high, low = highs[start:stop].max(), lows[start:stop].min()
        values += [high / entry - 1.0, low / entry - 1.0] if sign > 0 else [1.0 - low / entry, 1.0 - high / entry]
        rows.append(values)
    out[OUTCOME_COLUMNS] = pd.DataFrame(rows, columns=OUTCOME_COLUMNS, index=out.index)
    return out


def tag_events(signals: pd.DataFrame, events: pd.DataFrame, sessions: list[Session]) -> pd.DataFrame:
    """Event tags per signal (spec §8.6)."""
    out = signals.copy()
    previous = {sessions[i].day: sessions[i - 1].day for i in range(1, len(sessions))}
    empty = events.iloc[0:0]
    by_day = {day: frame for day, frame in events.groupby("date")}
    day_events, reaction, event_day, in_window = [], [], [], []
    for symbol, day, decision in zip(out["symbol"], out["day"], out["decision_ts"]):
        today = by_day.get(day, empty)
        relevant = today[today["ticker"].isna() | (today["ticker"] == symbol)]
        day_events.append(",".join(sorted(set(relevant["type"]))))
        prior = by_day.get(previous.get(day), empty)
        reported = bool(((prior["type"] == "earnings_amc") & (prior["ticker"] == symbol)).any() or ((today["type"] == "earnings_bmo") & (today["ticker"] == symbol)).any())
        reaction.append(reported)
        tiered = today[today["tier"].isin(INTRADAY_TIERS)]
        event_day.append(bool(len(tiered)) or reported)
        released = [pd.Timestamp(datetime.combine(day, time.fromisoformat(t), tzinfo=ET)) for t in tiered["time_et"].dropna()]
        in_window.append(any(decision - EVENT_BEFORE <= r <= decision + EVENT_AFTER for r in released))
    out["day_events"] = day_events
    out["earnings_reaction"] = reaction
    out["event_day"] = event_day
    out["event_in_window"] = in_window
    return out


def tag_splits(signals: pd.DataFrame, splits: pd.DataFrame, sessions: list[Session]) -> pd.DataFrame:
    """`near_split`: the signal day is a split session for that symbol, or the session before or after it (spec §8.5)."""
    order = {s.day: i for i, s in enumerate(sessions)}
    near = set()
    for symbol, split_day in zip(splits["symbol"], splits["day"]):
        i = order.get(split_day)
        if i is None:
            continue
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(sessions):
                near.add((symbol, sessions[j].day))
    out = signals.copy()
    out["near_split"] = [(symbol, day) in near for symbol, day in zip(out["symbol"], out["day"])]
    return out


def signals_for_symbol(symbol: str, minutes: pd.DataFrame, spy_minutes: pd.DataFrame, sessions: list[Session], splits: pd.DataFrame) -> pd.DataFrame:
    """Signals with outcomes for one symbol. `minutes` must come from `load_stock_minutes(..., clean=True)`."""
    by_day = split_by_day(minutes)
    spy_by_day = by_day if symbol == "SPY" else split_by_day(spy_minutes)
    summaries = session_summaries(by_day, sessions)
    clean_grids = {s.day: clean_grid(by_day.get(s.day), s) for s in sessions}
    frames = []
    for index, session in enumerate(sessions):
        today = by_day.get(session.day)
        history = history_minutes(clean_grids, splits, symbol, sessions, index)
        if today is None or history is None:
            continue
        grid = session_grid(today, session)
        if grid.empty:
            continue
        grid, five = enrich_session(grid, history)
        if symbol == "SPY":
            spy_grid = grid
        else:
            spy_raw = session_grid(spy_by_day[session.day], session) if session.day in spy_by_day else pd.DataFrame()
            spy_grid = None if spy_raw.empty else add_vwap(spy_raw)
        ctx = DayContext(symbol, session, grid, five, day_levels(summaries, splits, symbol, sessions, index), spy_grid)
        found = detect_all(ctx)
        if found:
            frames.append(forward_outcomes(pd.DataFrame(found, columns=SIGNAL_COLUMNS), grid, session))
    if not frames:
        return pd.DataFrame(columns=SIGNAL_COLUMNS + OUTCOME_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def _symbol_job(job: tuple) -> str:
    symbol, start, end, root = job
    minutes = load_stock_minutes([symbol], start, end, root=root, clean=True)
    spy = minutes if symbol == "SPY" else load_stock_minutes(["SPY"], start, end, root=root)
    frame = signals_for_symbol(symbol, minutes, spy, sessions_between(start, end), load_splits(root))
    _write_atomic(frame, symbol_signals_path(symbol, root))
    return symbol


def combine_stage1(symbols, start: date, end: date, root: Path | None = None) -> pd.DataFrame:
    frames = [pd.read_parquet(symbol_signals_path(s, root)) for s in symbols if symbol_signals_path(s, root).exists()]
    frames = [f for f in frames if not f.empty]
    signals = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SIGNAL_COLUMNS + OUTCOME_COLUMNS)
    signals["day"] = pd.to_datetime(signals["day"]).dt.date
    sessions = sessions_between(start, end)
    signals = tag_splits(tag_events(signals, load_events(root), sessions), load_splits(root), sessions)
    signals = signals.sort_values(["symbol", "decision_ts", "setup", "direction"]).reset_index(drop=True)[STAGE1_COLUMNS]
    _write_atomic(signals, signals_path(root))
    return signals


def run_stage1(symbols=UNIVERSE, start: date = STAGE1_DEV[0], end: date = STAGE1_DEV[1], workers: int = 4, overwrite: bool = False, root: Path | None = None) -> dict:
    symbols = list(symbols)
    todo = [s for s in symbols if overwrite or not symbol_signals_path(s, root).exists()]
    jobs = [(s, start, end, root) for s in todo]
    if workers <= 1 or len(jobs) <= 1:
        computed = [_symbol_job(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            computed = list(pool.map(_symbol_job, jobs))
    combined = combine_stage1(symbols, start, end, root)
    return {"computed": computed, "skipped": [s for s in symbols if s not in todo], "signals": int(len(combined))}


def load_signals(root: Path | None = None) -> pd.DataFrame:
    frame = pd.read_parquet(signals_path(root))
    frame["day"] = pd.to_datetime(frame["day"]).dt.date
    return frame
```

In `tests/options_research/test_data_access.py`, change the `PARQUET_READERS` line to:

```python
PARQUET_READERS = {"store.py", "reports.py", "stocks_alpaca.py", "corporate_actions.py", "costs.py", "events_sources.py", "print_checks.py", "stage1.py"}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/options_research/test_stage1.py tests/options_research/test_data_access.py -q`
Expected: all pass.

Run: `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py`
Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add src/options_research/stage1.py tests/options_research/test_stage1.py tests/options_research/test_data_access.py
git commit -F- <<'EOF'
feat(options_research): stage-1 pipeline with forward outcomes, event/split tags and resumable per-symbol runs

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 7: Stage-1 evaluation and the multiple-testing ledger (`evaluate.py`, `ledger.py`)

**Files:**
- Create: `src/options_research/evaluate.py`
- Create: `src/options_research/ledger.py`
- Test: `tests/options_research/test_evaluate.py`
- Test: `tests/options_research/test_ledger.py`

**Interfaces:**
- **Consumes:**
  - `costs.CostModel(table, fees_per_side=0.05)`, with `.table`, `.fees_per_side`, and `.base_half_spread(underlying, dte, otm, premium, tod) -> (h, level)`.
  - From `costs`: `COST_KEYS`, `dte_bucket`, `tod_bucket`.
  - From `market_calendar`: `get_session`, `previous_session_on_or_before`.
  - From `store`: `load_stock_minutes`, `stock_minute_files`.
  - From `config`: `REPO_ROOT`, `DATA_FREEZE`, `UNIVERSE`, `lake_root`, `reports_dir`.
  - Stage-1 signal columns from Task 6: `symbol`, `day`, `setup`, `direction`, `decision_ts`, `price`, `ret_30`, `ret_60`, `ret_hard`, `mfe_60`, `mae_60`, `event_day`.
- **Produces, in `evaluate.py`:**
  - Constants: `PRIMARY`, `EVAL_PARAMS`, `EVALUATION_COLUMNS`, `COST_CALIBRATION`.
  - Statistics:
    - `day_block_bootstrap(values, days, resamples=10000, seed=20260912) -> tuple[float, float, float]` returning (mean, se, t).
    - `evaluate_stage1(signals) -> pd.DataFrame` with EVALUATION_COLUMNS.
  - Break-even:
    - `near_expiry_dte(day) -> int`
    - `atm_mid(table, symbol, bucket) -> float`
    - `break_even_frac(model, symbol, day, decision_time, price, calibration_spot) -> float`
    - `add_break_even(signals, model, spots) -> pd.DataFrame`, which adds `be_frac`.
  - Report tables:
    - `horizon_table(signals)`
    - `event_table(signals)`
    - `per_ticker_means(signals)`
    - `per_ticker_break_even(signals)`
  - Cost-model inputs: `calibration_spots(symbols, root=None) -> dict[str, float]`.
- **Produces, in `ledger.py`:**
  - Constants: `ONE_SIDED_P_AT_T3 = 0.00135`, `LEDGER_KEY`.
  - Location and read/write:
    - `ledger_path(directory=None) -> Path`
    - `read_ledger(path=None) -> pd.DataFrame`
    - `append_entries(entries, path=None) -> int`, which returns the number actually appended.
  - Identity:
    - `config_hash(config: dict) -> str`
    - `git_commit(repo=REPO_ROOT) -> str`
    - `dataset_version(start, end, root=None, symbols=UNIVERSE) -> str`
  - Entries:
    - `expected_false_passes(n_tests) -> float`
    - `stage1_entries(evaluation, setup_params, eval_params, commit, dataset, period, now=None) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

Create `tests/options_research/test_evaluate.py`:

```python
from datetime import date, time

import numpy as np
import pandas as pd
import pytest

from src.options_research.costs import COST_KEYS, CostModel
from src.options_research.evaluate import (
    EVALUATION_COLUMNS,
    add_break_even,
    break_even_frac,
    calibration_spots,
    day_block_bootstrap,
    evaluate_stage1,
    event_table,
    horizon_table,
    near_expiry_dte,
    per_ticker_break_even,
)
from src.options_research.market_calendar import sessions_between
from src.options_research.stocks import STOCK_COLUMNS


def test_bootstrap_mean_and_day_blocks():
    days = [date(2024, 1, 2)] * 2 + [date(2024, 1, 3)] + [date(2024, 1, 4)] * 3
    values = [0.01, 0.03, 0.02, -0.01, 0.01, 0.02]
    mean, se, t = day_block_bootstrap(values, days)
    assert mean == pytest.approx(0.08 / 6)
    assert se > 0 and t == pytest.approx(mean / se)
    assert day_block_bootstrap(values, days) == (mean, se, t)


def test_bootstrap_does_not_reward_duplicate_signals_within_a_day():
    days = list(sessions_between(date(2024, 1, 2), date(2024, 3, 29)))
    rng = np.random.default_rng(1)
    base = rng.normal(0.001, 0.01, len(days))
    once = day_block_bootstrap(base, [s.day for s in days])
    tenfold = day_block_bootstrap(np.repeat(base, 10), np.repeat([s.day for s in days], 10))
    assert tenfold[0] == pytest.approx(once[0]) and tenfold[1] == pytest.approx(once[1])


def test_near_expiry_dte_counts_to_friday_or_the_holiday_thursday():
    assert near_expiry_dte(date(2025, 6, 2)) == 4
    assert near_expiry_dte(date(2025, 5, 30)) == 0
    assert near_expiry_dte(date(2025, 4, 16)) == 1
    assert near_expiry_dte(date(2025, 4, 17)) == 0


def cost_model():
    rows = [
        {"underlying": "TEST", "dte_bucket": "3-7", "moneyness": "ATM", "premium": None, "tod_bucket": None, "n": 100, "half_spread": 0.10, "mid": 2.0},
        {"underlying": "TEST", "dte_bucket": "3-7", "moneyness": "ATM", "premium": "1-3", "tod_bucket": "mid", "n": 50, "half_spread": 0.08, "mid": 2.0},
    ]
    return CostModel(pd.DataFrame(rows, columns=COST_KEYS + ["n", "half_spread", "mid"]))


def test_break_even_scales_the_half_spread_to_the_signal_price():
    be = break_even_frac(cost_model(), "TEST", date(2025, 6, 2), time(11, 0), 200.0, 100.0)
    assert be == pytest.approx((2 * 0.16 + 2 * 0.0005) / (0.5 * 200.0))
    signals = pd.DataFrame({"symbol": ["TEST"], "day": [date(2025, 6, 2)], "decision_ts": [pd.Timestamp("2025-06-02 11:00", tz="America/New_York").tz_convert("UTC")], "price": [200.0]})
    assert add_break_even(signals, cost_model(), {"TEST": 100.0})["be_frac"].iloc[0] == pytest.approx(be)


def spread_days(count):
    days = [s.day for s in sessions_between(date(2021, 7, 1), date(2025, 12, 31))]
    return [days[i] for i in np.linspace(0, len(days) - 1, count).astype(int)]


def synthetic_signals():
    rows = []
    for i, day in enumerate(spread_days(400)):
        rows.append({"setup": "A", "direction": "long", "symbol": "SPY" if i % 2 else "QQQ", "day": day, "ret_60": 0.002 + 0.001 * np.sin(i), "be_frac": 0.001})
    for i, day in enumerate(spread_days(100)):
        rows.append({"setup": "B", "direction": "short", "symbol": "SPY", "day": day, "ret_60": 0.002 + 0.001 * np.sin(i), "be_frac": 0.001})
    for i, day in enumerate(spread_days(400)):
        rows.append({"setup": "C", "direction": "long", "symbol": "SPY", "day": day, "ret_60": 0.0005 + 0.0001 * np.sin(i), "be_frac": 0.001})
    frame = pd.DataFrame(rows)
    for column in ("ret_30", "ret_hard"):
        frame[column] = frame["ret_60"]
    frame["mfe_60"], frame["mae_60"], frame["event_day"] = 0.004, -0.002, [i % 5 == 0 for i in range(len(frame))]
    return frame


def test_evaluate_stage1_applies_every_criterion():
    result = evaluate_stage1(synthetic_signals()).set_index("setup")
    assert list(evaluate_stage1(synthetic_signals()).columns) == EVALUATION_COLUMNS
    a, b, c = result.loc["A"], result.loc["B"], result.loc["C"]
    assert a["n"] == 400 and a["positive_years"] == 5 and a["t"] > 3 and a["cost_ratio"] == pytest.approx(a["mean_ret_60"] / 0.001)
    assert bool(a["passed"])
    assert not bool(b["pass_n"]) and not bool(b["passed"])
    assert bool(c["pass_t"]) and not bool(c["pass_cost"]) and not bool(c["passed"])


def test_descriptive_tables():
    signals = synthetic_signals()
    horizons = horizon_table(signals)
    assert {"n", "mean_ret_30", "mean_ret_60", "mean_ret_hard", "median_mfe_60", "median_mae_60"} <= set(horizons.columns)
    events = event_table(signals)
    assert {"n_all", "mean_all", "t_all", "n_ex_event", "mean_ex_event", "t_ex_event"} <= set(events.columns)
    assert per_ticker_break_even(signals).loc["SPY"] == pytest.approx(10.0)


def test_calibration_spots_read_regular_hours_closes_in_the_calibration_window(tmp_path):
    day = date(2026, 8, 24)
    rows = []
    for hhmm, close in (("08:00", 500.0), ("10:00", 100.0), ("11:00", 102.0), ("12:00", 104.0)):
        ts = pd.Timestamp(f"{day} {hhmm}", tz="America/New_York").tz_convert("UTC")
        rows.append({"symbol": "NVDA", "ts": ts, "open": close, "high": close, "low": close, "close": close, "volume": 100, "transactions": 1, "bad_high": False, "bad_low": False, "high_clean": close, "low_clean": close, "source": "alpaca"})
    path = tmp_path / "stock_1m" / "NVDA" / "2026" / f"{day.isoformat()}.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(rows, columns=STOCK_COLUMNS).to_parquet(path, index=False)
    assert calibration_spots(["NVDA"], root=tmp_path) == {"NVDA": pytest.approx(102.0)}
```

Create `tests/options_research/test_ledger.py`:

```python
import re
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from src.options_research.ledger import (
    append_entries,
    config_hash,
    dataset_version,
    expected_false_passes,
    git_commit,
    read_ledger,
    stage1_entries,
)


def test_config_hash_is_order_independent():
    assert config_hash({"a": 1, "b": [1, 2]}) == config_hash({"b": [1, 2], "a": 1})
    assert config_hash({"a": 1}) != config_hash({"a": 2})


def entry(dataset="d1", setup="ORB15"):
    return {"stage": "stage1", "setup": setup, "direction": "long", "config_hash": "h1", "dataset_version": dataset, "n": 1}


def test_append_entries_skips_repeats_of_the_same_configuration(tmp_path):
    path = tmp_path / "ledger.jsonl"
    assert append_entries([entry(), entry(setup="ORB30")], path) == 2
    assert append_entries([entry(), entry(setup="ORB30")], path) == 0
    assert append_entries([entry(dataset="d2")], path) == 1
    assert len(read_ledger(path)) == 3
    assert read_ledger(tmp_path / "missing.jsonl").empty


def test_expected_false_passes():
    assert expected_false_passes(18) == pytest.approx(18 * 0.00135)


def test_dataset_version_tracks_lake_inputs(tmp_path):
    day_file = tmp_path / "stock_1m" / "SPY" / "2024" / "2024-01-02.parquet"
    day_file.parent.mkdir(parents=True)
    day_file.write_bytes(b"abc")
    (tmp_path / "calendar").mkdir()
    (tmp_path / "calendar" / "events.parquet").write_bytes(b"v1")
    first = dataset_version(date(2024, 1, 2), date(2024, 1, 2), root=tmp_path, symbols=["SPY"])
    assert first == dataset_version(date(2024, 1, 2), date(2024, 1, 2), root=tmp_path, symbols=["SPY"])
    (tmp_path / "calendar" / "events.parquet").write_bytes(b"v2")
    assert dataset_version(date(2024, 1, 2), date(2024, 1, 2), root=tmp_path, symbols=["SPY"]) != first


def test_git_commit_is_a_sha():
    assert re.fullmatch(r"[0-9a-f]{40}(-dirty)?", git_commit())


def test_stage1_entries_hash_setup_and_evaluation_parameters():
    evaluation = pd.DataFrame([{"setup": "ORB15", "direction": "long", "n": 350, "mean_ret_60": 0.001, "t": 3.2, "passed": True}])
    now = datetime(2026, 9, 13, tzinfo=timezone.utc)
    [row] = stage1_entries(evaluation, {"ORB15": {"x": 1}}, {"t_min": 3.0}, "abc", "d1", "2021-06-18..2025-12-31", now)
    assert row["config_hash"] == config_hash({"setup": "ORB15", "direction": "long", "setup_params": {"x": 1}, "evaluation": {"t_min": 3.0}})
    assert row["stage"] == "stage1" and row["timestamp"] == now.isoformat() and row["passed"] is True and row["n"] == 350
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/options_research/test_evaluate.py tests/options_research/test_ledger.py -q`
Expected: collection errors `ModuleNotFoundError` for `src.options_research.evaluate` and `src.options_research.ledger`.

- [ ] **Step 3: Implement**

Create `src/options_research/evaluate.py`:

```python
"""Stage-1 evaluation (spec §8.3): day-block bootstrap t-stat, year consistency, cost-aware break-even, signal count."""

from __future__ import annotations

from datetime import date, time, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from src.options_research.config import DATA_FREEZE, TZ_ET
from src.options_research.costs import CostModel, dte_bucket, tod_bucket
from src.options_research.market_calendar import get_session, previous_session_on_or_before
from src.options_research.store import load_stock_minutes

PRIMARY = "ret_60"
T_MIN = 3.0
MIN_SIGNALS = 300
MIN_POSITIVE_YEARS = 4
COST_MULTIPLE = 1.5
RESAMPLES = 10_000
DESCRIPTIVE_RESAMPLES = 2_000
SEED = 20260912
ATM_DELTA = 0.5
COST_CALIBRATION = (date(2026, 8, 21), DATA_FREEZE)
EVAL_PARAMS = {
    "primary": PRIMARY, "t_min": T_MIN, "min_signals": MIN_SIGNALS, "min_positive_years": MIN_POSITIVE_YEARS, "cost_multiple": COST_MULTIPLE,
    "resamples": RESAMPLES, "seed": SEED, "atm_delta": ATM_DELTA, "near_expiry": "that week's Friday (prior session if holiday)",
    "cost_scaling": "ATM level-3 mid premium; h x price / median RTH close 2026-08-21..2026-09-11", "fees_per_contract_side": 0.05,
}
EVALUATION_COLUMNS = ["setup", "direction", "n", "mean_ret_60", "se", "t", "positive_years", "pooled_break_even", "cost_ratio", "pass_t", "pass_years", "pass_cost", "pass_n", "passed"]


def day_block_bootstrap(values, days, resamples: int = RESAMPLES, seed: int = SEED) -> tuple[float, float, float]:
    """Mean per signal, with SE and t from resampling whole trading days with replacement."""
    frame = pd.DataFrame({"value": np.asarray(values, dtype=float), "day": np.asarray(days)}).dropna(subset=["value"])
    if frame.empty:
        return float("nan"), float("nan"), float("nan")
    grouped = frame.groupby("day")["value"].agg(["sum", "count"])
    sums, counts = grouped["sum"].to_numpy(dtype=float), grouped["count"].to_numpy(dtype=float)
    mean = float(sums.sum() / counts.sum())
    if len(sums) < 2:
        return mean, float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    boots = np.empty(resamples)
    for start in range(0, resamples, 500):
        size = min(500, resamples - start)
        picks = rng.integers(0, len(sums), size=(size, len(sums)))
        boots[start:start + size] = sums[picks].sum(axis=1) / counts[picks].sum(axis=1)
    se = float(boots.std(ddof=1))
    return mean, se, (mean / se if se > 0 else float("nan"))


@lru_cache(maxsize=None)
def near_expiry_dte(day: date) -> int:
    """Calendar days to that week's Friday expiration, or to the prior session when Friday is a holiday."""
    friday = day + timedelta(days=4 - day.weekday())
    if get_session(friday) is None:
        friday = previous_session_on_or_before(friday)
    return max(0, (friday - day).days)


def atm_mid(table: pd.DataFrame, symbol: str, bucket: str) -> float:
    cell = table[(table["underlying"] == symbol) & (table["dte_bucket"] == bucket) & (table["moneyness"] == "ATM") & table["premium"].isna() & table["tod_bucket"].isna()]
    if cell.empty:
        raise KeyError(f"no ATM level-3 cost cell for {symbol} DTE bucket {bucket}")
    return float(cell["mid"].iloc[0])


def _break_even(h_cal: float, price: float, calibration_spot: float, fees_per_side: float) -> float:
    half_spread = h_cal * price / calibration_spot
    fee_per_share = fees_per_side / 100.0
    return (2.0 * half_spread + 2.0 * fee_per_share) / (ATM_DELTA * price)


def break_even_frac(model: CostModel, symbol: str, day: date, decision_time: time, price: float, calibration_spot: float) -> float:
    """Stock move (fraction of price) that pays the round-trip spread and fees of an ATM NEAR option (spec §8.3)."""
    dte = near_expiry_dte(day)
    h_cal, _ = model.base_half_spread(symbol, dte, 0.0, atm_mid(model.table, symbol, dte_bucket(dte)), decision_time)
    return _break_even(h_cal, price, calibration_spot, model.fees_per_side)


def add_break_even(signals: pd.DataFrame, model: CostModel, spots: dict[str, float]) -> pd.DataFrame:
    out = signals.copy()
    clock = pd.to_datetime(out["decision_ts"], utc=True).dt.tz_convert(TZ_ET).dt.time
    cache: dict[tuple, float] = {}
    values = []
    for symbol, day, decided, price in zip(out["symbol"], out["day"], clock, out["price"]):
        dte = near_expiry_dte(day)
        key = (symbol, dte, tod_bucket(decided))
        if key not in cache:
            cache[key] = model.base_half_spread(symbol, dte, 0.0, atm_mid(model.table, symbol, dte_bucket(dte)), decided)[0]
        values.append(_break_even(cache[key], float(price), spots[symbol], model.fees_per_side))
    out["be_frac"] = values
    return out


def evaluate_stage1(signals: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (setup, direction), group in signals.groupby(["setup", "direction"], sort=True):
        valid = group[group[PRIMARY].notna()]
        mean, se, t = day_block_bootstrap(valid[PRIMARY], valid["day"])
        years = valid.groupby(pd.to_datetime(valid["day"]).dt.year)[PRIMARY].mean()
        positive_years = int((years > 0).sum())
        pooled = float(valid.groupby("symbol")["be_frac"].median().median()) if len(valid) else float("nan")
        ratio = mean / pooled if pooled > 0 else float("nan")
        checks = {"pass_t": bool(t >= T_MIN), "pass_years": positive_years >= MIN_POSITIVE_YEARS, "pass_cost": bool(ratio >= COST_MULTIPLE), "pass_n": len(valid) >= MIN_SIGNALS}
        rows.append({"setup": setup, "direction": direction, "n": int(len(valid)), "mean_ret_60": mean, "se": se, "t": t, "positive_years": positive_years, "pooled_break_even": pooled, "cost_ratio": ratio, **checks, "passed": all(checks.values())})
    return pd.DataFrame(rows, columns=EVALUATION_COLUMNS)


def horizon_table(signals: pd.DataFrame) -> pd.DataFrame:
    grouped = signals.groupby(["setup", "direction"], sort=True)
    return pd.DataFrame({
        "n": grouped.size(),
        "mean_ret_30": grouped["ret_30"].mean(),
        "mean_ret_60": grouped["ret_60"].mean(),
        "mean_ret_hard": grouped["ret_hard"].mean(),
        "median_mfe_60": grouped["mfe_60"].median(),
        "median_mae_60": grouped["mae_60"].median(),
    }).reset_index()


def event_table(signals: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (setup, direction), group in signals.groupby(["setup", "direction"], sort=True):
        quiet = group[~group["event_day"].astype(bool)]
        mean_all, _, t_all = day_block_bootstrap(group[PRIMARY], group["day"], resamples=DESCRIPTIVE_RESAMPLES)
        mean_ex, _, t_ex = day_block_bootstrap(quiet[PRIMARY], quiet["day"], resamples=DESCRIPTIVE_RESAMPLES)
        rows.append({"setup": setup, "direction": direction, "n_all": len(group), "mean_all": mean_all, "t_all": t_all, "n_ex_event": len(quiet), "mean_ex_event": mean_ex, "t_ex_event": t_ex})
    return pd.DataFrame(rows)


def per_ticker_means(signals: pd.DataFrame) -> pd.DataFrame:
    """Mean primary return in basis points, rows setup/direction, columns ticker."""
    return (signals.pivot_table(index=["setup", "direction"], columns="symbol", values=PRIMARY, aggfunc="mean") * 1e4).round(1)


def per_ticker_break_even(signals: pd.DataFrame) -> pd.Series:
    """Median break-even move per ticker in basis points."""
    return (signals.groupby("symbol")["be_frac"].median() * 1e4).round(2)


def calibration_spots(symbols, root: Path | None = None) -> dict[str, float]:
    # Cost-model calibration exception to the holdout guard (spec §9.1): spot levels that scale the
    # 2026-calibrated half-spreads to each signal's price. No signals or returns are computed here.
    minutes = load_stock_minutes(list(symbols), *COST_CALIBRATION, holdout=True, root=root)
    et = minutes["ts"].dt.tz_convert(TZ_ET)
    minute_of_day = et.dt.hour * 60 + et.dt.minute
    rth = minutes[(minute_of_day >= 570) & (minute_of_day < 960)]
    return {symbol: float(value) for symbol, value in rth.groupby("symbol")["close"].median().items()}
```

Create `src/options_research/ledger.py`:

```python
"""Append-only multiple-testing ledger (spec §9.3). One JSON line per evaluated configuration."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from src.options_research.config import REPO_ROOT, UNIVERSE, lake_root, reports_dir
from src.options_research.store import stock_minute_files

ONE_SIDED_P_AT_T3 = 0.00135
LEDGER_KEY = ("stage", "setup", "direction", "config_hash", "dataset_version")
_DATASET_INPUTS = (("calendar", "events.parquet"), ("corporate_actions", "splits.parquet"), ("quality", "print_checks.parquet"), ("costs", "half_spread_table.parquet"))


def ledger_path(directory: Path | None = None) -> Path:
    return (directory or reports_dir()) / "ledger.jsonl"


def config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def git_commit(repo: Path = REPO_ROOT) -> str:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    return f"{head}-dirty" if dirty else head


def dataset_version(start: date, end: date, root: Path | None = None, symbols=UNIVERSE) -> str:
    """Fingerprint of the lake inputs: stock day-file names and sizes in the period plus the events/splits/print-check/cost files."""
    root = root or lake_root()
    digest = hashlib.sha256()
    for path in stock_minute_files(symbols, start, end, root=root):
        digest.update(f"{path.parent.parent.name}/{path.name}:{path.stat().st_size}\n".encode("utf-8"))
    for parts in _DATASET_INPUTS:
        path = root.joinpath(*parts)
        digest.update(path.read_bytes() if path.exists() else b"missing")
    return digest.hexdigest()[:16]


def read_ledger(path: Path | None = None) -> pd.DataFrame:
    path = path or ledger_path()
    if not path.exists():
        return pd.DataFrame()
    return pd.DataFrame([json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])


def append_entries(entries: list[dict], path: Path | None = None) -> int:
    path = path or ledger_path()
    existing = read_ledger(path)
    seen = {tuple(record.get(k) for k in LEDGER_KEY) for record in existing.to_dict("records")}
    new = [e for e in entries if tuple(e.get(k) for k in LEDGER_KEY) not in seen]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for e in new:
                handle.write(json.dumps(e, sort_keys=True, default=str) + "\n")
    return len(new)


def expected_false_passes(n_tests: int) -> float:
    return n_tests * ONE_SIDED_P_AT_T3


def _number(value) -> float | None:
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)


def stage1_entries(evaluation: pd.DataFrame, setup_params: dict, eval_params: dict, commit: str, dataset: str, period: str, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    entries = []
    for row in evaluation.to_dict("records"):
        config = {"setup": row["setup"], "direction": row["direction"], "setup_params": setup_params[row["setup"]], "evaluation": eval_params}
        entries.append({
            "timestamp": now.isoformat(), "stage": "stage1", "setup": row["setup"], "direction": row["direction"], "config_hash": config_hash(config),
            "git_commit": commit, "dataset_version": dataset, "period": period, "n": int(row["n"]), "mean_ret_60": _number(row["mean_ret_60"]),
            "t": _number(row["t"]), "passed": bool(row["passed"]),
        })
    return entries
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/options_research/test_evaluate.py tests/options_research/test_ledger.py tests/options_research/test_data_access.py -q`
Expected: all pass.

Run: `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py`
Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add src/options_research/evaluate.py src/options_research/ledger.py tests/options_research/test_evaluate.py tests/options_research/test_ledger.py
git commit -F- <<'EOF'
feat(options_research): stage-1 evaluation (day-block bootstrap, year and cost criteria) and multiple-testing ledger

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 8: M3 report, CLI, real stage-1 run, integration checks, docs

**Files:**
- Modify: `src/options_research/reports.py`. Append `m3_report`.
- Modify: `src/options_research/cli.py`. Add the `stage1` and `report-m3` commands.
- Modify: `tests/options_research/test_reports_cli.py`. Append tests.
- Create: `tests/options_research/test_integration_stage1.py`
- Modify: `CLAUDE.md`. Add commands and the feature/setup layout.
- Generate: `reports/options_research/m3_stage1.md` and `reports/options_research/ledger.jsonl`

**Interfaces:**
- Consumes (Task 6):
  - `stage1.run_stage1(symbols, start, end, workers, overwrite, root)`
  - `stage1.load_signals()`
  - `stage1.signals_path()`
- Consumes (Task 7, `evaluate`):
  - `EVAL_PARAMS`, `add_break_even`, `calibration_spots`, `evaluate_stage1`
  - `horizon_table`, `event_table`, `per_ticker_means`, `per_ticker_break_even`
- Consumes (Task 7, `ledger`):
  - `append_entries`, `stage1_entries`, `git_commit`, `dataset_version`, `read_ledger`, `expected_false_passes`
- Consumes (other modules):
  - `setups.SETUP_PARAMS`, `setups.SETUPS`
  - `costs.load_cost_model()`
  - `config.STAGE1_DEV`, `config.UNIVERSE`, `config.TZ_ET`
- Produces:
  - `reports.m3_report(evaluation, horizons, events, ticker_means, ticker_break_even, summary: dict, ledger: pd.DataFrame) -> str`
  - CLI `stage1 [--symbols A,B] [--workers N] [--overwrite]`
  - CLI `report-m3`

- [ ] **Step 1: Write the failing tests**

Append to `tests/options_research/test_reports_cli.py`:

```python
def test_m3_report_sections():
    from src.options_research.reports import m3_report

    evaluation = pd.DataFrame([
        {"setup": "ORB15", "direction": "long", "n": 400, "mean_ret_60": 0.0012, "se": 0.0003, "t": 4.0, "positive_years": 5, "pooled_break_even": 0.0006, "cost_ratio": 2.0, "pass_t": True, "pass_years": True, "pass_cost": True, "pass_n": True, "passed": True},
        {"setup": "MEANREV", "direction": "short", "n": 120, "mean_ret_60": -0.0001, "se": 0.0004, "t": -0.25, "positive_years": 2, "pooled_break_even": 0.0006, "cost_ratio": -0.17, "pass_t": False, "pass_years": False, "pass_cost": False, "pass_n": False, "passed": False},
    ])
    horizons = pd.DataFrame([{"setup": "ORB15", "direction": "long", "n": 400, "mean_ret_30": 0.001, "mean_ret_60": 0.0012, "mean_ret_hard": 0.002, "median_mfe_60": 0.004, "median_mae_60": -0.002}])
    events = pd.DataFrame([{"setup": "ORB15", "direction": "long", "n_all": 400, "mean_all": 0.0012, "t_all": 4.0, "n_ex_event": 300, "mean_ex_event": 0.0011, "t_ex_event": 3.5}])
    means = pd.DataFrame({"SPY": [12.0]}, index=pd.MultiIndex.from_tuples([("ORB15", "long")], names=["setup", "direction"]))
    break_even = pd.Series({"SPY": 6.0}, name="be_frac")
    ledger = pd.DataFrame([{"stage": "stage1", "config_hash": f"h{i}"} for i in range(18)])
    text = m3_report(evaluation, horizons, events, means, break_even, {"signals": 520}, ledger)
    for heading in ("# M3 Stage-1 Report", "## Pass/fail", "## Criteria", "## Horizons", "## With and without event days", "## Mean +60 min return by ticker (bps)", "## Break-even move by ticker (bps, median)", "## Multiple-testing ledger"):
        assert heading in text
    assert "Passing setup x direction pairs: 1 of 2: ORB15 long" in text
    by_ticker = text.split("## Mean +60 min return by ticker (bps)")[1].split("##")[0]
    assert "SPY" in by_ticker and "12" in by_ticker
    assert "Expected false passes under the null (one-sided p at t = 3): 0.024" in text


def test_stage1_cli_passes_symbols_workers_and_overwrite(monkeypatch, capsys):
    import src.options_research.stage1 as stage1
    from src.options_research.cli import main

    calls = []
    monkeypatch.setattr(stage1, "run_stage1", lambda symbols, workers, overwrite: calls.append((symbols, workers, overwrite)) or {"computed": symbols, "skipped": [], "signals": 0})
    assert main(["stage1", "--symbols", "SPY,QQQ", "--workers", "1", "--overwrite"]) == 0
    assert calls == [(["SPY", "QQQ"], 1, True)]
    assert '"signals": 0' in capsys.readouterr().out
```

Create `tests/options_research/test_integration_stage1.py`:

```python
from datetime import time

import pytest

from src.options_research.config import STAGE1_DEV, TZ_ET

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def signals():
    from src.options_research.stage1 import load_signals, signals_path

    if not signals_path().exists():
        pytest.skip("stage-1 signals not built (run: python -m src.options_research stage1)")
    return load_signals()


def test_every_setup_and_direction_has_signals(signals):
    from src.options_research.setups import SETUPS

    assert set(zip(signals["setup"], signals["direction"])) == {(s, d) for s in SETUPS for d in ("long", "short")}


def test_signals_stay_inside_the_development_period_and_windows(signals):
    assert signals["day"].min() >= STAGE1_DEV[0] and signals["day"].max() <= STAGE1_DEV[1]
    clock = signals["decision_ts"].dt.tz_convert(TZ_ET).dt.time
    assert clock.min() >= time(9, 46) and clock.max() <= time(15, 0)


def test_frequency_limits(signals):
    counts = signals.groupby(["symbol", "day", "setup", "direction"]).size()
    repeatable = counts.index.get_level_values("setup").isin(["VWAP_PULLBACK", "MEANREV"])
    assert counts[~repeatable].max() == 1 and counts[repeatable].max() <= 2


def test_outcomes_are_complete_and_plausible(signals):
    assert signals["ret_60"].notna().mean() > 0.99
    assert signals[["ret_30", "ret_60", "mfe_60", "mae_60"]].abs().max().max() < 0.5


def test_split_neighbourhoods_are_tagged(signals):
    assert signals["near_split"].any()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/options_research/test_reports_cli.py -q`
Expected: `test_m3_report_sections` fails with `ImportError: cannot import name 'm3_report'`, and `test_stage1_cli_passes_symbols_workers_and_overwrite` fails with argparse `invalid choice: 'stage1'` (SystemExit 2).

- [ ] **Step 3: Implement**

Append to `src/options_research/reports.py`:

```python
def _bps(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame.copy()
    for column in columns:
        out[column] = (out[column] * 1e4).round(2)
    return out


def m3_report(
    evaluation: pd.DataFrame,
    horizons: pd.DataFrame,
    events: pd.DataFrame,
    ticker_means: pd.DataFrame,
    ticker_break_even: pd.Series,
    summary: dict,
    ledger: pd.DataFrame,
) -> str:
    """Stage-1 report (spec §8.4): pass/fail table first, then diagnostics. Returns in bps; aggregates only."""
    from src.options_research.ledger import expected_false_passes

    lines = ["# M3 Stage-1 Report (stock-level evaluation, development period)", ""]
    lines += [f"- {key}: {value}" for key, value in summary.items()]
    lines += ["", "## Pass/fail (primary horizon: +60 min)", ""]
    if evaluation.empty:
        lines.append("No signals.")
    else:
        table = _bps(evaluation, ["mean_ret_60", "pooled_break_even"]).rename(columns={"mean_ret_60": "mean_bps", "pooled_break_even": "break_even_bps"})
        table["t"] = table["t"].round(2)
        table["cost_ratio"] = table["cost_ratio"].round(2)
        columns = ["setup", "direction", "n", "mean_bps", "t", "positive_years", "break_even_bps", "cost_ratio", "pass_n", "pass_t", "pass_years", "pass_cost", "passed"]
        lines.append(table[columns].to_markdown(index=False))
    passed = evaluation[evaluation["passed"].astype(bool)] if not evaluation.empty else evaluation
    names = ", ".join(f"{row.setup} {row.direction}" for row in passed.itertuples())
    lines += ["", f"Passing setup x direction pairs: {len(passed)} of {len(evaluation)}" + (f": {names}" if names else ""), ""]
    lines += [
        "## Criteria (spec §8.3, pre-registered)",
        "",
        "- Day-block bootstrap t >= 3.0 (10,000 resamples of trading days, seed 20260912)",
        "- Mean +60 min return > 0 in >= 4 of the 5 calendar years (2021 H2 counts as a year)",
        "- Mean +60 min return >= 1.5 x pooled break-even move (ATM NEAR option, round-trip half-spreads + fees, delta 0.5)",
        "- >= 300 signals",
        "",
        "## Horizons",
        "",
        _bps(horizons, ["mean_ret_30", "mean_ret_60", "mean_ret_hard", "median_mfe_60", "median_mae_60"]).to_markdown(index=False) if not horizons.empty else "No signals.",
        "",
        "## With and without event days",
        "",
        "Event day = a Tier 1/2 macro release that day, or the ticker's earnings reaction day.",
        "",
        _bps(events, ["mean_all", "mean_ex_event"]).round({"t_all": 2, "t_ex_event": 2}).to_markdown(index=False) if not events.empty else "No signals.",
        "",
        "## Mean +60 min return by ticker (bps)",
        "",
        ticker_means.to_markdown() if not ticker_means.empty else "No signals.",
        "",
        "## Break-even move by ticker (bps, median)",
        "",
        ticker_break_even.rename("break_even_bps").to_frame().to_markdown() if not ticker_break_even.empty else "No signals.",
        "",
        "## Multiple-testing ledger",
        "",
    ]
    stage1_rows = ledger[ledger["stage"] == "stage1"] if not ledger.empty else ledger
    count = int(stage1_rows["config_hash"].nunique()) if not stage1_rows.empty else 0
    lines += [f"- Stage-1 configurations recorded: {count}", f"- Expected false passes under the null (one-sided p at t = 3): {expected_false_passes(count):.3f}", ""]
    return "\n".join(lines)
```

In `src/options_research/cli.py`, add these command functions before `def main`:

```python
def _cmd_stage1(args: argparse.Namespace) -> int:
    from src.options_research import stage1

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else list(UNIVERSE)
    print(json.dumps(stage1.run_stage1(symbols, workers=args.workers, overwrite=args.overwrite), default=str))
    return 0


def _cmd_report_m3(args: argparse.Namespace) -> int:
    from src.options_research.config import STAGE1_DEV
    from src.options_research.costs import load_cost_model
    from src.options_research.evaluate import EVAL_PARAMS, add_break_even, calibration_spots, evaluate_stage1, event_table, horizon_table, per_ticker_break_even, per_ticker_means
    from src.options_research.ledger import append_entries, dataset_version, git_commit, read_ledger, stage1_entries
    from src.options_research.reports import m3_report, write_report
    from src.options_research.setups import SETUP_PARAMS
    from src.options_research.stage1 import load_signals

    signals = load_signals()
    signals = add_break_even(signals, load_cost_model(), calibration_spots(sorted(signals["symbol"].unique())))
    evaluation = evaluate_stage1(signals)
    period = f"{STAGE1_DEV[0]}..{STAGE1_DEV[1]}"
    appended = append_entries(stage1_entries(evaluation, SETUP_PARAMS, EVAL_PARAMS, git_commit(), dataset_version(*STAGE1_DEV), period))
    summary = {
        "period": period,
        "signals": int(len(signals)),
        "tickers": int(signals["symbol"].nunique()),
        "sessions with signals": int(signals["day"].nunique()),
        "signals within one session of a split": int(signals["near_split"].sum()),
        "ledger entries appended this run": appended,
    }
    text = m3_report(evaluation, horizon_table(signals), event_table(signals), per_ticker_means(signals), per_ticker_break_even(signals), summary, read_ledger())
    path = write_report("m3_stage1", text)
    print(json.dumps({"report": str(path), "passed": evaluation.loc[evaluation["passed"], ["setup", "direction"]].values.tolist(), "ledger_appended": appended}))
    return 0
```

In `main`, after the `rebuild-clean` parser block, add:

```python
    p = sub.add_parser("stage1", help="stage-1 signals + forward outcomes over the development period (resumable per symbol)")
    p.add_argument("--symbols", default="", help="comma-separated subset of the universe")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=_cmd_stage1)

    sub.add_parser("report-m3", help="stage-1 evaluation, ledger entries and report").set_defaults(func=_cmd_report_m3)
```

- [ ] **Step 4: Run the unit tests**

Run: `~/.local/bin/uv run pytest tests/options_research/test_reports_cli.py -q`
Expected: all pass.

Run: `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py`
Expected: 0 failures.

- [ ] **Step 5: Real stage-1 run (no network; reads the lake)**

Run each command in the foreground with Bash `timeout: 600000`. Never use `run_in_background` or sleep/Monitor loops.

First, time a single symbol:

```bash
PYTHONIOENCODING=utf-8 ~/.local/bin/uv run python -m src.options_research stage1 --symbols SPY --workers 1
```

Then run the rest in batches of four:

```bash
PYTHONIOENCODING=utf-8 ~/.local/bin/uv run python -m src.options_research stage1 --symbols QQQ,IWM,NVDA,TSLA --workers 4
PYTHONIOENCODING=utf-8 ~/.local/bin/uv run python -m src.options_research stage1 --symbols AAPL,AMZN,MSFT,GOOGL --workers 4
PYTHONIOENCODING=utf-8 ~/.local/bin/uv run python -m src.options_research stage1 --symbols META,AMD,NFLX --workers 3
PYTHONIOENCODING=utf-8 ~/.local/bin/uv run python -m src.options_research stage1 --workers 4
```

- If a batch times out, re-run the same command. Finished symbols are skipped.
- If one symbol alone takes more than 8 minutes, stop and report the SPY timing (status BLOCKED). The controller will split the run.
- The last command (all symbols) skips completed symbols and writes the combined, tagged `signals.parquet`.

- [ ] **Step 6: Report and integration checks**

```bash
PYTHONIOENCODING=utf-8 ~/.local/bin/uv run python -m src.options_research report-m3
~/.local/bin/uv run pytest -m integration tests/options_research -q
```

Expected:
- `report-m3` prints the report path, the passing pairs and `ledger_appended: 18`.
- All integration tests pass: the 9 existing plus 5 new.

If a stage-1 integration test fails, do NOT change the test or any pre-registered parameter. Report:
- the failing assertion
- the offending rows (symbol, day, setup, direction, decision_ts)
- your diagnosis

Then stop with DONE_WITH_CONCERNS.

Re-running `report-m3` must append 0 ledger entries. Check this once and record it in your report.

- [ ] **Step 7: Update CLAUDE.md**

In `CLAUDE.md`, in the options-research command block, add these two lines after the `report-m1 && ... report-m2` line:

```bash
uv run python -m src.options_research stage1 --workers 4   # stage-1 signals + outcomes (resumable per symbol; --symbols, --overwrite)
uv run python -m src.options_research report-m3            # evaluation vs spec §8.3, ledger entries, reports/options_research/m3_stage1.md
```

Directly after the `**Clean columns are hindsight values.**` bullet list, add this paragraph:

```markdown
**Stage-1 layout.**
- `features.py` builds raw point-in-time features: a 1-min grid, VWAP/σ, and 5-min Wilder
  indicators attached only when the 5-min bar is complete.
- `levels.py` is the only feature module that reads clean columns. It holds prior-day and
  pre-market levels plus the 5-session warm-up, all split-adjusted.
- `setups/` holds one detector per pre-registered setup. It takes a `DayContext` and returns
  signals decided at `T = bar start + 1 min`.
- `stage1.py` runs the detectors and adds forward outcomes and tags. `evaluate.py` applies spec §8.3.
- `ledger.py` records every evaluated configuration in `reports/options_research/ledger.jsonl`.
- Pre-registered interpretations are in `docs/superpowers/plans/2026-09-13-options-research-m3-stage1.md`.
  Changing a setup parameter or evaluation rule creates new ledger configurations.
```

- [ ] **Step 8: Commit**

```bash
git add src/options_research/reports.py src/options_research/cli.py tests/options_research/test_reports_cli.py tests/options_research/test_integration_stage1.py CLAUDE.md reports/options_research/m3_stage1.md reports/options_research/ledger.jsonl
git commit -F- <<'EOF'
feat(options_research): stage-1 CLI and M3 report; run over the development period; ledger entries

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

- [ ] **Step 9: Hand back**

Report to the controller:
- the per-batch stage1 JSON and the per-symbol timing
- the report's pass/fail table (copy it)
- the integration test output and the `ledger_appended` values from both runs
- anything unexpected, for example a setup with very few signals or a direction with no signals

The user reviews which setups pass (spec §11 M3 checkpoint). Do not start M4.
