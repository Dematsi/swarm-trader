"""Fixes 2 and 3: reference price, fail-closed risk manager, daily circuit breaker."""

import json
import sys
import types

import pytest

import execute_trades as et
import risk_manager as rm
from risk_manager import ValidationResult
from tests.safety.conftest import FakeResponse


# ── helpers ─────────────────────────────────────────────────────────────────

PORTFOLIO_STATE = {
    "equity": 100_000.0,
    "cash": 50_000.0,
    "cash_pct": 0.5,
    "daily_pnl_pct": 0.0,
    "weekly_pnl_pct": 0.0,
    "positions": {},
    "sector_alloc": {},
    "trade_count_today": 0,
    "open_position_count": 0,
}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    """Run execute_trades.main() --dry-run fully offline. Returns a runner."""
    monkeypatch.setattr(et, "_headers", lambda: {"APCA-API-KEY-ID": "test"})
    monkeypatch.setattr(et, "get_account_for_mode", lambda mode: types.SimpleNamespace(name="Test", headers={}))
    # Performance snapshot is imported lazily at the end of main(); stub it out.
    monkeypatch.setitem(sys.modules, "performance_tracker_v2", types.SimpleNamespace(take_snapshot=lambda: None))
    monkeypatch.setattr(et, "rm_get_portfolio_state", lambda mode=None: dict(PORTFOLIO_STATE), raising=False)

    state = {"account": {"equity": "100000", "last_equity": "100000"}, "positions": {}}
    monkeypatch.setattr(et, "get_account", lambda: state["account"])
    monkeypatch.setattr(et, "get_positions", lambda: state["positions"])

    def run(trades, capsys):
        f = tmp_path / "decisions.json"
        f.write_text(json.dumps({"trades": trades}))
        monkeypatch.setattr(sys, "argv", ["execute_trades.py", "--file", str(f), "--dry-run", "--mode", "swing"])
        rc = et.main()
        out = capsys.readouterr().out
        return rc, json.loads(out)

    state["run"] = run
    return state


def _by_ticker(output):
    return {r["ticker"]: r for r in output["results"]}


# ── Fix 2: zero reference price ─────────────────────────────────────────────

def test_risk_manager_rejects_missing_or_zero_entry_price():
    for bad in (None, 0, 0.0, -5.0):
        for action in ("buy", "short"):
            result = rm.validate_trade("AAPL", action, 10, bad, portfolio_state=dict(PORTFOLIO_STATE), mode="swing")
            assert not result.approved, f"{action} with entry_price={bad!r} should be rejected"
            assert "price" in result.reason.lower()


def test_risk_manager_blocks_oversized_trade_with_real_price():
    # Sanity: with a real price the size rules actually fire.
    result = rm.validate_trade("AAPL", "buy", 10_000, 200.0, portfolio_state=dict(PORTFOLIO_STATE), mode="swing")
    assert not result.approved


def test_get_latest_price_uses_alpaca_latest_trade(monkeypatch):
    monkeypatch.setattr(et, "_headers", lambda: {"APCA-API-KEY-ID": "test"})
    calls = []

    def fake_get(url, headers=None, timeout=None, **kwargs):
        calls.append(url)
        return FakeResponse({"symbol": "AAPL", "trade": {"p": 187.25}})

    monkeypatch.setattr(et.requests, "get", fake_get)
    assert et.get_latest_price("AAPL") == 187.25
    assert calls == ["https://data.alpaca.markets/v2/stocks/AAPL/trades/latest"]


def test_get_latest_price_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(et, "_headers", lambda: {"APCA-API-KEY-ID": "test"})
    monkeypatch.setattr(et.requests, "get", lambda *a, **k: FakeResponse({"message": "nope"}, status_code=500))
    assert et.get_latest_price("AAPL") is None


def test_unheld_ticker_uses_fetched_price_for_v2_validation(harness, monkeypatch, capsys):
    monkeypatch.setattr(et, "RISK_MANAGER_AVAILABLE", True)
    monkeypatch.setattr(et, "get_latest_price", lambda ticker: 200.0)
    seen = {}

    def fake_validate(ticker, action, qty, entry_price, portfolio_state=None, mode=None):
        seen["entry_price"] = entry_price
        return ValidationResult(approved=True, reason="ok")

    monkeypatch.setattr(et, "rm_validate_trade", fake_validate, raising=False)
    rc, out = harness["run"]([{"ticker": "AAPL", "action": "buy", "qty": 10}], capsys)
    assert rc == 0
    assert seen["entry_price"] == 200.0
    assert _by_ticker(out)["AAPL"]["status"] == "would_execute"


