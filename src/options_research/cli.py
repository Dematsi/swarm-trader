"""Command line for the options research data foundation: `uv run python -m src.options_research <command>`."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

from src.options_research.config import DATA_FREEZE, REPO_ROOT, UNIVERSE, ZIP_END, ZIP_START, equity_zip_path, lake_root


def _cmd_ingest_stocks(args: argparse.Namespace) -> int:
    from src.options_research.stocks import ingest_zip

    print(json.dumps(ingest_zip(equity_zip_path(), args.start, args.end, workers=args.workers, overwrite=args.overwrite)))
    return 0


def _cmd_ingest_tail(args: argparse.Namespace) -> int:
    from src.options_research.alpaca_data import AlpacaDataClient
    from src.options_research.stocks_alpaca import ingest_alpaca_tail, validate_zip_overlap

    client = AlpacaDataClient()
    print(json.dumps(ingest_alpaca_tail(client, args.start, args.end, overwrite=args.overwrite)))
    sample_days = [date(2022, 1, 11), date(2024, 3, 15), date(2025, 6, 11), date(2026, 6, 1), ZIP_END]
    overlap = validate_zip_overlap(client, sample_days)
    path = lake_root() / "validation" / "zip_vs_alpaca.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overlap, indent=2))
    print(json.dumps(overlap))
    return 0


def _cmd_detect_splits(args: argparse.Namespace) -> int:
    import pandas as pd

    from src.options_research.corporate_actions import daily_rth_summary, detect_splits, write_splits
    from src.options_research.store import load_stock_minutes

    summaries = []
    for symbol in UNIVERSE:
        # Split-detection exception to the holdout guard (spec §9.1): corporate actions only, no strategy metrics.
        minutes = load_stock_minutes([symbol], ZIP_START, DATA_FREEZE, holdout=True)
        summaries.append(daily_rth_summary(minutes))
    splits = detect_splits(pd.concat(summaries, ignore_index=True))
    print(write_splits(splits))
    print(splits.to_string(index=False))
    return 0


def _cmd_build_events(args: argparse.Namespace) -> int:
    from src.options_research.events_sources import build_events, write_events

    events, notes = build_events(ZIP_START, DATA_FREEZE, os.environ.get("FRED_API_KEY"))
    print(write_events(events, notes))
    print(json.dumps(notes))
    return 0


def _cmd_build_costs(args: argparse.Namespace) -> int:
    import psycopg

    from src.options_research.costs import build_cost_table, save_calibration, save_cost_table, session_realized_vol
    from src.options_research.store import load_stock_minutes

    start = datetime.combine(args.start, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(args.end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    with psycopg.connect(os.environ["OPTIONS_DB_URL"]) as conn:
        table = build_cost_table(conn, UNIVERSE, start, end)
    print(save_cost_table(table))
    # Cost-calibration exception to the holdout guard (spec §9.1): SPY realized vol for spread scaling only.
    spy = load_stock_minutes(["SPY"], args.start, args.end, holdout=True)
    rv = session_realized_vol(spy)
    payload = {"rv_cal": float(rv.median()) if len(rv) else None, "sessions": int(len(rv)), "window": f"{args.start}..{args.end}", "cells": int(len(table))}
    print(save_calibration(payload))
    print(json.dumps(payload))
    return 0


def _cmd_report_m1(args: argparse.Namespace) -> int:
    from src.options_research.reports import m1_report, write_report

    print(write_report("m1_data_foundation", m1_report()))
    return 0


def _cmd_report_m2(args: argparse.Namespace) -> int:
    from src.options_research.reports import m2_report, write_report

    print(write_report("m2_cost_model", m2_report()))
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(prog="python -m src.options_research")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest-stocks", help="zip minute bars -> lake")
    p.add_argument("--start", type=date.fromisoformat, default=ZIP_START)
    p.add_argument("--end", type=date.fromisoformat, default=ZIP_END)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=_cmd_ingest_stocks)

    p = sub.add_parser("ingest-tail", help="Alpaca SIP minute bars after the zip + overlap validation")
    p.add_argument("--start", type=date.fromisoformat, default=ZIP_END + timedelta(days=1))
    p.add_argument("--end", type=date.fromisoformat, default=DATA_FREEZE)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=_cmd_ingest_tail)

    sub.add_parser("detect-splits", help="detect splits from lake minutes").set_defaults(func=_cmd_detect_splits)
    sub.add_parser("build-events", help="events table (FRED needs FRED_API_KEY)").set_defaults(func=_cmd_build_events)

    p = sub.add_parser("build-costs", help="half-spread table from Schwab quotes + RV calibration")
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 8, 21))
    p.add_argument("--end", type=date.fromisoformat, default=DATA_FREEZE)
    p.set_defaults(func=_cmd_build_costs)

    sub.add_parser("report-m1").set_defaults(func=_cmd_report_m1)
    sub.add_parser("report-m2").set_defaults(func=_cmd_report_m2)

    args = parser.parse_args(argv)
    return args.func(args)
