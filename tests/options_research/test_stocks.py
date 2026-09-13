import gzip
import io
import zipfile
from datetime import date

import pandas as pd

from src.options_research.stocks import (
    STOCK_COLUMNS,
    day_path,
    ingest_zip,
    is_day_done,
    mark_day_done,
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


def make_zip_multi_day(tmp_path):
    """Create a zip with two days of data (2025-06-11 and 2025-06-12), one SPY bar per day in trading hours."""
    rows_day1 = [
        ("SPY", 500, 600.0, 600.2, 600.3, 599.8, ns("2025-06-11T13:30:00Z"), 40),  # 09:30 ET -> kept
    ]
    rows_day2 = [
        ("SPY", 600, 601.0, 601.2, 601.3, 600.8, ns("2025-06-12T13:30:00Z"), 50),  # 09:30 ET -> kept
    ]

    # Create day 1
    frame1 = pd.DataFrame(rows_day1, columns=["ticker", "volume", "open", "close", "high", "low", "window_start", "transactions"])
    buf1 = io.BytesIO()
    with gzip.GzipFile(fileobj=buf1, mode="wb") as gz:
        gz.write(frame1.to_csv(index=False).encode())

    # Create day 2
    frame2 = pd.DataFrame(rows_day2, columns=["ticker", "volume", "open", "close", "high", "low", "window_start", "transactions"])
    buf2 = io.BytesIO()
    with gzip.GzipFile(fileobj=buf2, mode="wb") as gz:
        gz.write(frame2.to_csv(index=False).encode())

    path = tmp_path / "eq_multi.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("minute_aggs/2025/06/2025-06-11.csv.gz", buf1.getvalue())
        zf.writestr("minute_aggs/2025/06/2025-06-12.csv.gz", buf2.getvalue())
    return path


def test_partial_day_without_marker_is_reingested(tmp_path):
    """Verify that a partial day (stray parquet without marker) gets re-ingested."""
    path = make_zip(tmp_path)
    root = tmp_path / "lake"

    # Pre-create a stray parquet at day_path for SPY (simulating a crash mid-write)
    spy_path = day_path(root, "SPY", date(2025, 6, 11))
    spy_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"x": [1]}).to_parquet(spy_path)

    # Run ingest - should re-ingest because there's no marker
    result = ingest_zip(path, date(2025, 6, 1), date(2025, 6, 30), tickers=("SPY",), root=root, workers=1)
    assert result["days_written"] == 1

    # Verify the SPY file now has the correct schema
    written = pd.read_parquet(spy_path)
    assert list(written.columns) == STOCK_COLUMNS

    # Verify the day is now marked done
    assert is_day_done(root, date(2025, 6, 11), ("SPY",))


def test_marker_with_fewer_tickers_does_not_count_as_done(tmp_path):
    """Verify that a marker with fewer tickers doesn't satisfy a request for more tickers."""
    # Mark day done with only SPY
    mark_day_done(tmp_path, date(2025, 6, 11), ["SPY"], 2)

    # Check: SPY alone should be done
    assert is_day_done(tmp_path, date(2025, 6, 11), ["SPY"])

    # Check: SPY + QQQ should NOT be done (QQQ is missing from marker)
    assert not is_day_done(tmp_path, date(2025, 6, 11), ["SPY", "QQQ"])


def test_ingest_zip_process_pool_path(tmp_path):
    """Test the ProcessPoolExecutor path with multiple days and workers=2."""
    path = make_zip_multi_day(tmp_path)
    root = tmp_path / "lake"

    # Run ingest with workers=2 (should use ProcessPoolExecutor)
    result = ingest_zip(path, date(2025, 6, 1), date(2025, 6, 30), tickers=("SPY",), root=root, workers=2)

    # Verify both days were written
    assert result["days_written"] == 2

    # Verify both SPY day files exist
    spy_day1 = pd.read_parquet(day_path(root, "SPY", date(2025, 6, 11)))
    spy_day2 = pd.read_parquet(day_path(root, "SPY", date(2025, 6, 12)))
    assert len(spy_day1) == 1
    assert len(spy_day2) == 1

    # Verify both days are marked done
    assert is_day_done(root, date(2025, 6, 11), ("SPY",))
    assert is_day_done(root, date(2025, 6, 12), ("SPY",))
