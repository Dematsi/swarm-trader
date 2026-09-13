# Intraday Single-Leg Options Edge Research — Design Spec

- **Date:** 2026-09-12
- **Status:** Approved (design agreed in conversation; user said "proceed" 2026-09-12)
- **Branch:** `local-setup` (fork `Dematsi/swarm-trader`)

## 1. Goal and scope

Find out whether any **rules-based intraday setup** on liquid US stocks/ETFs has a statistically
robust edge when expressed as a **long single-leg option** (buy a call or a put), after realistic
costs, with **entry and exit timing modeled as carefully as possible**.

**In scope (round 1)**
- Long calls/puts only (debit, single leg), opened and closed on the same day.
- 12 underlyings: SPY, QQQ, IWM, NVDA, TSLA, AAPL, AMZN, MSFT, GOOGL, META, AMD, NFLX.
- Nine setup variants in four families (§6), long and short direction (call or put).
- Two-stage evaluation: stock-level predictiveness (stage 1), then option simulation (stage 2).
- Economic-calendar and earnings awareness (§8.6).

**Out of scope (later phases)**
- Debit vertical spreads (phase 2; needs Level 3 and confirmed multi-leg support).
- Setups built specifically around events (e.g. trading the range after the FOMC release).
- Paper or live order execution, position sizing, and portfolio construction.
- LLM agents. This work is deterministic and doesn't touch `src/agents` or the root trading
  scripts.

## 2. Constraints and safety

- New package `src/options_research/`. It imports **nothing** from the root trading scripts,
  `src/agents`, `src/alpaca_integration.py` or `src/accounts.py`.
- **Alpaca access goes through exactly one module**, `alpaca_data.py`. It is read-only by
  construction:
  - HTTP GET only. It has no function that can send a body or use another method.
  - Host+path allowlist:
    - `data.alpaca.markets`: `/v1beta1/options/bars`, `/v1beta1/options/trades`, `/v2/stocks/bars`
    - `api.alpaca.markets`: `/v2/options/contracts`
  - Uses only `ALPACA_DATA_API_KEY` / `ALPACA_DATA_SECRET_KEY`. These are **live-host keys**, so
    the allowlist is a safety boundary and is covered by tests.
  - Client-side rate limit of 180 requests/min (Alpaca's is 200). Retries with backoff on 429/5xx.
- **The sibling bot's Postgres is read-only** (`OPTIONS_DB_URL` forces
  `default_transaction_read_only`). It's used only for Schwab quotes (cost model) and for
  cross-validating our bars.
- **No vendor data in git.** The equity zip (Polygon/Massive flat files) and Alpaca data stay under
  `data/` (gitignored). Tests use synthetic fixtures. Integration checks that read real data are
  skipped when the data is absent.
- **Dataset freeze.** All development uses data through **2026-09-11**. The holdout rules are
  in §9.1.

## 3. Evidence behind the design (measured 2026-09-12)

Details are in `docs/DATA_WAREHOUSE.md`. Key facts:

| Fact | Consequence |
|---|---|
| Alpaca serves 5-min **and 1-min** option bars for expired contracts from about **Jan 2024**, plus historical option **trades** (ticks). There are no historical option quotes. | Option prices come from trade prints. Costs are modeled separately. |
| `GET /v2/options/contracts?status=inactive` lists expired contracts (full strike ladder). IWM had Wednesday expirations. | We know which strikes existed. Selection still requires prior prints (§7.2). |
| Liquid ATM contracts print every minute (SPY 0DTE, NVDA/AAPL weekly: 98–100% of minutes). Thinner ones don't (SPY next-weekly ATM 66%, META weekly 47%, gaps up to 12 min). NVDA weekly ATM: first print after a decision point at median 0.9 s, p90 4.2 s. | 1-min bars are enough for timing on liquid contracts. Liquidity filters are required. |
| Where a trade print sits within the Schwab bid/ask is bimodal: ~45% near the bid, ~45% near the ask, median exactly mid. 20–64% of 5-min bar closes lie outside the quote at the bar's end, i.e. stale. | Treat a print as a noisy estimate of mid and add half the spread. Fill only on prints **after** the decision. |
| Median ATM bid/ask spread (1–7 DTE): SPY/QQQ/IWM/NVDA/TSLA under ~2%; AAPL/AMZN/META/NFLX/AMD 2–6%; MSFT/GOOGL 6–8%. 0DTE OTM: 20–60%. | Model costs per ticker × DTE × moneyness × premium. Add a spread filter at entry. |
| The equity zip has all-US 1-min bars from **2021-06-18 to 2026-06-18**. Rolled up to 5 min it matches Alpaca SIP exactly. It is **not split-adjusted** (NVDA 1208.88 → 121.79 on 2024-06-10) and contains **bad prints** (NVDA 2024-06-10 high 195.95, true high ~123). | Detect and adjust splits. Filter outliers. Build levels from filtered regular-session minutes. |
| The sibling bot's `research_bars_5m` has ~23% of the option contract-days this test needs and only 5-min resolution. Where it has a contract-day, the bars are complete and identical to Alpaca. | Use it for validation, not as a bar source. |
| Alpaca options: single-leg market/limit/stop/stop_limit (the docs pages conflict), no extended hours. From **15:30 ET on expiration day**, Alpaca evaluates expiring positions and blocks new opening orders on them. | 0DTE entry and exit cutoffs (§7.5). Verify stop semantics on paper before any live use. |
| The PDT rule was eliminated 2026-06-04 (per user). | Not a constraint. |

