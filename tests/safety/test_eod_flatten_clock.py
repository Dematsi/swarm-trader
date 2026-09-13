"""Fix 4: EOD flatten must use Eastern time and only run while the market is open."""

import types
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

import execute_trades
import portfolio_monitor as pm
from src.agents import autoresearch_agent

ET = ZoneInfo("America/New_York")


def _fake_datetime(utc_instant: datetime, naive_local: datetime):
    """datetime stand-in: tz-aware now() is correct, naive now() mimics a non-Eastern machine clock."""

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return naive_local
            return utc_instant.astimezone(tz)

    return FakeDatetime


@pytest.fixture
def monitor(monkeypatch):
    monkeypatch.setattr(pm, "get_account_for_mode", lambda mode=None: types.SimpleNamespace(name="Test", headers={}))
    monkeypatch.setattr(pm, "get_account", lambda: {"equity": "100000", "cash": "50000", "last_equity": "100000"})
    monkeypatch.setattr(pm, "get_positions", lambda: [])
    monkeypatch.setattr(pm, "get_spy_daily_return", lambda: None)
    monkeypatch.setattr(pm, "get_intraday_high", lambda symbol: None)
    monkeypatch.setattr(pm, "_print_summary", lambda **kwargs: None)

    calls = {"flatten": 0, "clock": 0}

    def fake_flatten(dry_run=False):
        calls["flatten"] += 1
        return {"results": [{"ticker": "AAPL", "status": "would_flatten"}]}

    monkeypatch.setattr(execute_trades, "flatten_all", fake_flatten)

    def set_clock(is_open=True, error=None):
        def fake_get(endpoint):
            if endpoint == "clock":
                calls["clock"] += 1
                if error:
                    raise error
                return {"is_open": is_open}
            raise AssertionError(f"unexpected endpoint {endpoint}")

        monkeypatch.setattr(pm, "_get", fake_get)

    def set_time(utc_instant, naive_local):
        monkeypatch.setattr(pm, "datetime", _fake_datetime(utc_instant, naive_local))

    return types.SimpleNamespace(calls=calls, set_clock=set_clock, set_time=set_time)


# 15:50 ET on 2026-09-11 (EDT) == 19:50 UTC
AFTER_CUTOFF_UTC = datetime(2026, 9, 11, 19, 50, tzinfo=timezone.utc)
# 11:00 ET == 15:00 UTC
MORNING_UTC = datetime(2026, 9, 11, 15, 0, tzinfo=timezone.utc)


def test_flattens_after_cutoff_eastern_even_if_local_clock_is_pacific(monitor):
    monitor.set_time(AFTER_CUTOFF_UTC, naive_local=datetime(2026, 9, 11, 12, 50))  # Pacific
    monitor.set_clock(is_open=True)
    result = pm.run_monitor(dry_run=True, mode="day")
    assert monitor.calls["flatten"] == 1
    assert result.get("eod_flatten") is True


def test_no_flatten_in_morning_even_if_local_clock_reads_after_cutoff(monitor):
    monitor.set_time(MORNING_UTC, naive_local=datetime(2026, 9, 11, 16, 0))  # e.g. UTC+1 machine
    monitor.set_clock(is_open=True)
    result = pm.run_monitor(dry_run=True, mode="day")
    assert monitor.calls["flatten"] == 0
    assert not result.get("eod_flatten")


def test_no_flatten_when_market_closed(monitor):
    monitor.set_time(AFTER_CUTOFF_UTC, naive_local=datetime(2026, 9, 11, 15, 50))
    monitor.set_clock(is_open=False)
    result = pm.run_monitor(dry_run=True, mode="day")
    assert monitor.calls["clock"] == 1
    assert monitor.calls["flatten"] == 0
    assert not result.get("eod_flatten")


def test_no_flatten_when_clock_call_fails(monitor, caplog):
    monitor.set_time(AFTER_CUTOFF_UTC, naive_local=datetime(2026, 9, 11, 15, 50))
    monitor.set_clock(error=RuntimeError("clock down"))
    with caplog.at_level("WARNING", logger="portfolio_monitor"):
        result = pm.run_monitor(dry_run=True, mode="day")
    assert monitor.calls["flatten"] == 0
    assert not result.get("eod_flatten")
    assert any("clock" in rec.getMessage().lower() for rec in caplog.records if rec.levelname == "WARNING")


def test_autoresearch_bar_time_converted_with_real_dst():
    # 15:00 UTC in January is 10:00 EST (UTC-5); a fixed -4h offset says 11:00.
    ctx = autoresearch_agent._build_market_context({}, bars_df={"AAPL": [{"t": "2026-01-15T15:00:00Z"}]})
    assert ctx["current_bar_time"] == "10:00"
    # 15:00 UTC in July is 11:00 EDT (UTC-4).
    ctx = autoresearch_agent._build_market_context({}, bars_df={"AAPL": [{"t": "2026-07-15T15:00:00Z"}]})
    assert ctx["current_bar_time"] == "11:00"
