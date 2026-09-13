# Options Research M3-0 (Data Readiness) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the M1 causal bad-print filter with the approved two-sided, trade-confirmed
cleaning.
- Only isolated off-market prints get a clean high/low: the most extreme price actually traded
  inside the band. Genuine moves keep raw values.
- Also add a split volume-adjustment helper, enforce loader-only data access, restore UTC
  timestamps in reports, and rebuild the lake's clean columns and the M1 report.

**Architecture:**
- `quality.py` becomes three pure functions: `find_print_candidates`, `classify_print` and
  `apply_clean`.
- A new `print_checks.py` orchestrates a resumable three-phase maintenance job over the stored day
  files (no zip re-read):
  - **scan** — offline and parallel; writes `quality/print_candidates.parquet`
  - **confirm** — Alpaca SIP trades per candidate minute; writes the audit file
    `quality/print_checks.parquet`
  - **rewrite** — offline and parallel; resets and applies the clean columns and normalizes the
    schema
- Ingest writes pass-through clean columns (flags False, clean = raw).
- The read-only Alpaca client gains exactly one endpoint, `/v2/stocks/trades`.

**Tech Stack:** Python 3.12 via uv; pandas 2.3, numpy 1.26, httpx, duckdb 1.5, pyarrow 25 (all
installed).

**Spec:** `docs/superpowers/specs/2026-09-12-options-edge-research-design.md` — read §2 (allowlist),
§5.1 "Bad prints" (the approved M3-0 design), §9.1 (holdout) and §11 (M3-0 row).

## Global Constraints

- **Tooling:** run from the repo root `C:\Users\tsedi\swarm-trader-fork` with `~/.local/bin/uv`.
  The shell is Git Bash. Prefix commands with non-ASCII output with `PYTHONIOENCODING=utf-8`.
- **Isolation:** `src/options_research/` must NOT import from root scripts, `src/agents`,
  `src/alpaca_integration.py` or `src/accounts.py`.
- **Alpaca access:** only through `src/options_research/alpaca_data.py`.
  - GET only.
  - The allowlist becomes exactly `data.alpaca.markets` `/v1beta1/options/bars`,
    `/v1beta1/options/trades`, `/v2/stocks/bars`, `/v2/stocks/trades` and `api.alpaca.markets`
    `/v2/options/contracts`.
  - Non-default ports and URL credentials are rejected.
  - Keys come only from `ALPACA_DATA_API_KEY` / `ALPACA_DATA_SECRET_KEY`.
- **Cleaning parameters** (spec §5.1, exact values):
  - 15-bar centered window, needing ≥ 6 bars
  - band = max(8 × MAD, 3% of the reference)
  - snap-back: the median of the next 5 closes is within the band
  - isolated print: 1–3 trades beyond the band, all with exchange code `D`
  - clean value: the most extreme in-band traded price, clipped into the raw bar; empty when there
    is no in-band trade
- **Hindsight rule:** clean columns may only feed values read after the relevant window ends
  (prior-day high/low/close, ATR history, pre-market high/low at or after 09:30). Intraday
  regular-hours features use raw OHLC.
- **Holdout guard:** unchanged. `print_checks.py` is a data-maintenance exception (spec §9.1). Its
  module docstring must say so. It rewrites lake files and computes no strategy metrics.
- **Timestamps:** tz-aware UTC in storage; `ts` = bar start. Reports render `ts` in UTC
  (`SET TimeZone='UTC'`).
- **No vendor data in git:** `data/` is gitignored; reports under `reports/options_research/` are
  committed.
- **Tests:** TDD. Unit tests are offline (httpx.MockTransport, injected fetchers). Real-data tests
  are marked `@pytest.mark.integration`.
- **Unit suite:** `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py`. Baseline
  is 223 passed, with 8 pre-existing warnings from `tests/security`.
- **Commits:** every commit message ends with a `Co-Authored-By: <your actual model name>
  <noreply@anthropic.com>` line, followed by exactly
  `Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx`.
- **Branch:** work on `local-setup`. Do not push; the controller pushes.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/options_research/alpaca_data.py` | Read-only client | Add `/v2/stocks/trades` to allowlist |
| `src/options_research/stocks_alpaca.py` | Alpaca stock data | Add `STOCK_TRADES_URL`, `fetch_minute_trades` |
| `src/options_research/quality.py` | Pure cleaning logic | Rewrite: `find_print_candidates`, `classify_print`, `apply_clean` (remove `flag_bad_prints`) |
| `src/options_research/stocks.py` | Zip ingest | `STOCK_COLUMNS` drops `bad_close`; `normalize_minutes` writes pass-through clean columns |
| `src/options_research/store.py` | Loader | `union_by_name=True` for mixed legacy/new files |
| `src/options_research/print_checks.py` | New: scan → confirm → rewrite maintenance job | Create |
| `src/options_research/cli.py` | CLI | Add `rebuild-clean --phase all\|scan\|confirm\|rewrite --workers N` |
| `src/options_research/reports.py` | Reports | Adjustments table without `bad_close`, excluded-bar flag, UTC restored, new "Print checks" section |
| `src/options_research/corporate_actions.py` | Splits | Add `volume_adjustment_factors` |
| `tests/options_research/test_data_access.py` | New: loader-only access guard | Create |
| `tests/options_research/test_print_checks.py` | New | Create |
| `CLAUDE.md` | Agent guide | Replace the provisional-clean warning with the hindsight rule + `rebuild-clean` |

---

### Task 1: Allow stock trades endpoint and fetch one minute of trades

**Files:**
- Modify: `src/options_research/alpaca_data.py:1-22`
- Modify: `src/options_research/stocks_alpaca.py` (add constant + function after `STOCK_BARS_URL`)
- Test: `tests/options_research/test_alpaca_data.py`, `tests/options_research/test_stocks_alpaca.py`

**Interfaces:**
- Produces:
  - `STOCK_TRADES_URL = "https://data.alpaca.markets/v2/stocks/trades"`
  - `fetch_minute_trades(client: AlpacaDataClient, symbol: str, minute_start: pd.Timestamp) -> list[dict]`
    - Each dict has keys `t: str`, `price: float`, `size: int`, `exchange: str`,
      `conditions: list[str]`.
    - Returns only trades with `minute_start <= t < minute_start + 1 min`.

- [ ] **Step 1: Update the allowlist test (RED)**

In `tests/options_research/test_alpaca_data.py`, change `test_allowlist_is_exactly_the_spec_endpoints` so the expected frozenset is:

```python
    assert ALLOWED_ENDPOINTS == frozenset({
        ("data.alpaca.markets", "/v1beta1/options/bars"),
        ("data.alpaca.markets", "/v1beta1/options/trades"),
        ("data.alpaca.markets", "/v2/stocks/bars"),
        ("data.alpaca.markets", "/v2/stocks/trades"),
        ("api.alpaca.markets", "/v2/options/contracts"),
    })
```

- [ ] **Step 2: Add the trades-fetch test (RED)**

Append to `tests/options_research/test_stocks_alpaca.py` (it already imports `httpx`, `pandas as pd`, `AlpacaDataClient`, `RateLimiter`):

```python
from src.options_research.stocks_alpaca import STOCK_TRADES_URL, fetch_minute_trades