## 4. Architecture

```
equity-data.zip (1-min, 2021-06-18 → 2026-06-18) ─┐
Alpaca SIP 1-min stock bars (2026-06-18 → freeze) ┴─► stocks.py ─► lake/stock_1m/symbol=X/year=YYYY.parquet
                                                              └─► lake/corporate_actions.parquet (detected splits)
calendar.py (exchange_calendars XNYS) + events.py (FOMC, FRED release dates, computed expirations, earnings)
                                                              ─► lake/calendar/sessions.parquet, events.parquet
features.py (point-in-time: VWAP, σ-bands, RSI, ATR, ADX, BB/KC, opening range, gap, levels, SPY regime)
setups/  orb · vwap · mean_reversion · gaps_levels · squeeze      ─► signals (decision_time, ticker, direction, invalidation spec)
stage1.py  forward stock returns per signal → stage-1 report (setups that pass go to stage 2)

ladders.py        Alpaca contract listing  ─► lake/contracts/underlying=X/week=YYYY-Www.parquet
option_bars.py    on-demand 1-min bars for candidate contracts of passing-setup signals
                                            ─► lake/option_1m/underlying=X/date=YYYY-MM-DD.parquet
trades.py         on-demand ticks around entries/exits of finalists ─► lake/option_trades/...
costs.py          half-spread model from Schwab contract_greeks (sibling DB) ─► lake/costs/model.parquet
engine.py         event-time simulator: signal → contract → entry fill → exits → trade log
evaluate.py       metrics, day-block bootstrap, splits by DTE/weekday/event/regime, edge-decay, stress
ledger.py         append-only record of every configuration evaluated (multiple-testing ledger)
cli.py            `uv run python -m src.options_research <command>`
```

The lake root is `data/options_lake/` (gitignored). Reports go to `reports/options_research/`
(committed, Markdown, aggregate numbers only).

New dependencies: `duckdb`, `pyarrow`, `exchange-calendars`.

## 5. Data layer

### 5.1 Stock minute bars (`stocks.py`)
- **Ingest.** For each trading day, read `minute_aggs/YYYY/MM/DATE.csv.gz` from the zip as a
  stream, keep the 12 tickers, and convert `window_start` (epoch ns, UTC) to a tz-aware timestamp
  marking the **bar start**. Keep 04:00–20:00 ET. Write Parquet partitioned by symbol/year.
- **Tail.** 2026-06-18 through the freeze date comes from Alpaca `/v2/stocks/bars?timeframe=1Min&feed=sip`.
  On overlapping days, zip and Alpaca must agree exactly (validation check).
- **Bad prints.** Flag a 1-min bar when its high or low deviates from the rolling 15-minute median
  close by more than max(8 × rolling MAD, 1.5%). Flagged extremes are clipped to that bar's
  open/close range for level and feature computation. Raw values are kept.
  Pre-market bars count toward pre-market high/low only when volume ≥ 100 shares.
- **Splits.** Detect candidates where the RTH open / prior RTH close ratio is within 3% of a split
  ratio (2, 3, 4, 5, 10, 15, 20 or reciprocals) and the day's volume ratio confirms. Produce
  `corporate_actions.parquet` with an adjustment factor. Detection must find at least NVDA
  2021-07-20 (4:1), AMZN 2022-06-06 (20:1), GOOGL 2022-07-18 (20:1), TSLA 2022-08-25 (3:1) and
  NVDA 2024-06-10 (10:1). Any additional detections are listed for manual confirmation.
  Multi-day features (prior-day levels, gap %, average volumes, ATR history) use split-adjusted
  series. Same-day prices stay raw, matching the unadjusted option strikes of that day.

