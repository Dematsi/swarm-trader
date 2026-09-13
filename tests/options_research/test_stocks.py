import gzip
import io
import zipfile
from datetime import date

import pandas as pd

from src.options_research.stocks import (
    STOCK_COLUMNS,
    day_path,
    ingest_zip,
    normalize_minutes,
    read_zip_day,
    zip_minute_members,
)

# 2025-06-11 is EDT (UTC-4): 04:00 ET = 08:00Z, 09:30 ET = 13:30Z, 20:00 ET = 00:00Z next day
NS = 1_000_000_000


def ns(iso):
    return int(pd.Timestamp(iso).value)


def make_zip(tmp_path):
    rows = [
        ("SPY", 100, 600.0, 600.1, 600.2, 599.9, ns("2025-06-11T07:59:00Z"), 3),   # 03:59 ET -> dropped
        ("SPY", 500, 600.0, 600.2, 600.3, 599.8, ns("2025-06-11T13:30:00Z"), 40),  # 09:30 ET -> kept
        ("SPY", 300, 600.2, 600.1, 600.4, 600.0, ns("2025-06-11T23:59:00Z"), 9),   # 19:59 ET -> kept
        ("SPY", 200, 600.1, 600.1, 600.1, 600.1, ns("2025-06-12T00:00:00Z"), 2),   # 20:00 ET -> dropped
        ("XYZ", 900, 10.0, 10.1, 10.2, 9.9, ns("2025-06-11T13:30:00Z"), 5),       # not in universe
    ]
    frame = pd.DataFrame(rows, columns=["ticker", "volume", "open", "close", "high", "low", "window_start", "transactions"])
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(frame.to_csv(index=False).encode())
    path = tmp_path / "eq.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("minute_aggs/2025/06/2025-06-11.csv.gz", buf.getvalue())
        zf.writestr("day_aggs/2025/06/2025-06-11.csv.gz", b"")
    return path


def test_zip_minute_members_maps_dates(tmp_path):
    members = zip_minute_members(make_zip(tmp_path))
    assert members == {date(2025, 6, 11): "minute_aggs/2025/06/2025-06-11.csv.gz"}


def test_read_zip_day_filters_hours_tickers_and_converts_ts(tmp_path):
    path = make_zip(tmp_path)
    df = read_zip_day(path, "minute_aggs/2025/06/2025-06-11.csv.gz", ["SPY", "QQQ"])
    assert list(df.columns) == STOCK_COLUMNS
    assert df["symbol"].unique().tolist() == ["SPY"]
    assert df["ts"].tolist() == [pd.Timestamp("2025-06-11T13:30:00Z"), pd.Timestamp("2025-06-11T23:59:00Z")]
    assert str(df["ts"].dt.tz) == "UTC"
    assert df["source"].unique().tolist() == ["zip"]
    assert df["volume"].dtype == "int64"


def test_ingest_zip_writes_day_files_and_skips_existing(tmp_path):
    path = make_zip(tmp_path)
    root = tmp_path / "lake"
    first = ingest_zip(path, date(2025, 6, 1), date(2025, 6, 30), tickers=("SPY",), root=root, workers=1)
    assert first == {"days_available": 1, "days_written": 1, "days_skipped": 0, "rows": 2}
    written = pd.read_parquet(day_path(root, "SPY", date(2025, 6, 11)))
    assert len(written) == 2
    second = ingest_zip(path, date(2025, 6, 1), date(2025, 6, 30), tickers=("SPY",), root=root, workers=1)
    assert second["days_written"] == 0 and second["days_skipped"] == 1


def test_normalize_minutes_empty_input_keeps_schema():
    empty = pd.DataFrame(columns=["symbol", "ts", "open", "high", "low", "close", "volume", "transactions"])
    empty["ts"] = pd.to_datetime(empty["ts"], utc=True)
    out = normalize_minutes(empty, source="zip")
    assert list(out.columns) == STOCK_COLUMNS and out.empty
