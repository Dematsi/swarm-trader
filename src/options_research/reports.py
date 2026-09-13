"""M1 (data foundation) and M2 (cost model) Markdown reports — aggregates only, safe to commit."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from src.options_research.config import lake_root, reports_dir
from src.options_research.corporate_actions import EXPECTED_SPLITS, load_splits
from src.options_research.events_sources import load_events


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _stock_aggregates(root: Path) -> pd.DataFrame:
    pattern = (root / "stock_1m" / "*" / "*" / "*.parquet").as_posix()
    if not list((root / "stock_1m").glob("*/*/*.parquet")):
        return pd.DataFrame(columns=["symbol", "year", "days", "rows", "bad_high", "bad_low"])
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        return con.execute(
            f"""
            SELECT symbol, year(ts) AS year, count(DISTINCT CAST(ts AS DATE)) AS days, count(*) AS rows,
                   sum(CAST(bad_high AS INTEGER)) AS bad_high, sum(CAST(bad_low AS INTEGER)) AS bad_low
            FROM read_parquet('{pattern}')
            GROUP BY 1, 2 ORDER BY 1, 2
            """
        ).df()
    finally:
        con.close()


def _largest_bad_print_adjustments(root: Path) -> pd.DataFrame:
    pattern = (root / "stock_1m" / "*" / "*" / "*.parquet").as_posix()
    columns = ["symbol", "ts", "high", "high_clean", "low", "low_clean", "close", "bad_close", "volume", "transactions", "adjustment"]
    if not list((root / "stock_1m").glob("*/*/*.parquet")):
        return pd.DataFrame(columns=columns)
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        return con.execute(
            f"""
            SELECT symbol, ts, high, high_clean, low, low_clean, close, bad_close, volume, transactions,
                   greatest(high - high_clean, low_clean - low) AS adjustment
            FROM read_parquet('{pattern}')
            WHERE bad_high OR bad_low OR bad_close
            ORDER BY adjustment DESC
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


def write_report(name: str, text: str, directory: Path | None = None) -> Path:
    directory = directory or reports_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path
