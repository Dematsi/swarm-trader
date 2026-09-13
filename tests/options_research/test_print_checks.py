from datetime import date
from pathlib import Path

import httpx
import pandas as pd
import pytest

from src.options_research.alpaca_data import AlpacaDataClient, RateLimiter
from src.options_research.print_checks import (
    CANDIDATES_COLUMNS,
    CHECK_COLUMNS,
    candidates_path,
    checks_path,
    confirm_candidates,
    rebuild_clean,
    rewrite_clean_columns,
    scan_candidates,
)
from src.options_research.stocks import STOCK_COLUMNS, day_path, normalize_minutes, write_day

DAY = date(2023, 2, 1)
WICK_TS = pd.Timestamp("2023-02-01T21:15:00Z")


def wick_day(symbol="SYM", start="2023-02-01T21:00:00Z", n=30):
    ts = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    closes = [183.0 + (0.05 if i % 2 else -0.05) for i in range(n)]
    raw = pd.DataFrame({"symbol": symbol, "ts": ts, "open": closes, "high": [c + 0.05 for c in closes],
                        "low": [c - 0.05 for c in closes], "close": closes, "volume": 1000, "transactions": 20})
    raw.loc[15, "low"] = 153.12
    return normalize_minutes(raw, source="zip")


def seed(root):
    write_day(wick_day(), DAY, root)
    legacy = normalize_minutes(pd.DataFrame({
        "symbol": "SYM", "ts": pd.date_range("2023-02-02T15:00:00Z", periods=10, freq="1min", tz="UTC"),
        "open": 50.0, "high": 50.1, "low": 49.9, "close": 50.0, "volume": 10, "transactions": 1,
    }), source="zip").assign(bad_close=False)
    write_day(legacy, date(2023, 2, 2), root)


def fake_trades(symbol, ts):
    assert symbol == "SYM" and ts == WICK_TS
    return [{"t": "2023-02-01T21:15:01Z", "price": p, "size": 100, "exchange": x, "conditions": ["@", "T"]}
            for p, x in ((182.75, "V"), (182.90, "P"), (182.94, "V"), (153.12, "D"))]


def test_scan_candidates_finds_the_wick_and_writes_file(tmp_path):
    seed(tmp_path)
    cands = scan_candidates(tmp_path, symbols=["SYM"], workers=1)
    assert cands[["symbol", "side", "extreme"]].values.tolist() == [["SYM", "low", 153.12]]
    assert pd.Timestamp(cands.iloc[0]["ts"]) == WICK_TS
    assert str(pd.Timestamp(cands.iloc[0]["session_date"]).date()) == "2023-02-01"
    assert candidates_path(tmp_path).exists()


def test_confirm_candidates_is_resumable(tmp_path):
    seed(tmp_path)
    cands = scan_candidates(tmp_path, symbols=["SYM"], workers=1)
    calls = []

    def fetch(symbol, ts):
        calls.append((symbol, ts))
        return fake_trades(symbol, ts)

    first = confirm_candidates(cands, fetch, root=tmp_path)
    assert len(calls) == 1
    assert list(first.columns) == CHECK_COLUMNS
    assert first.iloc[0]["decision"] == "isolated" and first.iloc[0]["clean_value"] == 182.75
    second = confirm_candidates(cands, fetch, root=tmp_path)
    assert len(calls) == 1 and len(second) == 1
    assert checks_path(tmp_path).exists()


def test_rewrite_applies_decisions_and_normalizes_schema(tmp_path):
    seed(tmp_path)
    cands = scan_candidates(tmp_path, symbols=["SYM"], workers=1)
    checks = confirm_candidates(cands, fake_trades, root=tmp_path)
    summary = rewrite_clean_columns(checks, root=tmp_path, symbols=["SYM"], workers=1)
    assert summary == {"files": 2, "flags": 1}
    wick = pd.read_parquet(day_path(tmp_path, "SYM", DAY))
    assert list(wick.columns) == STOCK_COLUMNS
    row = wick[wick["ts"] == WICK_TS].iloc[0]
    assert row["bad_low"] and row["low_clean"] == 182.75 and row["low"] == 153.12
    legacy = pd.read_parquet(day_path(tmp_path, "SYM", date(2023, 2, 2)))
    assert list(legacy.columns) == STOCK_COLUMNS


