from datetime import date

import httpx
import pandas as pd
import pytest

from src.options_research.alpaca_data import AlpacaDataClient, RateLimiter
from src.options_research.stocks import day_path, is_day_done, write_day
from src.options_research.stocks_alpaca import (
    STOCK_BARS_URL,
    STOCK_TRADES_URL,
    compare_sources,
    fetch_alpaca_day,
    fetch_minute_trades,
    ingest_alpaca_tail,
    validate_zip_overlap,
)


def bar(t, o=600.0, h=600.5, l=599.5, c=600.2, v=1000, n=10):
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "n": n, "vw": c}


def client_for(pages):
    def handler(request):
        assert request.method == "GET"
        assert str(request.url).startswith(STOCK_BARS_URL)
        assert request.url.params["timeframe"] == "1Min"
        assert request.url.params["feed"] == "sip"
        assert request.url.params["adjustment"] == "raw"
        token = request.url.params.get("page_token")
        return httpx.Response(200, json=pages[token])
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return AlpacaDataClient(key="k", secret="s", http=http, limiter=RateLimiter(1000), sleep=lambda s: None)


def test_fetch_alpaca_day_paginates_and_normalizes():
    pages = {
        None: {"bars": {"SPY": [bar("2025-06-11T13:30:00Z")]}, "next_page_token": "p2"},
        "p2": {"bars": {"SPY": [bar("2025-06-11T13:31:00Z")], "QQQ": [bar("2025-06-12T00:00:00Z")]}, "next_page_token": None},
    }
    df = fetch_alpaca_day(client_for(pages), ["SPY", "QQQ"], date(2025, 6, 11))
    assert df["source"].unique().tolist() == ["alpaca"]
    assert df[df["symbol"] == "SPY"]["ts"].tolist() == [pd.Timestamp("2025-06-11T13:30:00Z"), pd.Timestamp("2025-06-11T13:31:00Z")]
    assert df[df["symbol"] == "QQQ"].empty  # 20:00 ET excluded


def test_ingest_alpaca_tail_writes_sessions_only(tmp_path):
    pages = {None: {"bars": {"SPY": [bar("2025-12-24T14:30:00Z")]}, "next_page_token": None}}
    summary = ingest_alpaca_tail(client_for(pages), date(2025, 12, 24), date(2025, 12, 25), tickers=("SPY",), root=tmp_path)
    assert summary == {"sessions": 1, "days_written": 1, "days_skipped": 0, "rows": 1}
    assert day_path(tmp_path, "SPY", date(2025, 12, 24)).exists()
    # Verify day is marked done (R7)
    assert is_day_done(tmp_path, date(2025, 12, 24), ("SPY",))
    # Verify running again skips the day (R7)
    summary2 = ingest_alpaca_tail(client_for(pages), date(2025, 12, 24), date(2025, 12, 25), tickers=("SPY",), root=tmp_path)
    assert summary2 == {"sessions": 1, "days_written": 0, "days_skipped": 1, "rows": 0}


def frame(rows, source):
    df = pd.DataFrame(rows, columns=["symbol", "ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["source"] = source
    return df


def test_compare_sources_counts_mismatches():
    z = frame([("SPY", "2025-06-11T13:30:00Z", 1, 2, 0.5, 1.5, 100), ("SPY", "2025-06-11T13:31:00Z", 1, 2, 0.5, 1.5, 100),
               ("SPY", "2025-06-11T13:32:00Z", 1, 2, 0.5, 1.5, 100)], "zip")
    a = frame([("SPY", "2025-06-11T13:30:00Z", 1, 2, 0.5, 1.5, 100), ("SPY", "2025-06-11T13:31:00Z", 1, 2.1, 0.5, 1.5, 90),
               ("SPY", "2025-06-11T13:33:00Z", 1, 2, 0.5, 1.5, 100)], "alpaca")
    result = compare_sources(z, a)
    assert result["max_abs_diff_pct"] == pytest.approx(0.1 / 1.5)
    del result["max_abs_diff_pct"]
    assert result == {
        "compared": 2, "ohlc_mismatch": 1, "volume_mismatch": 1, "zip_only": 1, "alpaca_only": 1,
        "close_mismatch": 0, "max_close_diff_pct": 0.0,
    }


def test_compare_sources_close_mismatch_detects_wrong_security():
    z = frame([("META", "2022-01-11T14:30:00Z", 14.0, 14.1, 13.9, 14.0, 500)], "zip")
    a = frame([("META", "2022-01-11T14:30:00Z", 330.0, 330.5, 329.5, 330.0, 500)], "alpaca")
    result = compare_sources(z, a)
    assert result["close_mismatch"] == 1
    assert result["max_abs_diff_pct"] > 1.0
    assert result["max_close_diff_pct"] > 1.0


def test_validate_zip_overlap_reads_lake_and_compares(tmp_path):
    day = date(2025, 6, 11)
    lake_rows = pd.DataFrame({
        "symbol": ["SPY"], "ts": pd.to_datetime(["2025-06-11T13:30:00Z"], utc=True),
        "open": [600.0], "high": [600.5], "low": [599.5], "close": [600.2], "volume": [1000], "transactions": [10],
        "bad_high": [False], "bad_low": [False], "bad_close": [False], "high_clean": [600.5], "low_clean": [599.5], "source": ["zip"],
    })
    write_day(lake_rows, day, tmp_path)
    pages = {None: {"bars": {"SPY": [bar("2025-06-11T13:30:00Z")]}, "next_page_token": None}}
    result = validate_zip_overlap(client_for(pages), [day], tickers=("SPY",), root=tmp_path)
    assert result == {
        "2025-06-11": {
            "compared": 1, "ohlc_mismatch": 0, "volume_mismatch": 0, "zip_only": 0, "alpaca_only": 0,
            "close_mismatch": 0, "max_abs_diff_pct": 0.0, "max_close_diff_pct": 0.0,
            "rth_compared": 1, "rth_ohlc_mismatch": 0, "rth_volume_mismatch": 0, "rth_zip_only": 0, "rth_alpaca_only": 0,
            "rth_close_mismatch": 0, "rth_max_abs_diff_pct": 0.0, "rth_max_close_diff_pct": 0.0,
        }
    }


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