def test_fetch_minute_trades_paginates_and_keeps_only_the_minute():
    pages = {
        None: {"trades": {"META": [
            {"t": "2023-02-01T23:15:05.123456789Z", "p": 182.9, "s": 100, "x": "V", "c": ["@", "T"]},
        ]}, "next_page_token": "p2"},
        "p2": {"trades": {"META": [
            {"t": "2023-02-01T23:15:40Z", "p": 153.12, "s": 100000, "x": "D", "c": ["@", "T"]},
            {"t": "2023-02-01T23:16:00Z", "p": 183.0, "s": 10, "x": "V", "c": ["@"]},
        ]}, "next_page_token": None},
    }

    def handler(request):
        assert request.method == "GET"
        assert str(request.url).startswith(STOCK_TRADES_URL)
        assert request.url.params["symbols"] == "META"
        assert request.url.params["feed"] == "sip"
        assert request.url.params["start"] == "2023-02-01T23:15:00Z"
        assert request.url.params["end"] == "2023-02-01T23:16:00Z"
        return httpx.Response(200, json=pages[request.url.params.get("page_token")])

    client = AlpacaDataClient(key="k", secret="s", http=httpx.Client(transport=httpx.MockTransport(handler)),
                              limiter=RateLimiter(1000), sleep=lambda s: None)
    trades = fetch_minute_trades(client, "META", pd.Timestamp("2023-02-01T23:15:00Z"))
    assert [(t["price"], t["size"], t["exchange"], t["conditions"]) for t in trades] == [
        (182.9, 100, "V", ["@", "T"]),
        (153.12, 100000, "D", ["@", "T"]),
    ]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/options_research/test_alpaca_data.py::test_allowlist_is_exactly_the_spec_endpoints tests/options_research/test_stocks_alpaca.py::test_fetch_minute_trades_paginates_and_keeps_only_the_minute -v`
Expected: FAIL. The allowlist assertion fails, and the second test fails with `ImportError: cannot import name 'STOCK_TRADES_URL'`.

- [ ] **Step 4: Implement**

In `src/options_research/alpaca_data.py`, change the module docstring's second paragraph to
`safety boundary: GET only, a fixed set of data/listing endpoints, no method that can send an order.`
and make the allowlist:

```python
ALLOWED_ENDPOINTS: frozenset[tuple[str, str]] = frozenset({
    ("data.alpaca.markets", "/v1beta1/options/bars"),
    ("data.alpaca.markets", "/v1beta1/options/trades"),
    ("data.alpaca.markets", "/v2/stocks/bars"),
    ("data.alpaca.markets", "/v2/stocks/trades"),
    ("api.alpaca.markets", "/v2/options/contracts"),
})
```

In `src/options_research/stocks_alpaca.py`, directly below `STOCK_BARS_URL = ...`, add:

```python
STOCK_TRADES_URL = "https://data.alpaca.markets/v2/stocks/trades"
```

and after `fetch_alpaca_day`, add:

```python
def fetch_minute_trades(client: AlpacaDataClient, symbol: str, minute_start: pd.Timestamp) -> list[dict]:
    """SIP trades for one symbol with minute_start <= t < minute_start + 1 minute (spec §5.1 confirmation)."""
    start = pd.Timestamp(minute_start).tz_convert("UTC")
    end = start + pd.Timedelta(minutes=1)
    params = {
        "symbols": symbol,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feed": "sip",
        "limit": 10000,
    }
    trades: list[dict] = []
    for page in client.paginate(STOCK_TRADES_URL, params):
        for trade in (page.get("trades") or {}).get(symbol, []):
            if start <= pd.Timestamp(trade["t"]) < end:
                trades.append({
                    "t": trade["t"],
                    "price": float(trade["p"]),
                    "size": int(trade["s"]),
                    "exchange": str(trade.get("x", "")),
                    "conditions": list(trade.get("c") or []),
                })
    return trades
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/options_research/test_alpaca_data.py tests/options_research/test_stocks_alpaca.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/options_research/alpaca_data.py src/options_research/stocks_alpaca.py tests/options_research/test_alpaca_data.py tests/options_research/test_stocks_alpaca.py
git commit -F- <<'EOF'
feat(options_research): allow read-only stock trades endpoint and fetch one minute of SIP trades

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 2: Two-sided, trade-confirmed cleaning functions and schema change

**Files:**
- Rewrite: `src/options_research/quality.py`
- Modify: `src/options_research/stocks.py:16,20,43-56`
- Modify: `src/options_research/store.py:56`
- Rewrite: `tests/options_research/test_quality.py`
- Modify: `tests/options_research/test_store.py` (fixture + one new test)
- Modify: `tests/options_research/test_stocks_alpaca.py` (fixture only)

**Interfaces:**
- Produces:
  - constants `WINDOW=15`, `MIN_WINDOW_BARS=6`, `MAD_MULT=8.0`, `MIN_BAND_PCT=0.03`,
    `SNAPBACK_BARS=5`, `MAX_ISOLATED_TRADES=3`, `OFF_EXCHANGE_CODE="D"`
  - `CANDIDATE_COLUMNS = ["ts", "side", "extreme", "reference", "band"]`
  - `find_print_candidates(day: pd.DataFrame) -> pd.DataFrame`
    - input: one symbol-session with `ts, open, high, low, close`
    - returns `CANDIDATE_COLUMNS`; `side` is `"high"` or `"low"`
  - `classify_print(trades: list[dict], side: str, reference: float, band: float) -> dict`
    - keys: `decision` (`"isolated"|"genuine"|"no_outlier_trades"|"no_trades"`), `n_trades`,
      `n_outliers`, `outlier_prices`, `outlier_exchanges`, `outlier_conditions`, `clean_value`
      (`float | None`)
  - `apply_clean(day: pd.DataFrame, checks: pd.DataFrame | None) -> pd.DataFrame`
    - resets `bad_high`, `bad_low`, `high_clean`, `low_clean` from raw, then applies
      `decision == "isolated"` rows (`ts, side, decision, clean_value`)
    - clean values are clipped into the raw bar
    - an inverted pair becomes NaN for both
  - `stocks.STOCK_COLUMNS = ["symbol", "ts", "open", "high", "low", "close", "volume", "transactions", "bad_high", "bad_low", "high_clean", "low_clean", "source"]`

- [ ] **Step 1: Rewrite the quality tests (RED)**

Replace the whole of `tests/options_research/test_quality.py` with:

