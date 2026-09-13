"""Lake loaders with the holdout guard (spec §9.1)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from src.options_research.config import HOLDOUT, lake_root
from src.options_research.stocks import STOCK_COLUMNS

HINDSIGHT_COLUMNS = ["bad_high", "bad_low", "high_clean", "low_clean"]


class HoldoutAccessError(RuntimeError):
    """Raised when a range touching the holdout is requested without holdout=True."""


def guard_period(start: date, end: date, holdout: bool) -> None:
    if start > end:
        raise ValueError(f"reversed date range: start {start} is after end {end}")
    if not holdout and end >= HOLDOUT[0]:
        raise HoldoutAccessError(
            f"{start}..{end} overlaps the holdout starting {HOLDOUT[0]}; pass holdout=True only for "
            "data validation, split detection, cost calibration, or the frozen holdout run"
        )


def stock_minute_files(symbols: Iterable[str], start: date, end: date, root: Path | None = None) -> list[Path]:
    base = (root or lake_root()) / "stock_1m"
    files: list[Path] = []
    for symbol in symbols:
        for year in range(start.year, end.year + 1):
            year_dir = base / symbol / str(year)
            if not year_dir.exists():
                continue
            files.extend(p for p in sorted(year_dir.glob("*.parquet")) if start <= date.fromisoformat(p.stem) <= end)
    return files


def load_stock_minutes(
    symbols: Iterable[str],
    start: date,
    end: date,
    holdout: bool = False,
    root: Path | None = None,
    clean: bool = False,
) -> pd.DataFrame:
    """Load lake minute bars for `symbols` over [start, end] (inclusive), sorted by symbol then ts (UTC).

    `bad_high`/`bad_low`/`high_clean`/`low_clean` are hindsight columns (spec §5.1): they are computed from
    bars *after* each bar (a centered window plus a snap-back check), so the value at bar i can depend on
    bars that come later in the session. Pass `clean=True` to include them, and only to read a level once
    the relevant window has closed (e.g. prior-day high/low, ATR history, or a pre-market high/low read
    at/after 09:37, when the last pre-market bar's window is complete). Prior-day close is the raw close.
    Intraday features must use raw OHLC and should leave `clean=False` (the default).
    """
    guard_period(start, end, holdout)
    columns = [c for c in STOCK_COLUMNS if clean or c not in HINDSIGHT_COLUMNS]
    files = stock_minute_files(symbols, start, end, root=root)
    if not files:
        return pd.DataFrame(columns=columns)
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        frame = con.read_parquet([p.as_posix() for p in files], union_by_name=True).order("symbol, ts").df()
    finally:
        con.close()
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame[columns].reset_index(drop=True)
