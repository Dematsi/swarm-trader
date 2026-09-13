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

`docker/Dockerfile` installs from `uv.lock`. The web-app launchers `app/run.sh` and
`app/run.bat` still call Poetry; to run the backend directly, use
`uv run uvicorn app.backend.main:app --host 127.0.0.1 --port 8000`.

**Options research** (`src/options_research/`, spec in `docs/superpowers/specs/2026-09-12-options-edge-research-design.md`):

Results, decisions and process lessons are recorded in `docs/research/options-edge-research-log.md` (newest first; PRELIMINARY/FINAL status). Add an entry after every milestone, run or review.

```bash
uv run python -m src.options_research ingest-stocks   # equity zip -> data/options_lake/stock_1m (resumable)
uv run python -m src.options_research ingest-tail     # Alpaca SIP minutes after 2026-06-18 + zip-vs-Alpaca check
uv run python -m src.options_research detect-splits
uv run python -m src.options_research build-events    # needs FRED_API_KEY for macro release dates
uv run python -m src.options_research build-costs     # Schwab quotes from the sibling DB (read-only)
uv run python -m src.options_research report-m1 && uv run python -m src.options_research report-m2
uv run python -m src.options_research stage1 --workers 4   # stage-1 signals + outcomes (resumable per symbol; --symbols, --overwrite)
uv run python -m src.options_research report-m3            # evaluation vs spec §8.3, ledger entries, reports/options_research/m3_stage1.md
uv run pytest -m integration tests/options_research   # real-data checks (zip, lake, DB)
```

Loaders in `store.py` refuse holdout dates (>= 2026-01-02) unless `holdout=True`, which is
reserved for validation, split detection and cost calibration.

**Clean columns are hindsight values.** `rebuild-clean` flags only isolated off-market prints (≤3
off-exchange trades beyond a two-sided band, confirmed from Alpaca SIP trades) and sets
`high_clean`/`low_clean` to the most extreme in-band traded price. The value is empty when no
in-band trade lies inside the raw bar.
- `store.load_stock_minutes` returns flag and clean columns only with `clean=True`.
- Use them only for values read after the window closes: prior-day high/low, ATR history, and
  pre-market high/low at or after 09:37.
- Prior-day close and all intraday regular-hours features use raw OHLC.
- `tests/options_research/test_data_access.py` restricts which modules may read the lake,
  reference clean columns, or import `quality`/`print_checks`. The candidate detector looks at
  future bars.
- Run `uv run python -m src.options_research rebuild-clean` (phases `scan`, `confirm`, `rewrite`)
  after any new ingest. The audit trail is in `data/options_lake/quality/print_checks.parquet`.

**Stage-1 layout.**
- `features.py` builds raw point-in-time features: a 1-min grid, VWAP/σ, and 5-min Wilder
  indicators attached only when the 5-min bar is complete.
- `levels.py` is the only feature module that reads clean columns. It holds prior-day and
  pre-market levels plus the 5-session warm-up, all split-adjusted.
- `setups/` holds one detector per pre-registered setup. It takes a `DayContext` and returns
  signals decided at `T = bar start + 1 min`.
- `stage1.py` runs the detectors and adds forward outcomes and tags. `evaluate.py` applies spec §8.3.
- `ledger.py` records every evaluated configuration in `reports/options_research/ledger.jsonl`.
- Pre-registered interpretations are in `docs/superpowers/plans/2026-09-13-options-research-m3-stage1.md`.
  Changing a setup parameter or evaluation rule creates new ledger configurations.

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

## Safety invariants (security audit + fixes, 2026-09-12)

These behaviors were added on purpose and are covered by `tests/safety/` and `tests/security/`.
Don't regress them:
- `execute_trades.py` **fails closed**. If `risk_manager` can't be imported, or the daily
  circuit breaker has tripped, buy/short entries are rejected while sells/covers still go
  through. An entry with no resolvable price (from the trade, the position, or Alpaca's latest
  trade) is rejected, and `risk_manager.validate_trade` also rejects a price <= 0.
- `portfolio_monitor.py` checks the EOD flatten time in `America/New_York` and flattens only
  when Alpaca's `/v2/clock` says the market is open.
- `portfolio_manager` clamps LLM decisions to `compute_allowed_actions` and drops tickers it
  wasn't asked about. `autoresearch` is not in `run_hedge_fund.py`'s default analysts.
- `autoresearch/evolve.py` runs `claude` with `Read`/`Edit(strategy.py)` only, no Bash, and an
  allowlisted environment without broker/LLM keys (`build_agent_env`).
- `app/backend` masks API keys in responses, enforces `TrustedHostMiddleware`
  (127.0.0.1/localhost), and rejects path traversal in `routes/storage.py`.

Still open:
- `src/alpaca_integration.py:execute_decisions` still has a fail-open `risk_manager` import.
  `run_hedge_fund.py` doesn't use it.
- `src/accounts.py:get_account_for_mode("day")` doesn't fall back to the primary keys (the
  README says it should). `src/alpaca_integration.py` resolves headers at import, so importing
  `run_hedge_fund` raises when day keys are absent.
- Code the AI writes into `autoresearch/strategy.py` is still unsandboxed Python at backtest time.
- `autoresearch/strategy.py` and `gather_data.py` use a fixed -4h/`-04:00` ET offset, which is
  wrong during EST.
- `app/frontend`: `npm run build` already failed with 18 `tsc` errors before the dependency bump.