```python
import numpy as np
import pandas as pd
import pytest

from src.options_research.quality import apply_clean, classify_print, find_print_candidates


def day_frame(closes, lows=None, highs=None, opens=None, start="2023-02-01T21:00:00Z"):
    n = len(closes)
    ts = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    closes = [float(c) for c in closes]
    return pd.DataFrame({
        "ts": ts,
        "open": opens or closes,
        "high": highs or [c + 0.05 for c in closes],
        "low": lows or [c - 0.05 for c in closes],
        "close": closes,
    })


def wobble(level, n=30):
    return [level + (0.05 if i % 2 else -0.05) for i in range(n)]


def test_snapback_low_wick_is_a_candidate():
    closes = wobble(183.0)
    lows = [c - 0.05 for c in closes]
    lows[15] = 153.12
    cands = find_print_candidates(day_frame(closes, lows=lows))
    assert list(cands.columns) == ["ts", "side", "extreme", "reference", "band"]
    assert len(cands) == 1
    row = cands.iloc[0]
    assert row["side"] == "low" and row["extreme"] == 153.12
    assert row["reference"] == pytest.approx(183.0, abs=0.1)
    assert row["band"] == pytest.approx(0.03 * row["reference"])


def test_clean_step_move_produces_no_candidates():
    closes = [100.0] * 15 + [106.0] * 15
    assert find_print_candidates(day_frame(closes)).empty


def test_spike_that_does_not_snap_back_is_not_a_candidate():
    closes = [100.0] * 15 + [120.0] * 15
    highs = [c + 0.05 for c in closes]
    highs[14] = 125.0
    assert find_print_candidates(day_frame(closes, highs=highs)).empty


def test_sessions_shorter_than_six_bars_have_no_reference():
    closes = [50.0] * 5
    lows = [49.95] * 5
    lows[2] = 30.0
    assert find_print_candidates(day_frame(closes, lows=lows)).empty


def trades(prices_exchanges):
    return [{"t": "2023-02-01T21:15:00Z", "price": p, "size": 100, "exchange": x, "conditions": ["@"]} for p, x in prices_exchanges]


def test_single_off_exchange_print_is_isolated_and_cleans_to_extreme_in_band_trade():
    result = classify_print(trades([(182.75, "V"), (182.90, "P"), (182.94, "V"), (153.12, "D")]), "low", 183.0, 5.49)
    assert result["decision"] == "isolated"
    assert result["n_trades"] == 4 and result["n_outliers"] == 1
    assert result["outlier_prices"] == [153.12] and result["outlier_exchanges"] == ["D"]
    assert result["clean_value"] == 182.75


def test_high_side_clean_value_is_max_in_band_trade():
    result = classify_print(trades([(299.26, "Q"), (299.67, "V"), (309.35, "D")]), "high", 299.45, 8.98)
    assert result["decision"] == "isolated" and result["clean_value"] == 299.67


def test_on_exchange_outlier_is_genuine():
    result = classify_print(trades([(177.5, "V"), (169.0, "P")]), "low", 177.88, 5.34)
    assert result["decision"] == "genuine" and result["clean_value"] is None


def test_more_than_three_outliers_is_genuine_even_off_exchange():
    result = classify_print(trades([(177.5, "V")] + [(169.0, "D")] * 4), "low", 177.88, 5.34)
    assert result["decision"] == "genuine"


def test_no_trades_and_no_outliers_decisions():
    assert classify_print([], "low", 100.0, 3.0)["decision"] == "no_trades"
    assert classify_print(trades([(100.1, "V")]), "low", 100.0, 3.0)["decision"] == "no_outlier_trades"


def test_isolated_without_in_band_trades_has_empty_clean_value():
    result = classify_print(trades([(195.0, "D"), (190.0, "D")]), "high", 171.82, 5.15)
    assert result["decision"] == "isolated" and result["clean_value"] is None


def test_apply_clean_resets_then_applies_isolated_decisions():
    day = day_frame(wobble(183.0))
    day.loc[15, "low"] = 153.12
    day["bad_high"] = True  # stale values must be reset
    checks = pd.DataFrame({"ts": [day.loc[15, "ts"], day.loc[3, "ts"], day.loc[5, "ts"]],
                           "side": ["low", "high", "low"],
                           "decision": ["isolated", "genuine", "isolated"],
                           "clean_value": [182.75, 999.0, None]})
    out = apply_clean(day, checks)
    assert out.loc[15, "bad_low"] and out.loc[15, "low_clean"] == 182.75
    assert not out["bad_high"].any() and out.loc[3, "high_clean"] == out.loc[3, "high"]
    assert out.loc[5, "bad_low"] and np.isnan(out.loc[5, "low_clean"])
    untouched = out.drop(index=[5, 15])
    assert (untouched["low_clean"] == untouched["low"]).all() and (untouched["high_clean"] == untouched["high"]).all()


def test_apply_clean_without_checks_is_pass_through():
    day = day_frame(wobble(50.0, n=8))
    out = apply_clean(day, None)
    assert not out["bad_high"].any() and not out["bad_low"].any()
    assert (out["high_clean"] == out["high"]).all() and (out["low_clean"] == out["low"]).all()


def test_apply_clean_never_leaves_the_raw_bar_range():
    rng = np.random.RandomState(0)
    n = 200
    mid = 100 + rng.randn(n).cumsum() * 0.1
    day = pd.DataFrame({"ts": pd.date_range("2024-01-02T14:30:00Z", periods=n, freq="1min", tz="UTC"),
                        "open": mid, "high": mid + rng.rand(n), "low": mid - rng.rand(n), "close": mid})
    picks = rng.choice(n, 40, replace=False)
    checks = pd.DataFrame({"ts": day["ts"].iloc[picks].reset_index(drop=True), "side": rng.choice(["high", "low"], 40),
                           "decision": "isolated", "clean_value": mid[picks] + rng.randn(40) * 5})
    checks.loc[checks.index[:5], "clean_value"] = np.nan
    out = apply_clean(day, checks)
    hc, lc = out["high_clean"], out["low_clean"]
    assert ((hc.isna()) | ((hc >= out["low"] - 1e-12) & (hc <= out["high"] + 1e-12))).all()
    assert ((lc.isna()) | ((lc >= out["low"] - 1e-12) & (lc <= out["high"] + 1e-12))).all()
    both = hc.notna() & lc.notna()
    assert (lc[both] <= hc[both] + 1e-12).all()


def test_apply_clean_inverted_pair_becomes_empty():
    day = day_frame([100.0] * 8)
    t = day.loc[4, "ts"]
    checks = pd.DataFrame({"ts": [t, t], "side": ["high", "low"], "decision": ["isolated", "isolated"],
                           "clean_value": [99.96, 100.04]})
    out = apply_clean(day, checks)
    assert np.isnan(out.loc[4, "high_clean"]) and np.isnan(out.loc[4, "low_clean"])
```

- [ ] **Step 2: Add the mixed-schema loader test and drop `bad_close` from fixtures (RED)**

In `tests/options_research/test_store.py`:
- In the fixture dict at line 13, delete `"bad_close": [False],`.
- Append:

```python
def test_loads_mixed_legacy_and_new_schema_files(tmp_path):
    lake_day(tmp_path, "SPY", "2025-06-11T13:30:00Z", 600.0)
    legacy = pd.read_parquet(stock_minute_files(["SPY"], date(2025, 6, 11), date(2025, 6, 11), root=tmp_path)[0])
    lake_day(tmp_path, "SPY", "2025-06-12T13:30:00Z", 601.0)
    legacy_path = stock_minute_files(["SPY"], date(2025, 6, 12), date(2025, 6, 12), root=tmp_path)[0]
    legacy.assign(bad_close=False, close=601.0, ts=pd.to_datetime(["2025-06-12T13:30:00Z"], utc=True)).to_parquet(legacy_path, index=False)
    df = load_stock_minutes(["SPY"], date(2025, 6, 11), date(2025, 6, 12), root=tmp_path)
    assert list(df.columns) == STOCK_COLUMNS and df["close"].tolist() == [600.0, 601.0]
```

