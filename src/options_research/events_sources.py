"""FRED macro release dates, yfinance earnings dates, and the combined events table (spec §5.2)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

from src.options_research.config import ETFS, TZ_ET, UNIVERSE, lake_root
from src.options_research.events_rules import EVENT_COLUMNS, fomc_events, make_event, rule_events
from src.options_research.market_calendar import get_session, next_session_on_or_after

FRED_URL = "https://api.stlouisfed.org/fred/release/dates"
FRED_RELEASES: dict[int, tuple[str, str, str]] = {
    10: ("cpi", "1", "08:30"),
    50: ("employment_situation", "1", "08:30"),
    46: ("ppi", "2", "08:30"),
    54: ("personal_income_outlays", "2", "08:30"),
    53: ("gdp", "2", "08:30"),
    9: ("retail_sales", "2", "08:30"),
    192: ("jolts", "2", "10:00"),
}


def fred_release_events(api_key: str, start: date, end: date, http: httpx.Client | None = None) -> list[dict]:
    owns_http = http is None
    http = http or httpx.Client(timeout=30)
    try:
        events: list[dict] = []
        for release_id, (type_, tier, time_et) in FRED_RELEASES.items():
            response = http.get(FRED_URL, params={
                "release_id": release_id,
                "api_key": api_key,
                "file_type": "json",
                "include_release_dates_with_no_data": "false",
                "limit": 10000,
            })
            if not (200 <= response.status_code < 300):
                # No URL or key in the message: the URL carries api_key as a query param.
                raise RuntimeError(f"FRED release dates request failed for release {release_id}: HTTP {response.status_code}")
            for item in response.json()["release_dates"]:
                day = date.fromisoformat(item["date"])
                if start <= day <= end and get_session(day) is not None:
                    events.append(make_event(day, time_et, type_, tier, "fred"))
        return events
    finally:
        if owns_http:
            http.close()


def _yfinance_earnings(ticker: str) -> pd.DataFrame:
    import yfinance as yf

    return yf.Ticker(ticker).get_earnings_dates(limit=40)


def earnings_events(
    tickers: Iterable[str],
    start: date,
    end: date,
    fetch: Callable[[str], pd.DataFrame] | None = None,
) -> list[dict]:
    fetch = fetch or _yfinance_earnings
    events: list[dict] = []
    for ticker in tickers:
        if ticker in ETFS:
            continue
        frame = fetch(ticker)
        if frame is None or frame.empty:
            continue
        for stamp in frame.index:
            stamp = pd.Timestamp(stamp)
            stamp_et = stamp.tz_convert(TZ_ET) if stamp.tzinfo else stamp.tz_localize(TZ_ET)
            # Ruling R6: Skip stamps outside the calendar range before checking the session
            if not (start - timedelta(days=7) <= stamp_et.date() <= end + timedelta(days=7)):
                continue
            if stamp_et.hour < 12:
                impact, type_ = stamp_et.date(), "earnings_bmo"
            else:
                impact, type_ = next_session_on_or_after(stamp_et.date() + timedelta(days=1)), "earnings_amc"
            if start <= impact <= end and get_session(impact) is not None:
                events.append(make_event(impact, None, type_, "earnings", "yfinance", ticker=ticker))
    return events


def build_events(
    start: date,
    end: date,
    fred_api_key: str | None,
    earnings_fetch: Callable[[str], pd.DataFrame] | None = None,
    http: httpx.Client | None = None,
) -> tuple[pd.DataFrame, dict]:
    rows = rule_events(start, end) + fomc_events(start, end)
    notes: dict = {"start": start.isoformat(), "end": end.isoformat()}
    if fred_api_key:
        rows += fred_release_events(fred_api_key, start, end, http=http)
        notes["fred"] = "included"
    else:
        notes["fred"] = "skipped: FRED_API_KEY not set"
    rows += earnings_events(UNIVERSE, start, end, fetch=earnings_fetch)
    frame = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    frame = (
        frame.assign(_t=frame["time_et"].fillna(""), _k=frame["ticker"].fillna(""))
        .sort_values(["date", "_t", "type", "_k"], kind="stable")
        .drop(columns=["_t", "_k"])
        .reset_index(drop=True)
    )
    return frame, notes


def write_events(df: pd.DataFrame, notes: dict, root: Path | None = None) -> Path:
    folder = (root or lake_root()) / "calendar"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "events.parquet"
    df.to_parquet(path, index=False)
    (folder / "events_notes.json").write_text(json.dumps(notes, indent=2), encoding="utf-8")
    return path


def load_events(root: Path | None = None) -> pd.DataFrame:
    return pd.read_parquet((root or lake_root()) / "calendar" / "events.parquet")
