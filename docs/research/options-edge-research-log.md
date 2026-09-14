# Options Edge Research Log

A running, human-readable record of what was built, what the data said, what was decided and what
we learned. Newest entries go at the top. Numbers come from the committed reports in
`reports/options_research/` and the ledger `reports/options_research/ledger.jsonl`. Detailed
process records live in git history.

- Spec: `docs/superpowers/specs/2026-09-12-options-edge-research-design.md`
- Plans: `docs/superpowers/plans/`

Status keys: **PRELIMINARY** (awaiting review), **FINAL** (reviewed and merged into the PR branch),
**SUPERSEDED**.

---

## 2026-09-13 — M3 stage 1: stock-level evaluation of the 9 setups — FINAL

Status: all 8 plan tasks were built and reviewed, and the final whole-branch review was completed.
Its single fix wave (ledger integrity, report notes, end-to-end look-ahead test) passed re-review
with results byte-identical. Code head is `bb59615`, pushed to PR #1. The ledger holds 18 schema-2
entries with clean SHA `1231a48`.

**Question.** Does any pre-registered intraday setup predict the underlying stock's move well
enough to pay for an ATM near-expiry option round trip?

**Data and method**
- **Universe and period:** 12 tickers, 2021-06-18 → 2025-12-31 (development period only; no
  2026 holdout data used).
- **Signals:** 51,565 over 1,135 sessions. 62 fall within one session of a split.
- **Primary outcome:** signed stock return from the open of the bar at decision time T to +60 min.
- **Pass rules (spec §8.3, pre-registered):**
  - day-block bootstrap t ≥ 3.0
  - positive in at least 4 of 5 years
  - mean ≥ 1.5 × pooled break-even
  - ≥ 300 signals
- **Break-even:** round-trip half-spreads plus fees of an ATM option expiring that week, with
  delta 0.5. Spreads come from Schwab quotes (Aug–Sep 2026), scaled to each signal's price.
  The pooled break-even is about 4.5 bps.

**Result: 0 of 18 setup × direction pairs pass.**

| Pair | n | Mean +60m (bps) | t | Years > 0 | Cost ratio | Fails on |
|---|---|---|---|---|---|---|
| SQUEEZE long | 3,247 | +4.38 | 2.99 | 5/5 | 0.97 | t (just), cost |
| PDL_BREAK long | 6,201 | +3.19 | 1.60 | 5/5 | 0.70 | t, cost |
| VWAP_PULLBACK long | 5,177 | +2.47 | 1.41 | 4/5 | 0.55 | t, cost |
| GAP_FILL long | 1,272 | +6.28 | 1.03 | 4/5 | 1.38 | t, cost |
| VWAP_RECLAIM long | 4,821 | +1.14 | 0.87 | 4/5 | 0.25 | t, cost |
| GAP_GO short | 1,538 | +4.39 | 0.95 | 3/5 | 0.96 | t, years, cost |
| MEANREV long | 51 | +8.21 | 0.54 | 3/5 | 1.83 | n, t, years |
| MEANREV short | 45 | −46.0 | −1.37 | 2/5 | — | n, t, years, cost |

The remaining ORB, short-side PDL/VWAP and GAP_FILL short pairs sit at or below zero. See
`reports/options_research/m3_stage1.md` for the full table, horizons (+30 min and 15:45 exit),
event-day splits and per-ticker results.

**Final review (2026-09-13).**
- Independent rebuild of 160 signals matched, with 0 mismatches.
- The detectors were re-implemented on real data and matched.
- SQUEEZE long's t of 2.99 is within Monte Carlo noise; cost is the binding criterion.
- The ledger was regenerated with schema 2.

**What the numbers suggest.** These are hypotheses to test, not conclusions.
- **No option edge at +60 min.** The nearest pair (SQUEEZE long) has the right sign in every
  year, but its average move is about one break-even, not the 1.5× required.
- **Long bias.** Long variants of trend/breakout setups are mildly positive in most years. Short
  variants are not. That fits the 2021–2025 upward drift of these names. Returns are raw, not
  adjusted against SPY or beta, so part of any "long edge" may just be market drift.
- **Break-even is roughly fixed.** At about 4.5 bps, per-signal stock moves need to be larger to
  matter. Longer holds (the 15:45 exit), higher-volatility windows or cheaper structures such as
  debit verticals change that arithmetic. Each would be a **new, pre-registered test** recorded in
  the ledger, not a tweak of these.
- **MEANREV rarely fires.** The rule (ADX < 20, 2.5σ from VWAP, extreme RSI) produced fewer than
  60 signals per side in 4.5 years, so it was never testable as specified.
- **Sanity checks passed.**
  - ORB15 long and short both have exactly 2,163 signals, but per-ticker counts differ, so this
    is a coincidence.
  - No signals fall after 2025-12-31.
  - No NaN outcomes.
  - The ledger records 18 configurations with clean commit SHAs.
  - Expected false passes under the null: 18 × 0.00135 ≈ 0.024.