In `tests/options_research/test_stocks_alpaca.py`, in the `lake_rows` dict of `test_validate_zip_overlap_reads_lake_and_compares`, delete `"bad_close": [False],`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/options_research/test_quality.py tests/options_research/test_store.py -v`
Expected: FAIL. `test_quality.py` fails with `ImportError: cannot import name 'apply_clean'`.
`test_loads_mixed_legacy_and_new_schema_files` fails from the DuckDB schema mismatch or a
`KeyError` on the legacy column.

- [ ] **Step 4: Implement `quality.py`**

Replace the whole of `src/options_research/quality.py` with:

```python
"""Bad-print cleaning for 1-minute stock bars (spec §5.1): two-sided candidates + trade-level confirmation.

The candidate step uses bars AFTER each bar, so clean columns are hindsight values: they may only feed levels
read once the relevant window is over (prior-day high/low/close, ATR history, pre-market high/low at/after 09:30).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW = 15
MIN_WINDOW_BARS = 6
MAD_MULT = 8.0
MIN_BAND_PCT = 0.03
SNAPBACK_BARS = 5
MAX_ISOLATED_TRADES = 3
OFF_EXCHANGE_CODE = "D"
CANDIDATE_COLUMNS = ["ts", "side", "extreme", "reference", "band"]


def find_print_candidates(day: pd.DataFrame) -> pd.DataFrame:
    if day.empty:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS)
    bars = day.sort_values("ts").reset_index(drop=True)
    close = bars["close"].astype(float)
    reference = close.rolling(WINDOW, center=True, min_periods=MIN_WINDOW_BARS).median()
    mad = (close - reference).abs().rolling(WINDOW, center=True, min_periods=MIN_WINDOW_BARS).median()
    band = np.maximum(MAD_MULT * mad, MIN_BAND_PCT * reference)
    next_closes = pd.concat([close.shift(-k) for k in range(1, SNAPBACK_BARS + 1)], axis=1)
    snapped_back = (next_closes.median(axis=1, skipna=True) - reference).abs() <= band
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    rows = []
    for side, extreme, outside in (("high", high, high - reference > band), ("low", low, reference - low > band)):
        for i in np.flatnonzero((outside & snapped_back).to_numpy()):
            rows.append({
                "ts": bars.loc[i, "ts"],
                "side": side,
                "extreme": float(extreme.iloc[i]),
                "reference": float(reference.iloc[i]),
                "band": float(band.iloc[i]),
            })
    if not rows:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS)
    return pd.DataFrame(rows, columns=CANDIDATE_COLUMNS).sort_values(["ts", "side"]).reset_index(drop=True)


def classify_print(trades: list[dict], side: str, reference: float, band: float) -> dict:
    upper, lower = reference + band, reference - band
    if side == "high":
        outliers = [t for t in trades if t["price"] > upper]
    else:
        outliers = [t for t in trades if t["price"] < lower]
    in_band = [t["price"] for t in trades if lower <= t["price"] <= upper]
    isolated = 0 < len(outliers) <= MAX_ISOLATED_TRADES and all(t["exchange"] == OFF_EXCHANGE_CODE for t in outliers)
    if not trades:
        decision = "no_trades"
    elif not outliers:
        decision = "no_outlier_trades"
    else:
        decision = "isolated" if isolated else "genuine"
    clean_value = None
    if decision == "isolated" and in_band:
        clean_value = max(in_band) if side == "high" else min(in_band)
    return {
        "decision": decision,
        "n_trades": len(trades),
        "n_outliers": len(outliers),
        "outlier_prices": [t["price"] for t in outliers],
        "outlier_exchanges": [t["exchange"] for t in outliers],
        "outlier_conditions": [",".join(t["conditions"]) for t in outliers],
        "clean_value": clean_value,
    }


def apply_clean(day: pd.DataFrame, checks: pd.DataFrame | None) -> pd.DataFrame:
    out = day.copy()
    out["bad_high"] = False
    out["bad_low"] = False
    out["high_clean"] = out["high"].astype(float)
    out["low_clean"] = out["low"].astype(float)
    if checks is not None and not checks.empty:
        for check in checks[checks["decision"] == "isolated"].itertuples(index=False):
            matches = out.index[out["ts"] == check.ts]
            if len(matches) == 0:
                continue
            i = matches[0]
            out.loc[i, f"bad_{check.side}"] = True
            column = f"{check.side}_clean"
            value = check.clean_value
            if value is None or pd.isna(value):
                out.loc[i, column] = np.nan
            else:
                out.loc[i, column] = float(np.clip(float(value), out.loc[i, "low"], out.loc[i, "high"]))
    inverted = out["high_clean"].notna() & out["low_clean"].notna() & (out["low_clean"] > out["high_clean"])
    out.loc[inverted, ["high_clean", "low_clean"]] = np.nan
    return out
```

- [ ] **Step 5: Implement the schema change in `stocks.py` and `store.py`**

In `src/options_research/stocks.py`:
- Replace `from src.options_research.quality import flag_bad_prints` with `from src.options_research.quality import apply_clean`.
- Replace the `STOCK_COLUMNS` line with:

```python
STOCK_COLUMNS = RAW_COLUMNS + ["bad_high", "bad_low", "high_clean", "low_clean", "source"]
```

- Replace the body of `normalize_minutes` with:

```python
def normalize_minutes(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=STOCK_COLUMNS)
    et = raw["ts"].dt.tz_convert(TZ_ET)
    minute_of_day = et.dt.hour * 60 + et.dt.minute
    kept = raw.loc[(minute_of_day >= _FIRST_MINUTE) & (minute_of_day < _END_MINUTE), RAW_COLUMNS]
    if kept.empty:
        return pd.DataFrame(columns=STOCK_COLUMNS)
    # Pass-through clean columns (flags False, clean = raw); `rebuild-clean` applies trade-confirmed cleaning (spec §5.1).
    out = apply_clean(kept.sort_values(["symbol", "ts"]).reset_index(drop=True), None)
    out["volume"] = out["volume"].astype("int64")
    out["transactions"] = out["transactions"].fillna(0).astype("int64")
    out["source"] = source
    return out[STOCK_COLUMNS]
```

In `src/options_research/store.py` line 56, change `con.read_parquet([p.as_posix() for p in files])` to `con.read_parquet([p.as_posix() for p in files], union_by_name=True)`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/options_research/test_quality.py tests/options_research/test_store.py tests/options_research/test_stocks.py tests/options_research/test_stocks_alpaca.py -v`
Expected: all pass.

Run: `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py`
Expected: failures only in `tests/options_research/test_reports_cli.py`, because its seeds and query
still reference `bad_close` (Task 4 fixes this). Everything else passes. Record the exact counts in
your report.

- [ ] **Step 7: Commit**

```bash
git add src/options_research/quality.py src/options_research/stocks.py src/options_research/store.py tests/options_research/test_quality.py tests/options_research/test_store.py tests/options_research/test_stocks_alpaca.py
git commit -F- <<'EOF'
feat(options_research): two-sided trade-confirmed bad-print cleaning functions; drop bad_close

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 3: `print_checks.py` maintenance job and `rebuild-clean` CLI

**Files:**
- Create: `src/options_research/print_checks.py`
- Modify: `src/options_research/cli.py` (new command)
- Test: `tests/options_research/test_print_checks.py`

**Interfaces:**
- Consumes:
  - `quality.find_print_candidates`, `classify_print`, `apply_clean`
  - `stocks.STOCK_COLUMNS`, `normalize_minutes`, `write_day`, `day_path`
  - `stocks_alpaca.fetch_minute_trades`
  - `config.UNIVERSE`, `lake_root`
- Produces:
  - `CANDIDATES_COLUMNS = ["symbol", "session_date", "ts", "side", "extreme", "reference", "band"]`
  - `CHECK_COLUMNS = CANDIDATES_COLUMNS + ["decision", "n_trades", "n_outliers", "outlier_prices", "outlier_exchanges", "outlier_conditions", "clean_value"]`
  - `candidates_path(root) -> Path` (`root/quality/print_candidates.parquet`) and `checks_path(root) -> Path` (`root/quality/print_checks.parquet`)
  - `lake_day_files(root: Path, symbols: Iterable[str]) -> list[Path]`
  - `scan_candidates(root: Path | None = None, symbols=UNIVERSE, workers: int = 4) -> pd.DataFrame` (writes the candidates file)
  - `confirm_candidates(candidates: pd.DataFrame, fetch_trades: Callable[[str, pd.Timestamp], list[dict]], root: Path | None = None, flush_every: int = 100) -> pd.DataFrame`
    - resumable: skips (symbol, ts, side) already in the audit file
    - writes the audit file
  - `rewrite_clean_columns(checks: pd.DataFrame, root: Path | None = None, symbols=UNIVERSE, workers: int = 4) -> dict`
    - returns `{"files": int, "flags": int}`
  - `rebuild_clean(client, phase: str = "all", root: Path | None = None, symbols=UNIVERSE, workers: int = 4) -> dict`
    - `phase` is one of `all`, `scan`, `confirm`, `rewrite`
- CLI: `rebuild-clean [--phase all|scan|confirm|rewrite] [--workers N]`

- [ ] **Step 1: Write the failing tests**

Create `tests/options_research/test_print_checks.py`:

```python
from datetime import date

import httpx
import pandas as pd

from src.options_research.alpaca_data import AlpacaDataClient, RateLimiter
from src.options_research.print_checks import (
    CHECK_COLUMNS,
    candidates_path,
    checks_path,
    confirm_candidates,
    rebuild_clean,
    rewrite_clean_columns,
    scan_candidates,
)
from src.options_research.stocks import STOCK_COLUMNS, day_path, normalize_minutes, write_day

DAY = date(2023, 2, 1)
WICK_TS = pd.Timestamp("2023-02-01T21:15:00Z")


def wick_day(symbol="SYM", start="2023-02-01T21:00:00Z", n=30):
    ts = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    closes = [183.0 + (0.05 if i % 2 else -0.05) for i in range(n)]
    raw = pd.DataFrame({"symbol": symbol, "ts": ts, "open": closes, "high": [c + 0.05 for c in closes],
                        "low": [c - 0.05 for c in closes], "close": closes, "volume": 1000, "transactions": 20})
    raw.loc[15, "low"] = 153.12
    return normalize_minutes(raw, source="zip")


def seed(root):
    write_day(wick_day(), DAY, root)
    legacy = normalize_minutes(pd.DataFrame({
        "symbol": "SYM", "ts": pd.date_range("2023-02-02T15:00:00Z", periods=10, freq="1min", tz="UTC"),
        "open": 50.0, "high": 50.1, "low": 49.9, "close": 50.0, "volume": 10, "transactions": 1,
    }), source="zip").assign(bad_close=False)
    write_day(legacy, date(2023, 2, 2), root)


def fake_trades(symbol, ts):
    assert symbol == "SYM" and ts == WICK_TS
    return [{"t": "2023-02-01T21:15:01Z", "price": p, "size": 100, "exchange": x, "conditions": ["@", "T"]}
            for p, x in ((182.75, "V"), (182.90, "P"), (182.94, "V"), (153.12, "D"))]


def test_scan_candidates_finds_the_wick_and_writes_file(tmp_path):
    seed(tmp_path)
    cands = scan_candidates(tmp_path, symbols=["SYM"], workers=1)
    assert cands[["symbol", "side", "extreme"]].values.tolist() == [["SYM", "low", 153.12]]
    assert pd.Timestamp(cands.iloc[0]["ts"]) == WICK_TS
    assert str(pd.Timestamp(cands.iloc[0]["session_date"]).date()) == "2023-02-01"
    assert candidates_path(tmp_path).exists()


def test_confirm_candidates_is_resumable(tmp_path):
    seed(tmp_path)
    cands = scan_candidates(tmp_path, symbols=["SYM"], workers=1)
    calls = []

    def fetch(symbol, ts):
        calls.append((symbol, ts))
        return fake_trades(symbol, ts)

    first = confirm_candidates(cands, fetch, root=tmp_path)
    assert len(calls) == 1
    assert list(first.columns) == CHECK_COLUMNS
    assert first.iloc[0]["decision"] == "isolated" and first.iloc[0]["clean_value"] == 182.75
    second = confirm_candidates(cands, fetch, root=tmp_path)
    assert len(calls) == 1 and len(second) == 1
    assert checks_path(tmp_path).exists()


def test_rewrite_applies_decisions_and_normalizes_schema(tmp_path):
    seed(tmp_path)
    cands = scan_candidates(tmp_path, symbols=["SYM"], workers=1)
    checks = confirm_candidates(cands, fake_trades, root=tmp_path)
    summary = rewrite_clean_columns(checks, root=tmp_path, symbols=["SYM"], workers=1)
    assert summary == {"files": 2, "flags": 1}
    wick = pd.read_parquet(day_path(tmp_path, "SYM", DAY))
    assert list(wick.columns) == STOCK_COLUMNS
    row = wick[wick["ts"] == WICK_TS].iloc[0]
    assert row["bad_low"] and row["low_clean"] == 182.75 and row["low"] == 153.12
    legacy = pd.read_parquet(day_path(tmp_path, "SYM", date(2023, 2, 2)))
    assert list(legacy.columns) == STOCK_COLUMNS


def test_rebuild_clean_end_to_end_with_mock_alpaca(tmp_path):
    seed(tmp_path)

    def handler(request):
        assert request.url.path == "/v2/stocks/trades"
        return httpx.Response(200, json={"trades": {"SYM": [
            {"t": "2023-02-01T21:15:01Z", "p": 182.75, "s": 100, "x": "V", "c": ["@", "T"]},
            {"t": "2023-02-01T21:15:02Z", "p": 153.12, "s": 100000, "x": "D", "c": ["@", "T"]},
        ]}, "next_page_token": None})

    client = AlpacaDataClient(key="k", secret="s", http=httpx.Client(transport=httpx.MockTransport(handler)),
                              limiter=RateLimiter(1000), sleep=lambda s: None)
    summary = rebuild_clean(client, phase="all", root=tmp_path, symbols=["SYM"], workers=1)
    assert summary["candidates"] == 1 and summary["isolated"] == 1 and summary["flags"] == 1
    row = pd.read_parquet(day_path(tmp_path, "SYM", DAY)).set_index("ts").loc[WICK_TS]
    assert row["low_clean"] == 182.75
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/options_research/test_print_checks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.options_research.print_checks'`

- [ ] **Step 3: Implement `print_checks.py`**

Create `src/options_research/print_checks.py`:

```python
"""Rebuild bad-print flags and clean columns across the stock lake (spec §5.1).

