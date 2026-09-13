"""Lake loaders with the holdout guard (spec §9.1)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from src.options_research.config import HOLDOUT, lake_root
from src.options_research.stocks import STOCK_COLUMNS


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
) -> pd.DataFrame:
    guard_period(start, end, holdout)
    files = stock_minute_files(symbols, start, end, root=root)
    if not files:
        return pd.DataFrame(columns=STOCK_COLUMNS)
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        frame = con.read_parquet([p.as_posix() for p in files], union_by_name=True).order("symbol, ts").df()
    finally:
        con.close()
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame[STOCK_COLUMNS].reset_index(drop=True)
