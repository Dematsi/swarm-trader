"""M1 (data foundation) and M2 (cost model) Markdown reports — aggregates only, safe to commit."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from src.options_research.config import lake_root, reports_dir
from src.options_research.corporate_actions import EXPECTED_SPLITS, load_splits
from src.options_research.events_sources import load_events
from src.options_research.print_checks import checks_path


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


# The lake writes exactly one file per ET trading session:
# stock_1m/<SYM>/<YYYY>/<YYYY-MM-DD>.parquet. `ts` is UTC, and winter post-market bars
# (19:00-19:59 ET) land on the NEXT UTC calendar day, so grouping/day-counting off `ts`
# directly (e.g. `year(ts)`, `CAST(ts AS DATE)`) inflates day counts and can misattribute
# the year. Extract the session date from the file name instead (exact, no ICU/`AT TIME
# ZONE` dependency).
_SESSION_DATE_FROM_FILENAME = r"CAST(regexp_extract(filename, '(\d{4}-\d{2}-\d{2})\.parquet$', 1) AS DATE)"


def _stock_aggregates(root: Path) -> pd.DataFrame:
    pattern = (root / "stock_1m" / "*" / "*" / "*.parquet").as_posix()
    if not list((root / "stock_1m").glob("*/*/*.parquet")):
        return pd.DataFrame(columns=["symbol", "year", "days", "rows", "bad_high", "bad_low"])
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        # Data-validation/report exception to the holdout guard (spec §9.1): aggregates only, no strategy metrics.
        return con.execute(
            f"""
            SELECT symbol, year({_SESSION_DATE_FROM_FILENAME}) AS year,
                   count(DISTINCT filename) AS days, count(*) AS rows,
                   sum(CAST(bad_high AS INTEGER)) AS bad_high, sum(CAST(bad_low AS INTEGER)) AS bad_low
            FROM read_parquet('{pattern}', filename=true, union_by_name=true)
            GROUP BY 1, 2 ORDER BY 1, 2
            """
        ).df()
    finally:
        con.close()


def _largest_bad_print_adjustments(root: Path) -> pd.DataFrame:
    pattern = (root / "stock_1m" / "*" / "*" / "*.parquet").as_posix()
    columns = ["symbol", "session_date", "ts", "high", "high_clean", "low", "low_clean", "close", "volume", "transactions", "excluded", "adjustment"]
    if not list((root / "stock_1m").glob("*/*/*.parquet")):
        return pd.DataFrame(columns=columns)
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        # Data-validation/report exception to the holdout guard (spec §9.1): aggregates only, no strategy metrics.
        return con.execute(
            f"""
            SELECT symbol, {_SESSION_DATE_FROM_FILENAME} AS session_date, ts, high, high_clean, low, low_clean,
                   close, volume, transactions,
                   (high_clean IS NULL OR low_clean IS NULL) AS excluded,
                   greatest(coalesce(high - high_clean, 0), coalesce(low_clean - low, 0)) AS adjustment
            FROM read_parquet('{pattern}', filename=true, union_by_name=true)
            WHERE bad_high OR bad_low
            ORDER BY excluded DESC, adjustment DESC
            LIMIT 20
            """
        ).df()
    finally:
        con.close()


def m1_report(root: Path | None = None) -> str:
    root = root or lake_root()
    stocks = _stock_aggregates(root)
    lines = ["# M1 Data Foundation Report", ""]

    lines += ["## Stock minute coverage", ""]
    if stocks.empty:
        lines.append("No stock minute files found.")
    else:
        lines.append(stocks.pivot(index="symbol", columns="year", values="days").fillna(0).astype(int).to_markdown())
    lines.append("")

    lines += ["## Bad prints", ""]
    if not stocks.empty:
        lines.append(stocks.assign(flagged=stocks["bad_high"] + stocks["bad_low"]).pivot(index="symbol", columns="year", values="flagged").fillna(0).astype(int).to_markdown())
    lines.append("")

    lines += ["## Largest bad-print adjustments", ""]
    flagged = _largest_bad_print_adjustments(root)
    lines.append(flagged.to_markdown(index=False) if not flagged.empty else "No flagged bars.")
    lines.append("")

    lines += ["## Print checks (trade-level confirmation)", ""]
    audit = checks_path(root)
    if audit.exists():
        # Data-validation/report exception to the holdout guard (spec §9.1): aggregates only, no strategy metrics.
        checks = pd.read_parquet(audit)
        years = pd.to_datetime(checks["session_date"]).dt.year
        lines.append(f"- candidates checked: {len(checks)}")
        lines.append("- isolated print = at most 3 trades beyond the band, all reported off-exchange (code D); clean value = most extreme in-band traded price; other candidates keep raw values")
        lines += ["", checks.groupby(["decision", years]).size().unstack(fill_value=0).to_markdown()]
    else:
        lines.append("Not run.")
    lines.append("")

    lines += ["## Splits", ""]
    splits_path = root / "corporate_actions" / "splits.parquet"
    detected = load_splits(root) if splits_path.exists() else pd.DataFrame(columns=["symbol", "day", "ratio", "factor"])
    lines.append(detected.to_markdown(index=False) if not detected.empty else "No splits detected.")
    found = {(r.symbol, r.day, float(r.ratio)) for r in detected.itertuples()}
    missing = sorted(EXPECTED_SPLITS - found)
    extra = sorted(found - EXPECTED_SPLITS)
    lines += [
        "",
        f"- missing expected: {missing if missing else 'none'}",
        f"- additional detections (UNCONFIRMED — not applied to features until confirmed): {extra if extra else 'none'}",
        "",
    ]

    lines += ["## Zip vs Alpaca overlap", ""]
    overlap = _read_json(root / "validation" / "zip_vs_alpaca.json")
    lines.append(pd.DataFrame(overlap).T.to_markdown() if overlap else "Not run.")
    lines.append("")
    lines.append(
        "- Note: per-bar volume differs between vendors (zip vs Alpaca SIP); bars after 2026-06-18 come from "
        "Alpaca, so volume-based features that span that date mix vendors (holdout only)."
    )
    lines.append("")

    lines += ["## Events", ""]
    notes = _read_json(root / "calendar" / "events_notes.json")
    lines.append(f"- FRED: {notes.get('fred', 'unknown')}")
    events_path = root / "calendar" / "events.parquet"
    events = load_events(root) if events_path.exists() else pd.DataFrame(columns=["date", "type", "ticker"])
    if not events.empty:
        years = pd.to_datetime(events["date"]).dt.year
        lines += ["", events.groupby(["type", years]).size().unstack(fill_value=0).to_markdown()]
    lines.append("")

    lines += ["## Earnings spot-check", "", "Verify each row against the issuer's investor-relations page and tick the box.", ""]
    earnings = events[events["type"].astype(str).str.startswith("earnings")] if not events.empty else events
    if not earnings.empty:
        sample = earnings.sample(n=min(10, len(earnings)), random_state=7).sort_values("date")
        lines.append(sample.assign(verified="[ ]")[["ticker", "date", "type", "verified"]].to_markdown(index=False))
    lines.append("")
    return "\n".join(lines)


def m2_report(root: Path | None = None) -> str:
    root = root or lake_root()
    # Data-validation/report exception to the holdout guard (spec §9.1): aggregates only, no strategy metrics.
    table = pd.read_parquet(root / "costs" / "half_spread_table.parquet")
    calibration = _read_json(root / "costs" / "calibration.json")
    level = table[["dte_bucket", "moneyness", "premium", "tod_bucket"]].notna().sum(axis=1) + 1
    lines = ["# M2 Cost Model Report", "", "## Calibration", ""]
    lines += [f"- {k}: {v}" for k, v in calibration.items()]
    lines += ["", "## Cells by level (n >= 30 usable)", ""]
    lines.append(table.assign(level=level, usable=table["n"] >= 30).groupby("level")["usable"].agg(["count", "sum"]).rename(columns={"count": "cells", "sum": "usable"}).to_markdown())
    atm = table[(level == 3) & (table["moneyness"] == "ATM")].copy()
    lines += ["", "## ATM full spread as % of median mid (level 3: underlying x DTE x moneyness)", ""]
    if atm.empty:
        lines.append("No level-3 ATM cells.")
    else:
        atm["spread_pct"] = (200.0 * atm["half_spread"] / atm["mid"]).round(2)
        lines.append(atm.pivot(index="underlying", columns="dte_bucket", values="spread_pct").to_markdown())
    lines += ["", "Stress multipliers applied in stage 2: h x 1.5 and h x 2.0 (spec §5.6).", ""]
    return "\n".join(lines)


def _bps(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame.copy()
    for column in columns:
        out[column] = (out[column] * 1e4).round(2)
    return out


def m3_report(
    evaluation: pd.DataFrame,
    horizons: pd.DataFrame,
    events: pd.DataFrame,
    ticker_means: pd.DataFrame,
    ticker_break_even: pd.Series,
    summary: dict,
    ledger: pd.DataFrame,
) -> str:
    """Stage-1 report (spec §8.4): pass/fail table first, then diagnostics. Returns in bps; aggregates only."""
    from src.options_research.ledger import expected_false_passes

    lines = ["# M3 Stage-1 Report (stock-level evaluation, development period)", ""]
    lines += [f"- {key}: {value}" for key, value in summary.items()]
    lines += ["", "## Pass/fail (primary horizon: +60 min)", ""]
    if evaluation.empty:
        lines.append("No signals.")
    else:
        table = _bps(evaluation, ["mean_ret_60", "pooled_break_even"]).rename(columns={"mean_ret_60": "mean_bps", "pooled_break_even": "break_even_bps"})
        table["t"] = table["t"].round(2)
        table["cost_ratio"] = table["cost_ratio"].round(2)
        columns = ["setup", "direction", "n", "mean_bps", "t", "positive_years", "break_even_bps", "cost_ratio", "pass_n", "pass_t", "pass_years", "pass_cost", "passed"]
        lines.append(table[columns].to_markdown(index=False))
    passed = evaluation[evaluation["passed"].astype(bool)] if not evaluation.empty else evaluation
    names = ", ".join(f"{row.setup} {row.direction}" for row in passed.itertuples())
    lines += ["", f"Passing setup x direction pairs: {len(passed)} of {len(evaluation)}" + (f": {names}" if names else ""), ""]
    lines += [
        "## Criteria (spec §8.3, pre-registered)",
        "",
        "- Day-block bootstrap t >= 3.0 (10,000 resamples of trading days, seed 20260912)",
        "- Mean +60 min return > 0 in >= 4 of the 5 calendar years (2021 H2 counts as a year)",
        "- Mean +60 min return >= 1.5 x pooled break-even move (ATM NEAR option, round-trip half-spreads + fees, delta 0.5)",
        "- >= 300 signals",
        "",
        "## Horizons",
        "",
        _bps(horizons, ["mean_ret_30", "mean_ret_60", "mean_ret_hard", "median_mfe_60", "median_mae_60"]).to_markdown(index=False) if not horizons.empty else "No signals.",
        "",
        "## With and without event days",
        "",
        "Event day = a Tier 1/2 macro release that day, or the ticker's earnings reaction day.",
        "",
        _bps(events, ["mean_all", "mean_ex_event"]).round({"t_all": 2, "t_ex_event": 2}).to_markdown(index=False) if not events.empty else "No signals.",
        "",
        "## Mean +60 min return by ticker (bps)",
        "",
        ticker_means.to_markdown() if not ticker_means.empty else "No signals.",
        "",
        "## Break-even move by ticker (bps, median)",
        "",
        ticker_break_even.rename("break_even_bps").to_frame().to_markdown() if not ticker_break_even.empty else "No signals.",
        "",
        "## Multiple-testing ledger",
        "",
    ]
    stage1_rows = ledger[ledger["stage"] == "stage1"] if not ledger.empty else ledger
    count = int(stage1_rows["config_hash"].nunique()) if not stage1_rows.empty else 0
    lines += [f"- Stage-1 configurations recorded: {count}", f"- Expected false passes under the null (one-sided p at t = 3): {expected_false_passes(count):.3f}", ""]
    return "\n".join(lines)


def write_report(name: str, text: str, directory: Path | None = None) -> Path:
    directory = directory or reports_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path