Data-maintenance exception to the holdout guard (spec §9.1): reads and rewrites lake day files for all dates
(including the holdout period) and computes no signals or strategy metrics.
Phases: scan (offline, parallel) -> confirm (Alpaca SIP trades, resumable) -> rewrite (offline, parallel).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd

from src.options_research.config import UNIVERSE, lake_root
from src.options_research.quality import apply_clean, classify_print, find_print_candidates
from src.options_research.stocks import STOCK_COLUMNS

CANDIDATES_COLUMNS = ["symbol", "session_date", "ts", "side", "extreme", "reference", "band"]
CHECK_COLUMNS = CANDIDATES_COLUMNS + ["decision", "n_trades", "n_outliers", "outlier_prices", "outlier_exchanges", "outlier_conditions", "clean_value"]
PHASES = ("all", "scan", "confirm", "rewrite")


def candidates_path(root: Path) -> Path:
    return root / "quality" / "print_candidates.parquet"


def checks_path(root: Path) -> Path:
    return root / "quality" / "print_checks.parquet"


def lake_day_files(root: Path, symbols: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for symbol in symbols:
        files.extend(sorted((root / "stock_1m" / symbol).glob("*/*.parquet")))
    return files


def _scan_file(path: Path) -> pd.DataFrame:
    day = pd.read_parquet(path, columns=["ts", "open", "high", "low", "close"])
    candidates = find_print_candidates(day)
    if candidates.empty:
        return pd.DataFrame(columns=CANDIDATES_COLUMNS)
    candidates.insert(0, "session_date", date.fromisoformat(path.stem))
    candidates.insert(0, "symbol", path.parent.parent.name)
    return candidates[CANDIDATES_COLUMNS]


def _map(func, items: list, workers: int) -> list:
    if workers <= 1:
        return [func(item) for item in items]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(func, items, chunksize=32))