def test_rebuild_clean_end_to_end_with_mock_alpaca(tmp_path):
    seed(tmp_path)

    def handler(request):
        assert request.url.path == "/v2/stocks/trades"
        return httpx.Response(200, json={"trades": {"SYM": [
            {"t": "2023-02-01T21:15:01Z", "p": 182.75, "s": 100, "x": "V", "c": ["@", "T"]},
            {"t": "2023-02-01T21:15:02Z", "p": 153.12, "s": 100000, "x": "D", "c": ["@", "T"]},
        ]}, "next_page_token": None})

    client = AlpacaDataClient(key="k", secret="s", http=httpx.Client(transport=httpx.MockTransport(handler)),
                              limiter=RateLimiter(1000), sleep=lambda s: None)
    summary = rebuild_clean(client, phase="all", root=tmp_path, symbols=["SYM"], workers=1)
    assert summary["candidates"] == 1 and summary["isolated"] == 1 and summary["flags"] == 1
    row = pd.read_parquet(day_path(tmp_path, "SYM", DAY)).set_index("ts").loc[WICK_TS]
    assert row["low_clean"] == 182.75


def test_rebuild_clean_rewrite_phase_with_zero_checks_does_not_crash(tmp_path):
    seed(tmp_path)
    candidates_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=CANDIDATES_COLUMNS).to_parquet(candidates_path(tmp_path), index=False)
    pd.DataFrame(columns=CHECK_COLUMNS).to_parquet(checks_path(tmp_path), index=False)

    summary = rebuild_clean(None, phase="rewrite", root=tmp_path, symbols=["SYM"], workers=1)

    assert summary["flags"] == 0


def _boom_to_parquet(self, target, *args, **kwargs):
    """Simulate a crash mid-write: touch the temp file with garbage, then blow up before replace."""
    Path(target).write_bytes(b"garbage")
    raise RuntimeError("simulated crash mid-write")


def test_confirm_candidates_write_is_atomic_on_crash(tmp_path, monkeypatch):
    seed(tmp_path)
    cands = scan_candidates(tmp_path, symbols=["SYM"], workers=1)
    confirm_candidates(cands, fake_trades, root=tmp_path)
    path = checks_path(tmp_path)
    baseline = path.read_bytes()

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _boom_to_parquet)
    with pytest.raises(RuntimeError):
        confirm_candidates(cands, fake_trades, root=tmp_path)

    assert path.read_bytes() == baseline
    assert not path.with_name(path.name + ".tmp").exists()


def test_rewrite_clean_columns_write_is_atomic_on_crash(tmp_path, monkeypatch):
    seed(tmp_path)
    cands = scan_candidates(tmp_path, symbols=["SYM"], workers=1)
    checks = confirm_candidates(cands, fake_trades, root=tmp_path)
    path = day_path(tmp_path, "SYM", DAY)
    baseline = path.read_bytes()

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _boom_to_parquet)
    with pytest.raises(RuntimeError):
        rewrite_clean_columns(checks, root=tmp_path, symbols=["SYM"], workers=1)

    assert path.read_bytes() == baseline
    assert not path.with_name(path.name + ".tmp").exists()


def test_confirm_candidates_flush_and_resume_after_partial_failure(tmp_path):
    rows = [
        {"symbol": "SYM", "session_date": DAY, "ts": WICK_TS + pd.Timedelta(minutes=i),
         "side": "low", "extreme": 150.0, "reference": 183.0, "band": 5.0}
        for i in range(5)
    ]
    cands = pd.DataFrame(rows, columns=CANDIDATES_COLUMNS)

    first_calls = []

    def flaky_fetch(symbol, ts):
        first_calls.append((symbol, ts))
        if len(first_calls) == 4:
            raise RuntimeError("simulated network failure")
        return []

    with pytest.raises(RuntimeError):
        confirm_candidates(cands, flaky_fetch, root=tmp_path, flush_every=2)

    on_disk = pd.read_parquet(checks_path(tmp_path))
    assert len(on_disk) == 2
    assert on_disk["ts"].tolist() == [rows[0]["ts"], rows[1]["ts"]]

    second_calls = []

    def ok_fetch(symbol, ts):
        second_calls.append((symbol, ts))
        return []

    final = confirm_candidates(cands, ok_fetch, root=tmp_path, flush_every=2)

    # The two already-flushed candidates are not re-fetched; the lost in-memory one (#2) and the
    # two never-attempted ones (#3, #4) are.
    assert second_calls == [(r["symbol"], r["ts"]) for r in rows[2:]]
    assert len(final) == 5
    keys = list(zip(final["symbol"], final["ts"], final["side"]))
    assert len(keys) == len(set(keys))
