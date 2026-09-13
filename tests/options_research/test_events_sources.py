import json
from datetime import date

import httpx
import pandas as pd
import pytest

from src.options_research.events_sources import (
    FRED_RELEASES,
    build_events,
    earnings_events,
    fred_release_events,
    load_events,
    write_events,
)


def fred_handler(dates_by_release):
    def handler(request):
        rid = int(request.url.params["release_id"])
        assert request.url.params["file_type"] == "json"
        assert request.url.params["api_key"] == "k"
        return httpx.Response(200, json={"release_dates": [{"release_id": rid, "date": d} for d in dates_by_release.get(rid, [])]})
    return handler


def test_fred_release_ids_and_times():
    assert FRED_RELEASES == {
        10: ("cpi", "1", "08:30"),
        50: ("employment_situation", "1", "08:30"),
        46: ("ppi", "2", "08:30"),
        54: ("personal_income_outlays", "2", "08:30"),
        53: ("gdp", "2", "08:30"),
        9: ("retail_sales", "2", "08:30"),
        192: ("jolts", "2", "10:00"),
    }


def test_fred_events_filter_range_and_non_sessions():
    http = httpx.Client(transport=httpx.MockTransport(fred_handler({
        10: ["2025-06-11", "2025-06-14", "2019-01-11"],  # in range; Saturday; out of range
        192: ["2025-06-03"],
    })))
    events = fred_release_events("k", date(2025, 1, 1), date(2025, 12, 31), http=http)
    assert sorted((e["date"], e["type"], e["time_et"], e["tier"], e["source"]) for e in events) == [
        (date(2025, 6, 3), "jolts", "10:00", "2", "fred"),
        (date(2025, 6, 11), "cpi", "08:30", "1", "fred"),
    ]


def test_fred_error_response_raises_without_leaking_key():
    def handler(request):
        return httpx.Response(400, text="bad request")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RuntimeError) as exc_info:
            fred_release_events("secret-key-123", date(2025, 1, 1), date(2025, 12, 31), http=http)
    finally:
        http.close()
    assert "secret-key-123" not in str(exc_info.value)
    assert "HTTP 400" in str(exc_info.value)


def test_fred_release_events_closes_internally_created_client(monkeypatch):
    closed = {"v": False}
    real_client_cls = httpx.Client

    class TrackingClient(real_client_cls):
        def close(self):
            closed["v"] = True
            super().close()

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda timeout=30: TrackingClient(timeout=timeout, transport=httpx.MockTransport(fred_handler({}))),
    )
    fred_release_events("k", date(2025, 1, 1), date(2025, 12, 31))
    assert closed["v"] is True


def _earnings_frame(timestamps):
    index = pd.DatetimeIndex(pd.to_datetime(timestamps)).tz_localize("America/New_York")
    index.name = "Earnings Date"
    return pd.DataFrame({"EPS Estimate": [1.0] * len(timestamps)}, index=index)


def test_earnings_bmo_same_day_amc_next_session_and_etfs_skipped():
    frames = {
        "NVDA": _earnings_frame(["2025-02-26 16:00"]),
        "AAPL": _earnings_frame(["2025-05-01 07:00"]),
    }
    calls = []

    def fetch(ticker):
        calls.append(ticker)
        return frames.get(ticker, _earnings_frame([]))

    events = earnings_events(["SPY", "NVDA", "AAPL"], date(2025, 1, 1), date(2025, 12, 31), fetch=fetch)
    assert "SPY" not in calls
    assert sorted((e["ticker"], e["date"], e["type"], e["tier"]) for e in events) == [
        ("AAPL", date(2025, 5, 1), "earnings_bmo", "earnings"),
        ("NVDA", date(2025, 2, 27), "earnings_amc", "earnings"),
    ]


def test_earnings_outside_calendar_range_are_skipped_without_error():
    frames = {"NVDA": _earnings_frame(["2019-02-14 16:00", "2025-02-26 16:00"])}
    events = earnings_events(["NVDA"], date(2025, 1, 1), date(2025, 12, 31), fetch=lambda t: frames[t])
    assert [(e["ticker"], e["date"]) for e in events] == [("NVDA", date(2025, 2, 27))]


def test_build_events_without_fred_key_records_note_and_writes(tmp_path):
    df, notes = build_events(date(2025, 6, 1), date(2025, 6, 30), fred_api_key=None, earnings_fetch=lambda t: _earnings_frame([]))
    assert notes["fred"].startswith("skipped")
    assert {"opex", "fomc_decision", "vix_expiration"} <= set(df["type"])
    assert list(df.columns) == ["date", "time_et", "type", "tier", "source", "ticker"]
    assert df["date"].is_monotonic_increasing
    path = write_events(df, notes, root=tmp_path)
    assert path == tmp_path / "calendar" / "events.parquet"
    assert json.loads((tmp_path / "calendar" / "events_notes.json").read_text())["fred"].startswith("skipped")
    loaded = load_events(root=tmp_path)
    assert len(loaded) == len(df)