def scan_candidates(root: Path | None = None, symbols: Iterable[str] = UNIVERSE, workers: int = 4) -> pd.DataFrame:
    root = root or lake_root()
    parts = [p for p in _map(_scan_file, lake_day_files(root, symbols), workers) if not p.empty]
    candidates = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=CANDIDATES_COLUMNS)
    path = candidates_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_parquet(path, index=False)
    return candidates


def _key(symbol: str, ts, side: str) -> tuple[str, pd.Timestamp, str]:
    return symbol, pd.Timestamp(ts).tz_convert("UTC"), side


def _write_checks(existing: pd.DataFrame, rows: list[dict], path: Path) -> pd.DataFrame:
    if not rows:
        combined = existing
    else:
        new = pd.DataFrame(rows, columns=CHECK_COLUMNS)
        combined = new if existing.empty else pd.concat([existing, new], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)
    return combined


def confirm_candidates(
    candidates: pd.DataFrame,
    fetch_trades: Callable[[str, pd.Timestamp], list[dict]],
    root: Path | None = None,
    flush_every: int = 100,
) -> pd.DataFrame:
    root = root or lake_root()
    path = checks_path(root)
    existing = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=CHECK_COLUMNS)
    done = {_key(s, t, side) for s, t, side in zip(existing["symbol"], existing["ts"], existing["side"])}
    rows: list[dict] = []
    trade_cache: dict[tuple[str, pd.Timestamp], list[dict]] = {}
    for candidate in candidates.itertuples(index=False):
        key = _key(candidate.symbol, candidate.ts, candidate.side)
        if key in done:
            continue
        minute = (key[0], key[1])
        if minute not in trade_cache:
            trade_cache[minute] = fetch_trades(key[0], key[1])
        result = classify_print(trade_cache[minute], candidate.side, float(candidate.reference), float(candidate.band))
        rows.append({
            "symbol": candidate.symbol, "session_date": candidate.session_date, "ts": key[1], "side": candidate.side,
            "extreme": float(candidate.extreme), "reference": float(candidate.reference), "band": float(candidate.band),
            **result,
        })
        done.add(key)
        if len(rows) >= flush_every:
            existing = _write_checks(existing, rows, path)
            rows = []
    return _write_checks(existing, rows, path)


def _rewrite_file(job: tuple[Path, pd.DataFrame | None]) -> int:
    path, checks = job
    day = pd.read_parquet(path)
    cleaned = apply_clean(day.drop(columns=["bad_close"], errors="ignore"), checks)
    cleaned[STOCK_COLUMNS].to_parquet(path, index=False)
    return int(cleaned["bad_high"].sum() + cleaned["bad_low"].sum())


def rewrite_clean_columns(
    checks: pd.DataFrame,
    root: Path | None = None,
    symbols: Iterable[str] = UNIVERSE,
    workers: int = 4,
) -> dict:
    root = root or lake_root()
    by_file: dict[tuple[str, str], pd.DataFrame] = {}
    if not checks.empty:
        for (symbol, session_date), group in checks.groupby(["symbol", "session_date"]):
            by_file[(symbol, str(pd.Timestamp(session_date).date()))] = group[["ts", "side", "decision", "clean_value"]].reset_index(drop=True)
    files = lake_day_files(root, symbols)
    jobs = [(f, by_file.get((f.parent.parent.name, f.stem))) for f in files]
    flags = _map(_rewrite_file, jobs, workers)
    return {"files": len(files), "flags": int(sum(flags))}


def rebuild_clean(
    client,
    phase: str = "all",
    root: Path | None = None,
    symbols: Iterable[str] = UNIVERSE,
    workers: int = 4,
) -> dict:
    from src.options_research.stocks_alpaca import fetch_minute_trades

    if phase not in PHASES:
        raise ValueError(f"phase must be one of {PHASES}")
    root = root or lake_root()
    symbols = tuple(symbols)
    summary: dict = {"phase": phase}
    if phase in ("all", "scan"):
        candidates = scan_candidates(root, symbols, workers)
    else:
        candidates = pd.read_parquet(candidates_path(root))
    summary["candidates"] = int(len(candidates))
    if phase == "scan":
        return summary
    if phase in ("all", "confirm"):
        checks = confirm_candidates(candidates, lambda s, ts: fetch_minute_trades(client, s, ts), root=root)
    else:
        checks = pd.read_parquet(checks_path(root))
    current = {_key(s, t, side) for s, t, side in zip(candidates["symbol"], candidates["ts"], candidates["side"])}
    checks = checks[[_key(s, t, side) in current for s, t, side in zip(checks["symbol"], checks["ts"], checks["side"])]]
    summary.update({k: int(v) for k, v in checks["decision"].value_counts().items()})
    summary["checked"] = int(len(checks))
    if phase == "confirm":
        return summary
    summary.update(rewrite_clean_columns(checks, root, symbols, workers))
    return summary
```

- [ ] **Step 4: Add the CLI command**

In `src/options_research/cli.py`, add after `_cmd_report_m2`:

```python
def _cmd_rebuild_clean(args: argparse.Namespace) -> int:
    from src.options_research.alpaca_data import AlpacaDataClient
    from src.options_research.print_checks import rebuild_clean

    client = AlpacaDataClient() if args.phase in ("all", "confirm") else None
    print(json.dumps(rebuild_clean(client, phase=args.phase, workers=args.workers), default=str))
    return 0
```

and in `main`, before `args = parser.parse_args(argv)`:

```python
    p = sub.add_parser("rebuild-clean", help="bad-print candidates -> Alpaca trade confirmation -> rewrite clean columns")
    p.add_argument("--phase", choices=["all", "scan", "confirm", "rewrite"], default="all")
    p.add_argument("--workers", type=int, default=4)
    p.set_defaults(func=_cmd_rebuild_clean)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/options_research/test_print_checks.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/options_research/print_checks.py src/options_research/cli.py tests/options_research/test_print_checks.py
