"""Alpaca SIP 1-minute stock bars for the post-zip tail, plus zip-vs-Alpaca validation (spec §5.1, §5.7)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timezone
from pathlib import Path

import pandas as pd

from src.options_research.alpaca_data import AlpacaDataClient
from src.options_research.config import UNIVERSE, lake_root
from src.options_research.market_calendar import ET, sessions_between
from src.options_research.stocks import (
    day_path,
    is_day_done,
    mark_day_done,
    normalize_minutes,
    write_day,
)

STOCK_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
_RTH_START_MINUTE = 9 * 60 + 30   # 09:30 ET
_RTH_END_MINUTE = 16 * 60         # 16:00 ET (exclusive)


def _utc_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_alpaca_day(client: AlpacaDataClient, tickers: Iterable[str], day: date) -> pd.DataFrame:
    params = {
        "symbols": ",".join(tickers),
        "timeframe": "1Min",
        "start": _utc_z(datetime.combine(day, time(4, 0), ET)),
        "end": _utc_z(datetime.combine(day, time(20, 0), ET)),
        "feed": "sip",
        "adjustment": "raw",
        "limit": 10000,
    }
    rows = []
    for page in client.paginate(STOCK_BARS_URL, params):
        for symbol, bars in (page.get("bars") or {}).items():
            for b in bars:
                rows.append({
                    "symbol": symbol, "ts": b["t"], "open": b["o"], "high": b["h"], "low": b["l"],
                    "close": b["c"], "volume": b["v"], "transactions": b.get("n", 0),
                })
    raw = pd.DataFrame(rows, columns=["symbol", "ts", "open", "high", "low", "close", "volume", "transactions"])
    raw["ts"] = pd.to_datetime(raw["ts"], utc=True)
    return normalize_minutes(raw, source="alpaca")


def ingest_alpaca_tail(
    client: AlpacaDataClient,
    start: date,
    end: date,
    tickers: Iterable[str] = UNIVERSE,
    root: Path | None = None,
    overwrite: bool = False,
) -> dict:
    root = root or lake_root()
    tickers = tuple(tickers)
    sessions = sessions_between(start, end)
    written = rows = 0
    for session in sessions:
        # R7: Use is_day_done instead of checking file existence
        if not overwrite and is_day_done(root, session.day, tickers):
            continue
        rows_written = write_day(fetch_alpaca_day(client, tickers, session.day), session.day, root)
        # R7: Mark day as done after writing
        mark_day_done(root, session.day, tickers, rows_written)
        rows += rows_written
        written += 1
    return {"sessions": len(sessions), "days_written": written, "days_skipped": len(sessions) - written, "rows": rows}


def compare_sources(zip_df: pd.DataFrame, alpaca_df: pd.DataFrame) -> dict:
    keys = ["symbol", "ts"]
    cols = ["open", "high", "low", "close", "volume"]
    merged = zip_df[keys + cols].merge(alpaca_df[keys + cols], on=keys, how="outer", suffixes=("_zip", "_alp"), indicator=True)
    both = merged[merged["_merge"] == "both"]
    ohlc_diff = pd.Series(False, index=both.index)
    row_max_abs_diff = pd.Series(0.0, index=both.index)
    for col in ("open", "high", "low", "close"):
        zip_col = both[f"{col}_zip"].astype(float)
        alp_col = both[f"{col}_alp"].astype(float)
        ohlc_diff |= zip_col.round(4) != alp_col.round(4)
        row_max_abs_diff = pd.concat([row_max_abs_diff, (zip_col - alp_col).abs()], axis=1).max(axis=1)
    close_zip = both["close_zip"].astype(float)
    close_alp = both["close_alp"].astype(float)
    close_mismatch = close_zip.round(4) != close_alp.round(4)
    max_abs_diff_pct = float((row_max_abs_diff / close_zip).max()) if len(both) else 0.0
    return {
        "compared": int(len(both)),
        "ohlc_mismatch": int(ohlc_diff.sum()),
        "volume_mismatch": int((both["volume_zip"].astype("int64") != both["volume_alp"].astype("int64")).sum()),
        "zip_only": int((merged["_merge"] == "left_only").sum()),
        "alpaca_only": int((merged["_merge"] == "right_only").sum()),
        "close_mismatch": int(close_mismatch.sum()),
        "max_abs_diff_pct": max_abs_diff_pct,
    }


def _rth_only(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to regular-session bars (09:30 ET <= minute-of-day < 16:00 ET)."""
    if df.empty:
        return df
    et = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(ET)
    minute_of_day = et.dt.hour * 60 + et.dt.minute
    return df[(minute_of_day >= _RTH_START_MINUTE) & (minute_of_day < _RTH_END_MINUTE)]


def validate_zip_overlap(
    client: AlpacaDataClient,
    days: Iterable[date],
    tickers: Iterable[str] = UNIVERSE,
    root: Path | None = None,
) -> dict[str, dict]:
    # Data-validation exception to the holdout guard (spec §9.1): reads lake files directly, computes no strategy metrics.
    root = root or lake_root()
    tickers = tuple(tickers)
    results: dict[str, dict] = {}
    for day in days:
        files = [day_path(root, t, day) for t in tickers if day_path(root, t, day).exists()]
        zip_df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame(columns=["symbol", "ts", "open", "high", "low", "close", "volume"])
        alpaca_df = fetch_alpaca_day(client, tickers, day)
        result = compare_sources(zip_df, alpaca_df)
        rth_result = compare_sources(_rth_only(zip_df), _rth_only(alpaca_df))
        result.update({f"rth_{key}": value for key, value in rth_result.items()})
        results[day.isoformat()] = result
    return results
