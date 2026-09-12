# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this fork is for

This fork of `zhound420/swarm-trader` (itself built on `virattt/ai-hedge-fund`) is used to
**research an edge in options trading**: intraday or swing, starting with single-leg long calls
and puts, then debit vertical spreads. Upstream trades **equities only** on Alpaca paper. It has
no options code and no Postgres access, so any options work is new code in this fork.

Research data comes from a local Postgres warehouse owned by the sibling project
`C:\Users\tsedi\alpaca-options-trading-bot`. **Read `docs/DATA_WAREHOUSE.md` before querying.**
It covers tables, coverage dates, the OCC vs Schwab symbol join key, and backtest caveats. In
particular, option bid/ask history only goes back to 2026-08-21. That DB is read-only from this
repo (`OPTIONS_DB_URL` enforces `default_transaction_read_only`).

## Commands

The project uses **uv** (migrated from Poetry; `poetry.lock` was replaced by `uv.lock`). README,
PLAYBOOK and script docstrings still say `poetry run`; substitute `uv run`. Run everything from
the repo root. Root scripts import `src.*` via the working directory rather than an installed
package.

```bash
uv sync                                        # install/refresh .venv
uv run pytest                                  # all tests
uv run pytest tests/backtesting/test_portfolio.py::test_name   # single test
uv run pytest --ignore=tests/test_api_rate_limiting.py         # skip the known-broken module
uv run black . && uv run isort .               # formatting (black line-length is 420)
uv run python risk_manager.py --status --mode swing            # read-only account/risk check
```

`tests/test_api_rate_limiting.py` fails at collection upstream: it imports `_make_api_request`,
which no longer exists after the switch to the free data layer. The other 37 tests (all under
`tests/backtesting/`) pass. There is no CI or lint config beyond black/isort in `pyproject.toml`.

Scripts that **place or cancel orders**: `execute_trades.py`, `run_hedge_fund.py --execute`,
`rebalance.py --execute`, `portfolio_monitor.py` (sells for real unless `--dry-run`), and
`execute_trades.py --flatten`. Prefer `--dry-run`. `.claude/settings.json` sets these to ask.

## Architecture

There are two largely independent layers plus a separate research loop.

**1. LangGraph analyst pipeline (`src/`)**
- `src/main.py:create_workflow` builds a fan-out/fan-in graph: `start_node` → every selected
  analyst in parallel → `risk_management_agent` → `portfolio_manager` → END.
- Analysts are registered in `src/utils/analysts.py:ANALYST_CONFIG` (key, display name,
  `agent_func`, order). Adding an agent = new file in `src/agents/` + an entry there
  (`mordecai.py` is the template).
- State is `src/graph/state.py:AgentState`. `data` and `metadata` merge dicts across parallel
  branches, and each analyst writes its signal under `state["data"]["analyst_signals"][agent_key]`.
- LLM calls go through `src/utils/llm.py:call_llm` with providers defined in `src/llm/models.py`.
- Fundamentals and prices come from `src/tools/api.py`, which delegates to `api_free.py`
  (yfinance + SEC EDGAR XBRL) with caching in `src/data/cache.py`. `api_original.py` is the
  unused financialdatasets.ai client.
- `src/backtesting/` is upstream's backtester for this LLM pipeline. It is what
  `tests/backtesting/` covers.

**2. Operational scripts (repo root, flat, not a package)**
- `run_hedge_fund.py` pulls Alpaca positions, runs the graph, converts decisions to trades, and
  pipes JSON into `execute_trades.py`. That script validates each BUY with `risk_manager.py`
  and submits Alpaca REST orders (brackets in swing mode).
- **Two different "risk managers" exist.** `src/agents/risk_manager.py` is a graph node that
  computes position limits for the LLM. Root `risk_manager.py:validate_trade` is the
  code-enforced V2 rule engine (11 rules) applied at execution time.
- `src/config.py:MODES` is the single source of truth for per-mode universe and risk limits.
  `resolve_mode()` picks the mode in this order: `--mode` flag → override in
  `trading_mode.json` → its `mode` field → `TRADING_MODE` env var → `swing`.
  `trading_mode.json` is rewritten at runtime by `set_mode()`.
- `src/accounts.py:get_account_for_mode` routes swing/day to separate Alpaca keys (day falls
  back to primary). The Alpaca **paper** base URL is hardcoded separately in about 10 files
  rather than centralized. Grep `paper-api.alpaca.markets` when touching broker access.
- Day mode builds intraday bars/VWAP/RSI directly from Alpaca's data API in `gather_data.py`,
  not through `src/tools`.

**3. AutoResearch (`autoresearch/`)**
- Karpathy-style loop: `evolve.py` invokes the `claude` CLI to edit **only** `strategy.py`
  (pure-Python rules, no LLM), runs `backtest_fast.py` (Alpaca bars cached in
  `autoresearch/data_cache/`, fitness = weighted Sharpe/Sortino/return/win-rate/profit-factor),
  then keeps or reverts the change. Agent instructions and known failure modes are in
  `autoresearch/program.md`.
- `strategy.py` is also loaded as the `autoresearch` analyst in the live graph and appears in
  `run_hedge_fund.py`'s default `--analysts`.

**`app/`** is upstream's web UI: a FastAPI backend on SQLite (`app/backend`, alembic migrations)
and a React/Vite flow editor (`app/frontend`). It is not used by the scripts above.

## Known hazards (security audit, 2026-09-12)

Treat these as open issues when changing trading paths:
- `execute_trades.py` **fails open**: if importing `risk_manager` fails, it logs a warning and
  continues with legacy checks only. Sells and covers are never rule-checked.
- Day-mode EOD flatten in `portfolio_monitor.py` compares naive `datetime.now()` (local clock)
  to "15:45 ET", so on a non-Eastern machine it flattens at the wrong time.
- LLM portfolio decisions are not clamped to `allowed_actions`/`max_shares`. The audit also
  found that V2 size and cash rules can pass when the reference price for an unheld ticker is 0.
- `autoresearch/evolve.py` loads `.env` and gives the spawned `claude` process unrestricted
  `Bash` with the full environment. Don't run it on a machine holding broker keys.
- Runtime state files `data/*.json*`, `snapshots/*.json` and `autoresearch/experiments/*.jsonl`
  are tracked in git despite `.gitignore`, so live results will show up in `git status`/commits.
- `app/backend` has no auth, returns stored API keys in plaintext, and has a path traversal in
  `routes/storage.py`. It binds to 127.0.0.1 only.