git commit -F- <<'EOF'
feat(options_research): resumable rebuild-clean job (scan, trade confirmation, rewrite) with audit file

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 4: Reports — new adjustments table, UTC timestamps, print-checks section

**Files:**
- Modify: `src/options_research/reports.py:29-92`
- Modify: `tests/options_research/test_reports_cli.py`

**Interfaces:**
- Consumes: `print_checks.checks_path`
- Produces:
  - `_largest_bad_print_adjustments(root)` with columns `symbol, session_date, ts, high, high_clean, low, low_clean, close, volume, transactions, excluded, adjustment`
  - an M1 section `## Print checks (trade-level confirmation)`

- [ ] **Step 1: Update the tests (RED)**

In `tests/options_research/test_reports_cli.py`:
- Delete `"bad_close": [False, False],` from both seed dicts (currently lines 18 and 49).
- In `test_m1_report_sections`, add these assertions:

```python
    assert "## Print checks (trade-level confirmation)" in text
    assert "Not run." in text  # no audit file seeded
    assert "+00:00" in text  # adjustments table ts rendered in UTC
```

- Append:

```python
def test_m1_report_summarizes_print_checks(tmp_path):
    from src.options_research.print_checks import CHECK_COLUMNS, checks_path

    seed_lake(tmp_path)
    checks = pd.DataFrame([{
        "symbol": "META", "session_date": pd.Timestamp("2023-02-01").date(), "ts": pd.Timestamp("2023-02-01T23:15:00Z"),
        "side": "low", "extreme": 153.12, "reference": 182.99, "band": 5.49, "decision": "isolated", "n_trades": 151,
        "n_outliers": 1, "outlier_prices": [153.12], "outlier_exchanges": ["D"], "outlier_conditions": ["@,T"], "clean_value": 182.75,
    }], columns=CHECK_COLUMNS)
    checks_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    checks.to_parquet(checks_path(tmp_path), index=False)
    text = m1_report(root=tmp_path)
    section = text.split("## Print checks (trade-level confirmation)")[1].split("## Splits")[0]
    assert "isolated" in section and "2023" in section
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/options_research/test_reports_cli.py -v`
Expected: FAIL. The query references the removed `bad_close` column and the new section is missing.

- [ ] **Step 3: Implement**

In `src/options_research/reports.py`:
- Add the import `from src.options_research.print_checks import checks_path`.
- In `_stock_aggregates`, add `con.execute("SET TimeZone='UTC'")` right after `con = duckdb.connect()` inside the `try`, and change `read_parquet('{pattern}', filename=true)` to `read_parquet('{pattern}', filename=true, union_by_name=true)`.
- Replace `_largest_bad_print_adjustments` with:

```python
def _largest_bad_print_adjustments(root: Path) -> pd.DataFrame:
    pattern = (root / "stock_1m" / "*" / "*" / "*.parquet").as_posix()
    columns = ["symbol", "session_date", "ts", "high", "high_clean", "low", "low_clean", "close", "volume", "transactions", "excluded", "adjustment"]
    if not list((root / "stock_1m").glob("*/*/*.parquet")):
        return pd.DataFrame(columns=columns)
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        # Data-validation/report exception to the holdout guard (spec §9.1): aggregates only, no strategy metrics.
        return con.execute(
            f"""
            SELECT symbol, {_SESSION_DATE_FROM_FILENAME} AS session_date, ts, high, high_clean, low, low_clean,
                   close, volume, transactions,
                   (high_clean IS NULL OR low_clean IS NULL) AS excluded,
                   greatest(coalesce(high - high_clean, 0), coalesce(low_clean - low, 0)) AS adjustment
            FROM read_parquet('{pattern}', filename=true, union_by_name=true)
            WHERE bad_high OR bad_low
            ORDER BY excluded DESC, adjustment DESC
            LIMIT 20
            """
        ).df()
    finally:
        con.close()
```

- In `m1_report`, directly after the "Largest bad-print adjustments" block (before `lines += ["## Splits", ""]`), add:

```python
    lines += ["## Print checks (trade-level confirmation)", ""]
    audit = checks_path(root)
    if audit.exists():
        # Data-validation/report exception to the holdout guard (spec §9.1): aggregates only, no strategy metrics.
        checks = pd.read_parquet(audit)
        years = pd.to_datetime(checks["session_date"]).dt.year
        lines.append(f"- candidates checked: {len(checks)}")
        lines.append("- isolated print = at most 3 trades beyond the band, all reported off-exchange (code D); clean value = most extreme in-band traded price; other candidates keep raw values")
        lines += ["", checks.groupby(["decision", years]).size().unstack(fill_value=0).to_markdown()]
    else:
        lines.append("Not run.")
    lines.append("")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.local/bin/uv run pytest tests/options_research/test_reports_cli.py -v`
Expected: all pass.

Run: `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py`
Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add src/options_research/reports.py tests/options_research/test_reports_cli.py
git commit -F- <<'EOF'
feat(options_research): M1 report shows trade-confirmed print checks; UTC timestamps restored

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 5: Split volume-adjustment helper and loader-only data-access guard

**Files:**
- Modify: `src/options_research/corporate_actions.py` (after `adjustment_factors`)
- Modify: `tests/options_research/test_corporate_actions.py`
- Create: `tests/options_research/test_data_access.py`

**Interfaces:**
- Produces: `volume_adjustment_factors(splits: pd.DataFrame, symbol: str, days: pd.Series) -> pd.Series`
  (adjusted volume = raw volume × factor)

- [ ] **Step 1: Write the failing tests**

Append to `tests/options_research/test_corporate_actions.py` (and add `volume_adjustment_factors` to its import list):

```python
def test_volume_adjustment_factor_is_reciprocal_before_split_day():
    splits = pd.DataFrame([{"symbol": "NVDA", "day": date(2024, 6, 10), "ratio": 10.0, "factor": 0.1}])
    days = pd.Series([date(2024, 6, 7), date(2024, 6, 10), date(2024, 6, 11)])
    assert volume_adjustment_factors(splits, "NVDA", days).tolist() == pytest.approx([10.0, 1.0, 1.0])
    assert volume_adjustment_factors(splits, "AAPL", days).tolist() == [1.0, 1.0, 1.0]
```

