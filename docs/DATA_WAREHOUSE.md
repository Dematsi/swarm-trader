# Local Market-Data Warehouse (options research)

Options research in this fork reads from the Postgres database of a **sibling project**,
`C:\Users\tsedi\alpaca-options-trading-bot` (Docker container `alpaca-options-postgres`,
`localhost:5432`, db `alpaca_options`). That project owns the schema and the ingest jobs;
see its `CLAUDE.md` and `docs/DATA_PROVIDERS.md` for how each table is populated.

**This repo is a read-only consumer.** `OPTIONS_DB_URL` in `.env` sets
`default_transaction_read_only=on`, so writes fail at the session level. Don't remove that,
and don't run DDL against this database: the sibling bot trades live (on paper) against it.

Coverage below was profiled on 2026-09-12. Re-check before relying on date ranges.

## Tables that matter for research

| Table | Source | What it is | Coverage (2026-09-12) |
|---|---|---|---|
| `research_bars_5m` (`kind='option'`) | Alpaca OPRA | 5-min option OHLCV, **including expired contracts** (no survivorship bias). Trade-based, so illiquid contracts have missing bars. | 18 underlyings, ~30k contracts, 2024-12-26 → 2026-09-11, 12.5M rows |
| `research_bars_5m` (`kind='stock'`) | Alpaca | 5-min underlying bars (short sample) | 13 symbols, 2026-05-21 → 2026-07-02 |
| `equity_bars_5m` | Alpaca | 5-min underlying OHLCV + `vwap`, `trade_count`. PK is `(symbol, bar_time, feed)`, so **filter `feed='sip'`** or you'll get duplicate bars where IEX rows also exist. | 17 symbols, SIP 2025-01-01 → 2026-09-11 |
| `contract_greeks` | Schwab `/chains` | Full-chain snapshots (~5-min cadence): bid/ask/mark, sizes, Greeks, IV, OI, volume, `underlying_spot`. **Forward-only**: Schwab has no historical Greeks. | 17 underlyings, **2026-08-21 → 2026-09-11 only**, 42M rows, 20 GB |
| `option_contract_meta` | Alpaca | Contract reference data: expiration, strike, type, multiplier, `expiration_type` | ~88k contracts |
| `flow_snapshots_5m` | sibling bot | Per-contract 5-min flow aggregates (buy/sell vol, sweeps, blocks, vol/OI, spread) with forward returns (`fwd_ret_15m`, `fwd_mfe_90m`) | 2026-07-06 → 2026-09-11 |
| `ta_snapshots_5m` | sibling bot | Underlying TA (ATR, ADX, BB, KC, stoch, MFI, CMF, multi-timeframe direction) | 5-min |
| `research_signal_labels` / `scan_candidates` | sibling bot | The sibling bot's gate decisions and labeled outcomes (`mfe_to_expiry`, `mfe_2d`). This is its own strategy's audit trail, not neutral data. | |
| `vix_daily` | CBOE | Daily VIX OHLC | 1990-01-02 → **2026-07-01 (stale)** |

Universe (both bar tables): AAPL, ADBE, AMD, AMZN, GLD, GOOGL, INTC, IWM, META, MSFT, NFLX,
NVDA, QQQ, SLV, SPY, TLT, TSLA (`research_bars_5m` also contains `SLV2`, an adjusted root).

## Symbol formats

- Alpaca / OCC (no padding): `SPY260910C00764000` in `research_bars_5m.symbol`,
  `option_contract_meta.occ_symbol` and `contract_greeks.occ_symbol`.
- Schwab (root space-padded to 6): `SPY   260909C00500000` in `contract_greeks.option_symbol`.
  **Join on `occ_symbol`**, never on `option_symbol`.
- Timestamps are `timestamptz` stored in UTC. Regular session is 13:30–20:00 UTC in EDT and
  14:30–21:00 UTC in EST. Convert to `America/New_York` before any time-of-day logic.

## Backtesting caveats

1. **No historical option quotes before 2026-08-21.** `research_bars_5m` gives trade prices,
   not bid/ask. A fill at a bar's close is optimistic. Model the spread explicitly, e.g. by
   calibrating `spread_pct` by moneyness/DTE/underlying from the 3 weeks of `contract_greeks`
   bid/ask and applying it to bar-based fills.
2. **Missing bars ≠ zero volume ≠ tradable.** A contract with no bar in a bucket had no
   prints. Don't forward-fill a price and assume you could have exited there.
3. **`contract_greeks` is huge and slow.** An unfiltered aggregate takes ~4 minutes. Always
   filter on `(underlying, snapshot_time)` or `bucket_time`, which are indexed.
4. Only ~3 weeks of Greeks/IV exist. Anything IV-based needs IV reconstructed from bar prices
   (Black-Scholes on bar close + underlying close) for the longer 2025–2026 sample.

## Connecting

```python
import os, psycopg
import pandas as pd
from dotenv import load_dotenv
load_dotenv()
with psycopg.connect(os.environ["OPTIONS_DB_URL"]) as conn:
    df = pd.read_sql(
        "SELECT * FROM equity_bars_5m WHERE symbol=%s AND feed='sip' AND bar_time >= %s",
        conn, params=("SPY", "2026-01-01"),
    )
```

Ad-hoc from a shell (no host psql needed):

```bash
docker exec -i alpaca-options-postgres sh -c 'psql -U "$POSTGRES_USER" -d alpaca_options' <<'SQL'
SELECT ...;
SQL
```
