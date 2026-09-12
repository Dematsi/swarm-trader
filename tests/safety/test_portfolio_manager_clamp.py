"""Fix 1: LLM portfolio decisions must be clamped to the deterministic constraints."""

import src.agents.portfolio_manager as pm
from src.agents.portfolio_manager import PortfolioDecision, PortfolioManagerOutput


def _decision(action, quantity):
    return PortfolioDecision(action=action, quantity=quantity, confidence=90, reasoning="llm")


def _run(monkeypatch, llm_decisions, tickers, current_prices, max_shares, portfolio):
    monkeypatch.setattr(pm, "call_llm", lambda **kwargs: PortfolioManagerOutput(decisions=llm_decisions))
    return pm.generate_trading_decision(
        tickers=tickers,
        signals_by_ticker={t: {} for t in tickers},
        current_prices=current_prices,
        max_shares=max_shares,
        portfolio=portfolio,
        agent_id="portfolio_manager",
        state={"metadata": {}, "data": {}},
    ).decisions


PORTFOLIO = {
    "cash": 10_000.0,
    "margin_requirement": 0.5,
    "margin_used": 0.0,
    "equity": 10_000.0,
    "positions": {"AAPL": {"long": 5, "short": 0}},
}


def test_llm_ticker_not_sent_to_llm_is_dropped(monkeypatch):
    out = _run(
        monkeypatch,
        {"AAPL": _decision("hold", 0), "TSLA": _decision("buy", 1000)},
        tickers=["AAPL"],
        current_prices={"AAPL": 100.0},
        max_shares={"AAPL": 20},
        portfolio=PORTFOLIO,
    )
    assert "TSLA" not in out
    assert set(out) == {"AAPL"}


def test_disallowed_action_becomes_hold(monkeypatch):
    # AAPL has no short position, so "cover" is not allowed.
    out = _run(
        monkeypatch,
        {"AAPL": _decision("cover", 10)},
        tickers=["AAPL"],
        current_prices={"AAPL": 100.0},
        max_shares={"AAPL": 20},
        portfolio=PORTFOLIO,
    )
    assert out["AAPL"].action == "hold"
    assert out["AAPL"].quantity == 0


def test_quantity_clamped_to_allowed_max(monkeypatch):
    out = _run(
        monkeypatch,
        {"AAPL": _decision("buy", 10_000)},
        tickers=["AAPL"],
        current_prices={"AAPL": 100.0},
        max_shares={"AAPL": 20},
        portfolio=PORTFOLIO,
    )
    allowed = pm.compute_allowed_actions(["AAPL"], {"AAPL": 100.0}, {"AAPL": 20}, PORTFOLIO)["AAPL"]
    assert out["AAPL"].action == "buy"
    assert out["AAPL"].quantity == allowed["buy"] == 20

    out = _run(
        monkeypatch,
        {"AAPL": _decision("sell", 500)},
        tickers=["AAPL"],
        current_prices={"AAPL": 100.0},
        max_shares={"AAPL": 20},
        portfolio=PORTFOLIO,
    )
    assert out["AAPL"].action == "sell"
    assert out["AAPL"].quantity == 5


def test_negative_quantity_clamped_to_zero(monkeypatch):
    out = _run(
        monkeypatch,
        {"AAPL": _decision("buy", -50)},
        tickers=["AAPL"],
        current_prices={"AAPL": 100.0},
        max_shares={"AAPL": 20},
        portfolio=PORTFOLIO,
    )
    assert out["AAPL"].quantity == 0


def test_llm_cannot_override_prefilled_hold(monkeypatch):
    # MSFT has zero price -> only hold allowed -> prefilled and never sent to the LLM.
    out = _run(
        monkeypatch,
        {"AAPL": _decision("hold", 0), "MSFT": _decision("buy", 100)},
        tickers=["AAPL", "MSFT"],
        current_prices={"AAPL": 100.0, "MSFT": 0.0},
        max_shares={"AAPL": 20, "MSFT": 0},
        portfolio=PORTFOLIO,
    )
    assert out["MSFT"].action == "hold"
    assert out["MSFT"].quantity == 0


def test_llm_omitted_ticker_defaults_to_hold(monkeypatch):
    out = _run(
        monkeypatch,
        {},
        tickers=["AAPL"],
        current_prices={"AAPL": 100.0},
        max_shares={"AAPL": 20},
        portfolio=PORTFOLIO,
    )
    assert out["AAPL"].action == "hold"
    assert out["AAPL"].quantity == 0