### 5.2 Calendar and events (`calendar.py`, `events.py`)
- **Sessions.** `exchange_calendars` XNYS: open/close per day, half days (13:00 close), holidays.
  All cutoffs are relative to that day's close.
- **Events table** (`date, time_et, type, tier, source, actual_vs_scheduled`):
  - **Tier 1:** FOMC decision (14:00) and press conference (14:30), from Fed historical calendars.
    CPI and Employment Situation (08:30).
  - **Tier 2:**
    - PPI, PCE (Personal Income & Outlays), retail sales and GDP (08:30).
    - JOLTS (10:00), ISM manufacturing/services (10:00) and Conference Board consumer confidence
      (10:00).
    - FOMC minutes (14:00), plus Fed chair testimony and Jackson Hole as a manual list.
  - **Macro release dates.** BLS/BEA/Census dates use **actual** release dates from the FRED
    release-dates API (needs `FRED_API_KEY`). Shutdown-delayed releases, e.g. fall 2025, are
    handled that way. ISM and Conference Board dates come from their published schedules as a
    manual CSV, marked `source=manual`.
  - **Market structure** (computed): monthly OPEX (3rd Friday), quarterly quad witching, VIX
    expiration (Wednesday 30 days before the next month's 3rd Friday, exchange-holiday adjusted),
    month-end, quarter-end, Russell reconstitution (manual dates).
  - **Earnings** for single names: date and BMO/AMC from yfinance, with a spot check of ≥10
    events against issuer IR pages recorded in the M1 report.

### 5.3 Strike ladders (`ladders.py`)
- For each underlying and ISO week, list contracts with `status=inactive`. Covered expirations
  run from the week's Monday to Monday + 20 days; strikes span the week's **raw (unadjusted)** RTH
  range ± 10%, because strikes that week are unadjusted too. Standard contracts only: the OCC root equals the ticker and the multiplier is 100.
  Nonstandard or adjusted contracts are excluded.
- A contract in the ladder is **eligible** at decision time only if it passes the prior-print
  liquidity filter (§7.2). Listing alone doesn't prove the contract existed at that moment.

### 5.4 Option minute bars (`option_bars.py`), on demand
- Runs **only for signals from setups that passed stage 1**.
- For each ticker-day with such signals: collect the candidate contracts for every signal (§7.1,
  including neighboring strikes in case ATM moves) and batch-request 1-min bars from 09:30 to
  close. Up to 100 symbols per request; follow `next_page_token`.
- Cache per underlying/day. A manifest records the request parameters, fetch time and bar counts.
  Re-runs skip cached symbols.

### 5.5 Option trades (`trades.py`), finalists only
For finalist configurations (§9.4), fetch ticks from 2 minutes before to 2 minutes after each entry
and exit decision to validate fill assumptions (§9.4).

### 5.6 Cost model (`costs.py`)
- **Source:** sibling DB `contract_greeks` (Schwab), 2026-08-21 → freeze. Uses `bid`, `ask`,
  `underlying_spot`, `strike`, `dte`, `bucket_time`; rows need `bid > 0` and `ask > bid`.
- **Half-spread `h`** = median of (ask − bid)/2 in **dollars**, grouped by underlying × DTE bucket
  {0, 1–2, 3–7, 8+} × moneyness {ITM > 0.5%, ATM ±0.5%, OTM 0.5–2%, OTM > 2%} × premium bucket
  {<1, 1–3, 3–10, ≥10} × time-of-day {09:30–10:00, 10:00–15:00, 15:00–close}. Sparse cells
  (n < 30) back off hierarchically: drop time-of-day, then premium, then moneyness. Floor
  `h ≥ $0.005`.
- **Regime scaling:** `h × clip(RV_prev / RV_cal, 1, 3)`. RV_prev is the prior session's SPY
  realized 1-min volatility; RV_cal is its median over the calibration window.
- **Event windows:** `h × 2` from 10 minutes before to 10 minutes after any Tier 1/2 intraday
  release.
- **Fees:** $0.05 per contract per side (assumption, §12).
- **Stress runs:** h × 1.5 and h × 2.0 on every stage-2 result.

### 5.7 Validation checks (in the M1/M4 reports)
- Zip vs Alpaca SIP stock bars on overlap days: identical OHLCV.
- Our option 1-min bars rolled up to 5 min vs `research_bars_5m` on a random ≥1% sample of
  overlapping contract-days: identical. This uses the correct window convention (both sides
  start-inclusive, end-exclusive).
- Coverage: share of stage-2 signals with an eligible contract, by ticker × month × DTE.
- Split detections, bad-print counts per ticker-year, and an events-table row count per type/year.

## 6. Setups (stage 1 signals)

Common rules:
- **Inputs:** 1-min stock bars. A signal evaluated on the bar starting at `t` is known at
  **decision time `T = t + 60 s`**. Features use only bars ending at or before `T`.
- **ATR5** = ATR(14) on 5-min bars built from 1-min bars.
- **VWAP** is session VWAP from 09:30 on the typical price (h+l+c)/3.
- **σ** is the volume-weighted standard deviation of typical price around VWAP since 09:30.
- **RSI** is RSI(14) on 5-min closes. **ADX** is ADX(14) on 5-min bars.
- **Signal window:** 10:00–15:00 ET unless stated. Cutoffs in §7.5 also apply.
- **Frequency:** one signal per ticker × setup × direction per day unless stated.
- **Invalidation:** every signal carries an invalidation rule evaluated on 1-min closes.

| ID | Setup | Long (call) trigger; short (put) is the mirror | Invalidation |
|---|---|---|---|
| ORB15 / ORB30 | Opening range breakout | OR = high/low of 09:30–09:45 (or 10:00). First 1-min close > OR high between OR end and 11:30. OR volume ≥ 1.2 × median OR volume of the prior 20 sessions. | 1-min close < OR midpoint |
| VWAP_RECLAIM | VWAP reclaim | ≥ 30 consecutive 1-min closes below VWAP, then a close ≥ VWAP + 0.1 × ATR5 | Close < VWAP − 0.1 × ATR5 |
| VWAP_PULLBACK | Trend pullback | SPY regime up (SPY close > SPY VWAP and SPY VWAP 30-min slope > 0). Ticker closes above VWAP for ≥ 30 min, then a bar low ≤ VWAP + 0.1 × ATR5 and close > VWAP. Cooldown 30 min; max 2 per day. | Close < VWAP − 0.1 × ATR5 |
| MEANREV | Mean reversion (fade) | Ticker ADX < 20. Close ≤ VWAP − 2.5σ and RSI ≤ 25. Max 2 per day, cooldown 30 min. | Close < signal-bar low − 0.1 × ATR5 |
| GAP_GO | Gap-and-go | Gap = RTH open / prior adjusted close − 1 ≥ +0.75%. After 09:45, first close > pre-market high (filtered). Window until 11:30. | Close < 09:30–09:45 low |
| GAP_FILL | Gap fade | Gap ≤ −0.75%. Before 11:00, first close > 09:30–09:45 high (bias toward prior close; this is the call side). | Close < 09:30–09:45 low |
| PDL_BREAK | Prior-day level break | 09:45–15:00. First close > prior RTH high (adjusted, filtered) + 0.05 × ATR5. | Close < prior RTH high − 0.1 × ATR5 |
| SQUEEZE | Squeeze breakout | 5-min BB(20, 2σ) inside KC(20, 1.5 × ATR20) for ≥ 6 consecutive 5-min bars, then a 5-min close > upper BB. Decision time is that 5-min bar's end. | 5-min close < KC midline (EMA20) |

The puts mirror each trigger. For example, GAP_GO on a gap down triggers on a close < pre-market
low, and GAP_FILL on a gap up triggers on a close < the 09:30–09:45 low.

Parameters above are **pre-registered**. Changing any of them creates a new ledger entry (§9.3).

## 7. Stage 2 — option simulation (`engine.py`)

### 7.1 Contract choice (4 variants)
At decision time `T`, using the stock price `S_T` (last 1-min close):
- **Expiry:** `NEAR` = the earliest expiration ≥ today. `WEEK` = the earliest expiration ≥ today + 5
  calendar days.
- **Strike:** `ATM` = the eligible strike nearest `S_T`. `OTM1` = the next eligible strike further
  out of the money (above ATM for calls, below for puts).
- Contract choice is never switched to a different strike or expiry to find a fill. If the chosen
  contract is ineligible, the signal is logged `no_eligible_contract`.

### 7.2 Eligibility and liquidity filter (point-in-time)
A contract is eligible at `T` only if **all** of these hold:
- ≥ 3 one-minute option bars with prints in `[T − 15 min, T)`
- last print ≥ $0.50
- modeled full spread `2h / last print ≤ 5%`
- not a nonstandard contract

### 7.3 Entry fill
- **Latency `L`:** base = 0 whole minutes. Entry uses the first 1-min option bar whose start is
  ≥ `T + L`.
- **Price:** entry price `E` = that bar's **open** (the first print in the minute) **+ h**. Fees
  are tracked separately and deducted in the trade's net P&L and return.
- **Timeout:** no bar starting in `[T + L, T + L + 2 min]` → `unfilled_entry` (logged).
- **Edge-decay runs:** L ∈ {0, 1, 2, 5} minutes, reported for every stage-2 configuration.

### 7.4 Exits (first to occur; evaluated minute by minute after entry)
1. **Premium stop / target** (entry price `E`, two pre-registered pairs: −30%/+50% and −50%/+100%).
   - **Stop trigger:** a 1-min bar with `low − h ≤ E × (1 − s)`.
     **Fill:** the next available bar's open − h − fees. Gaps fill at whatever that price is, and
     stop slippage is recorded.
   - **Target trigger:** `high − h ≥ E × (1 + g)`.
     **Fill:** exactly `E × (1 + g)` − fees, modeling a resting sell limit.
   - **Both in the same bar:** assume the stop hit first.
2. **Setup invalidation.** Checked on 1-min stock closes. Fill at the open of the first option bar
   starting ≥ invalidation decision time − h − fees.
3. **Time stop.** 60 minutes after entry. Fill as in 2.
4. **Hard exit.** At the cutoff in §7.5. Fill as in 2.

**No option bar available at exit:** use the first subsequent bar. If none exists before close,
exit at the last print − 2h − fees, flagged `forced_stale_exit`.

### 7.5 Session cutoffs (relative to that day's close `C`; normal day C = 16:00)
| Contract | Last entry | Hard exit |
|---|---|---|
| 0DTE (expires today) | C − 60 min (15:00) | C − 35 min (15:25) |
| All others | C − 45 min (15:15) | C − 15 min (15:45) |

### 7.6 Position rules
- One open position per ticker × setup × config. Signals arriving while one is open are ignored
  and counted.
- Results are per trade: return on premium and $ per 1 contract. There is no sizing or portfolio
  aggregation in round 1.

## 8. Stage 1 — stock-level evaluation (`stage1.py`)

### 8.1 Metrics
For each signal:
- The signed forward return from the open of the 1-min bar starting at `T` to +30 min, **+60 min
  (primary)** and the §7.5 hard-exit time.
- MFE/MAE over 60 min.

### 8.2 Development period
2021-06-18 → 2025-12-31.

### 8.3 Pass criteria (all required, primary horizon)
- Day-block-bootstrap t-stat ≥ 3.0, which is roughly Bonferroni across 18 setup × direction tests
  at α = 0.05.
- Mean has the same sign in ≥ 4 of 5 calendar years (2021 H2 counts as a year).
- **Cost-aware:** mean signed stock move in the signal's direction ≥ 1.5 × break-even move.
  - Break-even move = (2h + 2 fees) / (Δ × S).
  - Δ = 0.5 for ATM; h comes from the cost model at the median premium/time for that ticker and the
    NEAR expiry.
  - Evaluated on the pooled median across tickers, with a per-ticker table.
- ≥ 300 signals.

### 8.4 Output
Stage-1 report with a pass/fail table. **User checkpoint** before M4.

### 8.5 Split handling check
Signals within ±1 day of detected splits are flagged in reports. None may use unadjusted
multi-day features.

### 8.6 Events in stage 1
Every signal is tagged with events for its day and whether a Tier 1/2 intraday release falls
inside `[T − 15 min, T + 70 min]`. Reports show results with and without event days.

## 9. Evaluation (`evaluate.py`, `ledger.py`)

### 9.1 Periods and holdout protocol
- **Stage-2 development:** 2024-01-02 → 2025-12-31.
- **Holdout:** 2026-01-02 → 2026-09-11, for both stages.
  - Data loaders **refuse** holdout dates unless called with `holdout=True`. Holdout runs also
    require a ledger entry naming the frozen config hash.
  - One holdout run per finalist configuration. A repeat run is recorded as such and reported.

### 9.2 Stage-2 grid (per passing setup × direction)
- Core: 4 contract variants × 2 exit pairs × 2 event modes = **16 configurations**.
- Descriptive only (not selectable winners): latency variants and cost stress.

**Event modes:**
- `event_blind`: no special handling.
- `event_aware`:
  - No entries from 15 minutes before to 10 minutes after any Tier 1/2 intraday release.
  - Open positions are closed at 13:55 on FOMC days.
  - No NEAR-expiry entries on single-name earnings days before 10:00.

### 9.3 Multiple-testing ledger
Every evaluated configuration is appended with timestamp, git commit, config hash, dataset
version, period and headline metrics. Reports show the count of configurations tried and the
expected number of false passes under the null.

### 9.4 Stage-2 pass criteria (development period, base costs, L = 0)
- ≥ 200 filled trades.
- Mean return per trade (on premium) after costs > 0, with **day-block bootstrap** 95% CI lower
  bound > 0 (10,000 resamples).
- Profit factor ≥ 1.2.
- Positive in ≥ 60% of calendar quarters.
- Still mean > 0 at **h × 1.5**.
- Still mean > 0 **excluding the 5 best days**.
- Mean > 0 at L = 1 minute (timing robustness).

**Finalists** are passing configurations, capped at the top 3 by CI lower bound per setup.
For each finalist:
- Tick-trade fill validation: the median absolute difference between the modeled entry/exit price
  and the first tick after decision time + L, reported in dollars and as a share of h.
- Then the holdout run.
- **Holdout pass:** mean after costs > 0 and profit factor ≥ 1.1.

### 9.5 Reporting dimensions
Every stage-2 result is broken down by:
- ticker and actual DTE (0, 1, 2, 3, 4, 5+)
- weekday and month/quarter
- event tag and volatility regime (RV tercile)
- entry time-of-day bucket and exit reason (stop / target / invalidation / time / hard / stale)

It also reports:
- the unfilled and `no_eligible_contract` rates
- stop slippage distribution
- the edge-decay curve across latency variants

## 10. Testing strategy
- TDD for all modules. Unit tests are offline and use synthetic fixtures. No vendor data is
  committed.
- **Must-have tests:**
  - `alpaca_data`: rejects non-allowlisted hosts/paths, exposes no non-GET capability, never reads
    `ALPACA_API_KEY`, and handles pagination and 429 backoff (mocked).
  - **Lookahead:** perturbing any bar after `T` leaves every signal at `T` unchanged, for every setup.
  - Timestamp conventions: bar start vs end, and window boundaries start-inclusive/end-exclusive.
  - Fill logic: stop and target in the same bar, gap through stop, missing bars, forced stale exit,
    latency, entry timeout.
  - Cutoffs: 0DTE vs other expiries, half-days, DST transitions.
  - Split detection on synthetic series, and bad-print clipping.
  - Cost model: hierarchical backoff, regime scaling, event multiplier.
  - Holdout guard: loaders refuse holdout dates without the flag.
- **Integration checks** read the real zip/Alpaca/DB and are marked and skipped when unavailable:
  the known split detections, zip vs SIP identity, and 1-min → 5-min vs `research_bars_5m`
  identity.

## 11. Milestones (each ends with a report in `reports/options_research/`)

| M | Deliverable | Checkpoint |
|---|---|---|
| M1 | Package skeleton, safe Alpaca client, calendar/events, stock ingest (zip + tail), splits, bad prints, validation report | — |
| M2 | Cost model from Schwab quotes + stress, report | — |
| M3 | Features + 9 setups + stage-1 evaluation (dev period), report | **User reviews which setups pass** |
| M4 | Ladders + on-demand 1-min option bars for passing setups, validation vs bot data, coverage report | — |
| M5 | Stage-2 engine, dev-period grid, edge-decay, event modes, stress, report | **User reviews finalists** |
| M6 | Tick-trade fill validation for finalists + single holdout run, final report | **User decision on phase 2 (verticals)** |

## 12. Assumptions to confirm or calibrate
| Item | Default | Revisit when |
|---|---|---|
| Fees | $0.05/contract/side | Confirm Alpaca's current options fee schedule |
| Min premium | $0.50 | M2 report shows cost vs premium |
| Max spread | 5% of premium | M2 report |
| Prior-print filter | ≥ 3 one-minute bars with prints in the last 15 min | M4 coverage report |
| Exit pairs | −30%/+50%, −50%/+100% | Fixed for round 1 (pre-registered) |
| Time stop | 60 min | Fixed for round 1 |
| FRED API key | Required for macro release dates | User provides `FRED_API_KEY` before M1 events work |
| Stop-order semantics at Alpaca | Unknown trigger basis | Paper test before any live phase |
| Level 3 / multi-leg support | Unconfirmed | Before phase 2 |