(Add `import pytest` at the top if it isn't imported.)

Create `tests/options_research/test_data_access.py`:

```python
"""Feature code must read lake data only through approved modules (spec §11 M3-0)."""

from pathlib import Path

import src.options_research as pkg

PACKAGE = Path(pkg.__file__).parent
PARQUET_READERS = {"store.py", "reports.py", "stocks_alpaca.py", "corporate_actions.py", "costs.py", "events_sources.py", "print_checks.py"}
STOCK_LAKE_TOUCHERS = {"stocks.py", "store.py", "reports.py", "print_checks.py"}


def _sources():
    return {p.name: p.read_text(encoding="utf-8") for p in PACKAGE.glob("*.py")}


def test_only_approved_modules_read_parquet():
    offenders = sorted(name for name, text in _sources().items() if "read_parquet(" in text and name not in PARQUET_READERS)
    assert offenders == [], f"read lake data through store.load_stock_minutes instead: {offenders}"


def test_only_approved_modules_touch_the_stock_lake_path():
    offenders = sorted(name for name, text in _sources().items() if '"stock_1m"' in text and name not in STOCK_LAKE_TOUCHERS)
    assert offenders == [], f"stock minutes must be read via store.load_stock_minutes: {offenders}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `~/.local/bin/uv run pytest tests/options_research/test_corporate_actions.py tests/options_research/test_data_access.py -v`
Expected: `test_corporate_actions.py` FAILs on the import (`volume_adjustment_factors`); `test_data_access.py` passes already (it guards future code). Report both.

- [ ] **Step 3: Implement**

In `src/options_research/corporate_actions.py`, after `adjustment_factors`:

```python
def volume_adjustment_factors(splits: pd.DataFrame, symbol: str, days: pd.Series) -> pd.Series:
    """Multiply raw volumes by this factor to express pre-split volume in post-split shares."""
    return 1.0 / adjustment_factors(splits, symbol, days)
```

- [ ] **Step 4: Run tests**

Run: `~/.local/bin/uv run pytest tests/options_research/test_corporate_actions.py tests/options_research/test_data_access.py -v` → all pass.
Run: `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py` → 0 failures.

- [ ] **Step 5: Commit**

```bash
git add src/options_research/corporate_actions.py tests/options_research/test_corporate_actions.py tests/options_research/test_data_access.py
git commit -F- <<'EOF'
feat(options_research): split volume-adjustment helper; guard loader-only lake access

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 6: Rebuild the lake's clean columns, integration checks, report, docs

**Files:**
- Modify: `tests/options_research/test_integration_data.py` (append tests)
- Modify: `CLAUDE.md` (replace the provisional warning paragraph)
- Regenerate: `reports/options_research/m1_data_foundation.md`

**Interfaces:**
- Consumes: CLI `rebuild-clean`, `report-m1`; `store.load_stock_minutes`

**Preconditions:** `.env` has `ALPACA_DATA_API_KEY`, `ALPACA_DATA_SECRET_KEY` (present). The lake is
populated (15,670 day files). Your shell tool times out at 10 minutes per command. Run each phase as
a separate command; `confirm` is resumable, so if it times out, re-run the same command.

- [ ] **Step 1: Append the integration tests**

Append to `tests/options_research/test_integration_data.py`:

```python
def _bar(symbol, iso_ts):
    import pandas as pd

    from src.options_research.store import load_stock_minutes

    ts = pd.Timestamp(iso_ts)
    day = ts.tz_convert("America/New_York").date()
    minutes = load_stock_minutes([symbol], day, day)
    return minutes[minutes["ts"] == ts].iloc[0]


def test_clean_values_never_outside_raw_bar():
    import duckdb

    pattern = (lake_root() / "stock_1m" / "*" / "*" / "*.parquet").as_posix()
    con = duckdb.connect()
    bad = con.execute(
        f"SELECT count(*) FROM read_parquet('{pattern}', union_by_name=true) "
        "WHERE high_clean > high + 1e-9 OR low_clean < low - 1e-9 OR low_clean > high_clean + 1e-9"
    ).fetchone()[0]
    assert bad == 0


def test_known_isolated_prints_are_cleaned():
    meta = _bar("META", "2023-02-01T23:15:00Z")
    assert meta["bad_low"] and abs(meta["low_clean"] - 182.75) <= 0.02
    googl = _bar("GOOGL", "2024-04-25T22:54:00Z")
    assert googl["bad_low"] and abs(googl["low_clean"] - 174.80) <= 0.02
    qqq = _bar("QQQ", "2022-05-09T18:58:00Z")
    assert qqq["bad_high"] and abs(qqq["high_clean"] - 299.67) <= 0.02
    iwm = _bar("IWM", "2023-03-17T21:53:00Z")
    assert iwm["bad_high"] and abs(iwm["high_clean"] - 171.77) <= 0.02


def test_genuine_moves_keep_raw_values():
    meta = _bar("META", "2022-04-27T17:01:00Z")
    assert not meta["bad_low"] and meta["low_clean"] == meta["low"] == 169.0
    amzn = _bar("AMZN", "2022-10-27T20:01:00Z")
    assert not amzn["bad_low"] and not amzn["bad_high"]
    assert amzn["low_clean"] == amzn["low"] and amzn["high_clean"] == amzn["high"]
```

- [ ] **Step 2: Run the rebuild, one phase per command**

```bash
PYTHONIOENCODING=utf-8 ~/.local/bin/uv run python -m src.options_research rebuild-clean --phase scan --workers 4
PYTHONIOENCODING=utf-8 ~/.local/bin/uv run python -m src.options_research rebuild-clean --phase confirm
PYTHONIOENCODING=utf-8 ~/.local/bin/uv run python -m src.options_research rebuild-clean --phase rewrite --workers 4
```

Expected:
- **scan:** `{"phase": "scan", "candidates": ~1000}` (the dry run found 1,026).
- **confirm:** decision counts `isolated`, `genuine`, and possibly `no_outlier_trades`/`no_trades`.
- **rewrite:** `"files": 15670` and `"flags"` equal to the isolated count.

Pass the tool timeout 600000 ms for each command. If `confirm` times out, re-run it (it resumes).

- [ ] **Step 3: Run the integration tests**

Run: `~/.local/bin/uv run pytest -m integration tests/options_research -v`
Expected: all pass (the existing 5 + 3 new).

If a probe assertion fails, do NOT change the expected numbers. Report the bar's raw OHLC, its
audit row from `data/options_lake/quality/print_checks.parquet`, and the classification inputs.

- [ ] **Step 4: Regenerate the M1 report**

Run: `PYTHONIOENCODING=utf-8 ~/.local/bin/uv run python -m src.options_research report-m1`
Check:
- the "Print checks" section shows decision counts by year
- the adjustments table has `+00:00` timestamps
- the adjustments table shows no `bad_close` column

- [ ] **Step 5: Update CLAUDE.md**

In `CLAUDE.md`, replace the paragraph that starts with `**Do not use \`high_clean\`/\`low_clean\` for features yet.**` (it ends with `Use raw OHLC until then.`) with:

```markdown
**Clean columns are hindsight values.** `rebuild-clean` flags only isolated off-market prints (≤3
off-exchange trades beyond a two-sided band, confirmed from Alpaca SIP trades) and sets
`high_clean`/`low_clean` to the most extreme in-band traded price. Use clean columns only for values
read after the window closes (prior-day high/low/close, ATR history, pre-market high/low at or after
09:30). Intraday regular-hours features use raw OHLC. Run
`uv run python -m src.options_research rebuild-clean` (phases `scan`, `confirm`, `rewrite`) after
any new ingest; the audit trail is in `data/options_lake/quality/print_checks.parquet`.
```

- [ ] **Step 6: Run the full unit suite once more**

Run: `~/.local/bin/uv run pytest -q --ignore=tests/test_api_rate_limiting.py`
Expected: 0 failures.

- [ ] **Step 7: Commit**

```bash
git add tests/options_research/test_integration_data.py CLAUDE.md reports/options_research/m1_data_foundation.md
git commit -F- <<'EOF'
chore(options_research): rebuild trade-confirmed clean columns; integration probes; M1 report; CLAUDE.md

Co-Authored-By: <your actual model name> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

- [ ] **Step 8: Hand back**

Report to the controller:
- the three phase summaries
- decision counts
- integration test output
- 3–5 sample isolated and genuine rows from the audit file
- any unexpected decisions (e.g. a known bad print classified `genuine`, or `no_trades` counts)