**Decisions pending (user).** Spec §11 says only setups that pass go to M4 (option bars). With 0
passing, the options are:
1. Stop round 1 here and record a negative result.
2. Pre-register a round-2 hypothesis and add it to the ledger. Examples: market-adjusted returns,
   longer horizons, a volatility-regime filter, or debit verticals to lower the break-even.
3. Revisit the cost assumptions with more quote history.

Any new variant counts against the multiple-testing budget.

Rule questions to settle before any M4 work (raised by the final review). Each one changes
pre-registered evaluation rules:
- **NEAR expiry.** Should it be the earliest listed expiration (spec §7.1) instead of that week's
  Friday? SPY/QQQ/IWM had daily expirations for most of the period, so their break-evens are
  overstated early in the week. The pooled verdict does not change.
- **Cost test.** Pooled median vs per ticker. SQUEEZE long clears 1.5× break-even on SPY, QQQ and
  NVDA individually. Restricting tickers after seeing results would be a new ledger configuration
  and must be pre-registered.
- **t tie rule.** The bootstrap t has Monte Carlo error of about ±0.02. SQUEEZE long's t is
  2.97–3.00 across seeds, so a borderline convention is needed.

---

## 2026-09-13 — M3-0 data-readiness gate — FINAL

- **Change:** replaced the causal bad-print filter, which clipped genuine moves, with two-sided,
  trade-confirmed cleaning. Candidates are checked against Alpaca SIP trades: 1–3 off-exchange
  (`D`) outliers outside the band count as isolated.
- **Result:** 1,045 candidate sides on 1,026 of 11.65M bars. 428 were isolated and cleaned; 617
  were genuine and keep raw values. 7 bars consisted only of the bad print, so their clean values
  are empty (not clipped). The audit trail is in `data/options_lake/quality/print_checks.parquet`.
- **Hindsight rule:** clean columns may only feed after-the-window levels. Pre-market high/low is
  readable from 09:37. Prior-day close is raw. `load_stock_minutes` returns clean columns only
  with `clean=True`.
- **Also done:**
  - split volume-adjustment helper
  - recursive data-access guard test
  - UTC timestamps in reports
  - M1 report regenerated
- **Outcome:** the user confirmed the gate on 2026-09-13.

## 2026-09-12 — M1 data foundation and M2 cost model — FINAL

- **Lake:** 15,768 stock day files (1,314 sessions × 12 tickers). Built from Polygon flat files to
  2026-06-18, then Alpaca SIP to 2026-09-11.
- **Splits:** 6 detected, including NFLX 10:1 on 2025-11-17.
- **Events table:** FOMC, FRED macro releases, market structure and earnings.
- **Cost model:** half-spread table from Schwab `contract_greeks`, covering 2026-08-21 → freeze.

---

## Process lessons (for future sessions)

- **Pre-run plan code before handing it off.** Materializing every task's code into the tree and
  running it together (then removing it) caught fixture bugs before execution. Those were a sampling
  step that yielded 377 days instead of 400, and a table formatter printing `12` rather than `12.0`.
- **Look-ahead tests must be adversarial.** A ±5% random perturbation with one seed missed a
  deliberate peek-ahead detector most of the time. Perturbing later bars by ×0.5, ×1.5 and several
  random seeds, plus a test proving a peeking detector fails, made the check meaningful.
- **Cache keys must include every input.** Stage-1 per-symbol caches keyed only by symbol would
  have silently reused results for a different date range. They are now keyed by period.
- **Fingerprint datasets by content, not size.** A same-size file rewrite (for example
  `rebuild-clean`) would otherwise make a re-test look like a duplicate in the ledger. Content
  hashing 13,680 files takes about 150 s cold on Windows, which is accepted.
- **Commit code before recording results.** The ledger stores the git SHA. Running the report on
  a clean tree avoids `-dirty` provenance.
- **Timebox subagents.** One reviewer stalled for 10 minutes. Retrying with a 2-minute
  per-command limit and no background work fixed it.
- **Windows shell gotcha.** Python `print` to a redirected file writes CRLF, so `xargs rm` silently
  failed on `path\r`. Delete explicit paths instead.
- **Negative results are results.** Pre-registration plus the ledger means "0 of 18" is
  informative. Retuning parameters after seeing it would invalidate the test.
- **Look-ahead tests compare only what the signal decides.** Execution fills, such as the entry at
  the open of the bar starting at T, legitimately depend on bar T. An end-to-end test that
  compared `entry_price` failed for that reason, not because of a leak.
- **Don't delete tracked outputs before regenerating them.** Deleting the tracked ledger made
  `git_commit` report `-dirty`. The dirty check now ignores `reports/options_research/`.
- **Independent rebuilds make a negative result trustworthy.** The final reviewer rebuilt 160
  signals from raw minutes and re-implemented detectors on real data, with 0 mismatches. Keep doing
  this before accepting any pass/fail verdict.
