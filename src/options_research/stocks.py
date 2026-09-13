"""Ingest 1-minute stock bars from the Polygon/Massive flat-file zip into the lake (spec §5.1)."""

from __future__ import annotations

import gzip
import zipfile
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd

from src.options_research.config import TZ_ET, UNIVERSE, lake_root
from src.options_research.quality import flag_bad_prints

MINUTE_COLUMNS = ["ticker", "volume", "open", "close", "high", "low", "window_start", "transactions"]
RAW_COLUMNS = ["symbol", "ts", "open", "high", "low", "close", "volume", "transactions"]
STOCK_COLUMNS = RAW_COLUMNS + ["bad_high", "bad_low", "bad_close", "high_clean", "low_clean", "source"]
_FIRST_MINUTE = 4 * 60    # 04:00 ET
_END_MINUTE = 20 * 60     # 20:00 ET (exclusive)


def normalize_minutes(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=STOCK_COLUMNS)
    et = raw["ts"].dt.tz_convert(TZ_ET)
    minute_of_day = et.dt.hour * 60 + et.dt.minute
    kept = raw.loc[(minute_of_day >= _FIRST_MINUTE) & (minute_of_day < _END_MINUTE), RAW_COLUMNS]
    parts = [flag_bad_prints(group.reset_index(drop=True)) for _, group in kept.sort_values(["symbol", "ts"]).groupby("symbol", sort=True)]
    if not parts:
        return pd.DataFrame(columns=STOCK_COLUMNS)
    out = pd.concat(parts, ignore_index=True)
    out["volume"] = out["volume"].astype("int64")
    out["transactions"] = out["transactions"].fillna(0).astype("int64")
    out["source"] = source
    return out[STOCK_COLUMNS]


def zip_minute_members(zip_path: Path) -> dict[date, str]:
    with zipfile.ZipFile(zip_path) as zf:
        return {
            date.fromisoformat(name.rsplit("/", 1)[1][:10]): name
            for name in zf.namelist()
            if name.startswith("minute_aggs/") and name.endswith(".csv.gz")
        }


def read_zip_day(zip_path: Path, member: str, tickers: Iterable[str]) -> pd.DataFrame:
    wanted = set(tickers)
    with zipfile.ZipFile(zip_path) as zf, zf.open(member) as raw, gzip.GzipFile(fileobj=raw) as gz:
        frame = pd.read_csv(gz, usecols=MINUTE_COLUMNS, dtype={"ticker": "string"})
    frame = frame[frame["ticker"].isin(wanted)].rename(columns={"ticker": "symbol"})
    frame["symbol"] = frame["symbol"].astype(str)
    frame["ts"] = pd.to_datetime(frame["window_start"], unit="ns", utc=True)
    return normalize_minutes(frame.drop(columns=["window_start"]), source="zip")


def day_path(root: Path, symbol: str, day: date) -> Path:
    return root / "stock_1m" / symbol / f"{day.year}" / f"{day.isoformat()}.parquet"


def write_day(df: pd.DataFrame, day: date, root: Path) -> int:
    for symbol, group in df.groupby("symbol"):
        path = day_path(root, symbol, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        group.to_parquet(path, index=False)
    return len(df)


def _ingest_one(job: tuple[Path, str, date, tuple[str, ...], Path]) -> int:
    zip_path, member, day, tickers, root = job
    return write_day(read_zip_day(zip_path, member, tickers), day, root)


def ingest_zip(
    zip_path: Path,
    start: date,
    end: date,
    tickers: Iterable[str] = UNIVERSE,
    root: Path | None = None,
    workers: int = 4,
    overwrite: bool = False,
) -> dict:
    root = root or lake_root()
    tickers = tuple(tickers)
    members = zip_minute_members(zip_path)
    in_range = {d: m for d, m in sorted(members.items()) if start <= d <= end}
    jobs = [
        (zip_path, member, day, tickers, root)
        for day, member in in_range.items()
        if overwrite or not day_path(root, tickers[0], day).exists()
    ]
    if workers <= 1:
        row_counts = [_ingest_one(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            row_counts = list(pool.map(_ingest_one, jobs, chunksize=4))
    return {
        "days_available": len(in_range),
        "days_written": len(jobs),
        "days_skipped": len(in_range) - len(jobs),
        "rows": int(sum(row_counts)),
    }
