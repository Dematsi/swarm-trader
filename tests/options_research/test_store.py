from datetime import date

import pandas as pd
import pytest

from src.options_research.stocks import STOCK_COLUMNS, write_day
from src.options_research.store import HINDSIGHT_COLUMNS, HoldoutAccessError, guard_period, load_stock_minutes, stock_minute_files

DEFAULT_COLUMNS = [c for c in STOCK_COLUMNS if c not in HINDSIGHT_COLUMNS]


def lake_day(root, symbol, iso_ts, close):
    frame = pd.DataFrame({
        "symbol": [symbol], "ts": pd.to_datetime([iso_ts], utc=True), "open": [close], "high": [close], "low": [close],
        "close": [close], "volume": [100], "transactions": [1], "bad_high": [False], "bad_low": [False],
        "high_clean": [close], "low_clean": [close], "source": ["zip"],
    })
    write_day(frame, pd.Timestamp(iso_ts).tz_convert("America/New_York").date(), root)


def test_guard_blocks_ranges_touching_holdout():
    guard_period(date(2025, 1, 2), date(2025, 12, 31), holdout=False)
    with pytest.raises(HoldoutAccessError):
        guard_period(date(2025, 12, 1), date(2026, 1, 2), holdout=False)
    guard_period(date(2026, 1, 2), date(2026, 9, 11), holdout=True)


def test_loader_refuses_holdout_without_flag(tmp_path):
    with pytest.raises(HoldoutAccessError):
        load_stock_minutes(["SPY"], date(2026, 1, 2), date(2026, 1, 5), root=tmp_path)


def test_guard_rejects_reversed_range_before_holdout_check():
    with pytest.raises(ValueError):
        guard_period(date(2025, 6, 2), date(2025, 6, 1), holdout=False)


def test_loader_rejects_reversed_range(tmp_path):
    with pytest.raises(ValueError):
        load_stock_minutes(["SPY"], date(2025, 6, 2), date(2025, 6, 1), root=tmp_path)


def test_loads_filtered_sorted_utc(tmp_path):
    lake_day(tmp_path, "SPY", "2025-06-11T13:31:00Z", 600.0)
    lake_day(tmp_path, "QQQ", "2025-06-11T13:30:00Z", 500.0)
    lake_day(tmp_path, "SPY", "2025-06-12T13:30:00Z", 601.0)
    lake_day(tmp_path, "SPY", "2025-07-01T13:30:00Z", 610.0)
    files = stock_minute_files(["SPY", "QQQ"], date(2025, 6, 11), date(2025, 6, 12), root=tmp_path)
    assert len(files) == 3
    df = load_stock_minutes(["SPY", "QQQ"], date(2025, 6, 11), date(2025, 6, 12), root=tmp_path)
    assert list(df.columns) == DEFAULT_COLUMNS
    assert df[["symbol", "close"]].values.tolist() == [["QQQ", 500.0], ["SPY", 600.0], ["SPY", 601.0]]
    assert str(df["ts"].dt.tz) == "UTC"
    assert df["ts"].iloc[1] == pd.Timestamp("2025-06-11T13:31:00Z")


def test_empty_range_returns_schema(tmp_path):
    df = load_stock_minutes(["SPY"], date(2025, 1, 2), date(2025, 1, 3), root=tmp_path)
    assert list(df.columns) == DEFAULT_COLUMNS and df.empty


def test_loads_mixed_legacy_and_new_schema_files(tmp_path):
    lake_day(tmp_path, "SPY", "2025-06-11T13:30:00Z", 600.0)
    legacy = pd.read_parquet(stock_minute_files(["SPY"], date(2025, 6, 11), date(2025, 6, 11), root=tmp_path)[0])
    lake_day(tmp_path, "SPY", "2025-06-12T13:30:00Z", 601.0)
    legacy_path = stock_minute_files(["SPY"], date(2025, 6, 12), date(2025, 6, 12), root=tmp_path)[0]
    legacy.assign(bad_close=False, close=601.0, ts=pd.to_datetime(["2025-06-12T13:30:00Z"], utc=True)).to_parquet(legacy_path, index=False)
    df = load_stock_minutes(["SPY"], date(2025, 6, 11), date(2025, 6, 12), root=tmp_path)
    assert list(df.columns) == DEFAULT_COLUMNS and df["close"].tolist() == [600.0, 601.0]


def test_default_excludes_hindsight_columns(tmp_path):
    lake_day(tmp_path, "SPY", "2025-06-11T13:30:00Z", 600.0)
    df = load_stock_minutes(["SPY"], date(2025, 6, 11), date(2025, 6, 11), root=tmp_path)
    assert list(df.columns) == DEFAULT_COLUMNS
    for column in HINDSIGHT_COLUMNS:
        assert column not in df.columns


def test_clean_true_includes_hindsight_columns_in_stock_columns_order(tmp_path):
    lake_day(tmp_path, "SPY", "2025-06-11T13:30:00Z", 600.0)
    df = load_stock_minutes(["SPY"], date(2025, 6, 11), date(2025, 6, 11), root=tmp_path, clean=True)
    assert list(df.columns) == STOCK_COLUMNS


def test_clean_true_on_empty_range_returns_full_schema(tmp_path):
    df = load_stock_minutes(["SPY"], date(2025, 1, 2), date(2025, 1, 3), root=tmp_path, clean=True)
    assert list(df.columns) == STOCK_COLUMNS and df.empty
