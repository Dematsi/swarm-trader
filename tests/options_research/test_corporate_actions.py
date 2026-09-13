from datetime import date, timedelta

import pandas as pd

from src.options_research.corporate_actions import (
    EXPECTED_SPLITS,
    adjustment_factors,
    daily_rth_summary,
    detect_splits,
    load_splits,
    write_splits,
)


def daily_frame(symbol, closes, volumes, opens=None, start=date(2024, 5, 1)):
    days = [start + timedelta(days=i) for i in range(len(closes))]
    return pd.DataFrame({"symbol": symbol, "day": days, "rth_open": opens or closes, "rth_close": closes, "rth_volume": volumes})


def test_expected_splits_listed():
    assert EXPECTED_SPLITS == frozenset({
        ("NVDA", date(2021, 7, 20), 4.0), ("AMZN", date(2022, 6, 6), 20.0), ("GOOGL", date(2022, 7, 18), 20.0),
        ("TSLA", date(2022, 8, 25), 3.0), ("NVDA", date(2024, 6, 10), 10.0),
    })


def test_detects_forward_split_with_volume_confirmation():
    closes = [1200.0] * 25 + [121.0] * 5
    opens = [1200.0] * 25 + [120.4] + [121.0] * 4
    volumes = [40_000_000] * 25 + [314_000_000] * 5
    splits = detect_splits(daily_frame("NVDA", closes, volumes, opens=opens))
    assert splits.to_dict("records") == [{"symbol": "NVDA", "day": date(2024, 5, 26), "ratio": 10.0, "factor": 0.1}]


def test_price_halving_without_volume_jump_is_not_a_split():
    closes = [100.0] * 25 + [50.0] * 5
    volumes = [1_000_000] * 30
    assert detect_splits(daily_frame("XYZ", closes, volumes)).empty


def test_detects_reverse_split():
    closes = [2.0] * 25 + [10.0] * 5
    volumes = [5_000_000] * 25 + [1_000_000] * 5
    splits = detect_splits(daily_frame("REV", closes, volumes))
    assert splits.to_dict("records") == [{"symbol": "REV", "day": date(2024, 5, 26), "ratio": 0.2, "factor": 5.0}]


def test_adjustment_factor_applies_only_before_split_day():
    splits = pd.DataFrame([{"symbol": "NVDA", "day": date(2024, 6, 10), "ratio": 10.0, "factor": 0.1}])
    days = pd.Series([date(2024, 6, 7), date(2024, 6, 10), date(2024, 6, 11)])
    assert adjustment_factors(splits, "NVDA", days).tolist() == [0.1, 1.0, 1.0]
    assert adjustment_factors(splits, "AAPL", days).tolist() == [1.0, 1.0, 1.0]


def test_daily_rth_summary_uses_regular_session_only():
    ts = pd.to_datetime(["2025-11-28T13:00:00Z", "2025-11-28T14:30:00Z", "2025-11-28T17:59:00Z", "2025-11-28T18:30:00Z"], utc=True)
    minutes = pd.DataFrame({"symbol": "SPY", "ts": ts, "open": [1.0, 2.0, 3.0, 4.0], "close": [1.5, 2.5, 3.5, 4.5], "volume": [10, 20, 30, 40]})
    out = daily_rth_summary(minutes)
    assert out.to_dict("records") == [{"symbol": "SPY", "day": date(2025, 11, 28), "rth_open": 2.0, "rth_close": 3.5, "rth_volume": 50}]


def test_write_and_load_splits_roundtrip(tmp_path):
    splits = pd.DataFrame([{"symbol": "NVDA", "day": date(2024, 6, 10), "ratio": 10.0, "factor": 0.1}])
    path = write_splits(splits, root=tmp_path)
    assert path == tmp_path / "corporate_actions" / "splits.parquet"
    assert load_splits(root=tmp_path).to_dict("records") == splits.to_dict("records")