def test_unheld_ticker_oversized_buy_blocked_by_real_rules(harness, monkeypatch, capsys):
    monkeypatch.setattr(et, "RISK_MANAGER_AVAILABLE", True)
    monkeypatch.setattr(et, "rm_validate_trade", rm.validate_trade, raising=False)
    monkeypatch.setattr(et, "get_latest_price", lambda ticker: 200.0)
    # 10,000 * $200 = $2M on a $100K account. Previously ref_price=0 made this pass.
    rc, out = harness["run"]([{"ticker": "AAPL", "action": "buy", "qty": 10_000}], capsys)
    assert _by_ticker(out)["AAPL"]["status"] == "blocked"


def test_unknown_price_rejects_entry(harness, monkeypatch, capsys):
    monkeypatch.setattr(et, "RISK_MANAGER_AVAILABLE", True)
    monkeypatch.setattr(et, "get_latest_price", lambda ticker: None)
    monkeypatch.setattr(
        et, "rm_validate_trade",
        lambda *a, **k: ValidationResult(approved=True, reason="ok"),
        raising=False,
    )
    rc, out = harness["run"]([{"ticker": "AAPL", "action": "short", "qty": 10}], capsys)
    r = _by_ticker(out)["AAPL"]
    assert r["status"] == "blocked"
    assert "price" in r["reason"].lower()


# ── Fix 3: fail closed + circuit breaker ────────────────────────────────────

def test_entries_blocked_when_risk_manager_unavailable(harness, monkeypatch, capsys):
    monkeypatch.setattr(et, "RISK_MANAGER_AVAILABLE", False)
    monkeypatch.setattr(et, "get_latest_price", lambda ticker: 100.0)
    harness["positions"] = {"MSFT": {"symbol": "MSFT", "qty": "10", "current_price": "400"}}
    rc, out = harness["run"](
        [
            {"ticker": "AAPL", "action": "buy", "qty": 1},
            {"ticker": "TSLA", "action": "short", "qty": 1},
            {"ticker": "MSFT", "action": "sell", "qty": 10},
        ],
        capsys,
    )
    results = _by_ticker(out)
    assert results["AAPL"]["status"] == "blocked"
    assert results["TSLA"]["status"] == "blocked"
    assert "risk manager" in results["AAPL"]["reason"].lower()
    # Exits reduce risk and remain allowed.
    assert results["MSFT"]["status"] == "would_execute"


def test_circuit_breaker_blocks_entries_but_allows_exits(harness, monkeypatch, capsys):
    monkeypatch.setattr(et, "RISK_MANAGER_AVAILABLE", True)
    monkeypatch.setattr(et, "get_latest_price", lambda ticker: 100.0)
    # A risk manager that approves everything proves main() enforces the breaker itself.
    monkeypatch.setattr(
        et, "rm_validate_trade",
        lambda *a, **k: ValidationResult(approved=True, reason="ok"),
        raising=False,
    )
    harness["account"] = {"equity": "95000", "last_equity": "100000"}  # -5% vs swing limit 2%
    harness["positions"] = {
        "MSFT": {"symbol": "MSFT", "qty": "10", "current_price": "400"},
        "NVDA": {"symbol": "NVDA", "qty": "-5", "current_price": "100"},
    }
    rc, out = harness["run"](
        [
            {"ticker": "AAPL", "action": "buy", "qty": 1},
            {"ticker": "TSLA", "action": "short", "qty": 1},
            {"ticker": "MSFT", "action": "sell", "qty": 10},
            {"ticker": "NVDA", "action": "cover", "qty": 5},
        ],
        capsys,
    )
    results = _by_ticker(out)
    assert out["circuit_breaker_active"] is True
    assert results["AAPL"]["status"] == "blocked"
    assert results["TSLA"]["status"] == "blocked"
    assert "circuit breaker" in results["AAPL"]["reason"].lower()
    assert results["MSFT"]["status"] == "would_execute"
    assert results["NVDA"]["status"] == "would_execute"


def test_legacy_validator_uses_real_daily_pnl():
    ok, reason = et.validate_trade_legacy(
        "AAPL", "buy", 1, {}, 100_000.0, daily_loss_limit=0.02, max_trade_pct=0.15, daily_pnl_pct=-0.05,
    )
    assert not ok
    assert "circuit breaker" in reason.lower()

    ok, _ = et.validate_trade_legacy(
        "AAPL", "buy", 1, {}, 100_000.0, daily_loss_limit=0.02, max_trade_pct=0.15, daily_pnl_pct=0.01,
    )
    assert ok
