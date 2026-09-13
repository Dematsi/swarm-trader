"""Feature code must read lake data only through approved modules (spec §11 M3-0)."""

from pathlib import Path

import src.options_research as pkg

PACKAGE = Path(pkg.__file__).parent
PARQUET_READERS = {"store.py", "reports.py", "stocks_alpaca.py", "corporate_actions.py", "costs.py", "events_sources.py", "print_checks.py"}
STOCK_LAKE_TOUCHERS = {"stocks.py", "store.py", "reports.py", "print_checks.py"}


def _sources():
    return {p.name: p.read_text(encoding="utf-8") for p in PACKAGE.glob("*.py")}


def test_only_approved_modules_read_parquet():
    offenders = sorted(name for name, text in _sources().items() if "read_parquet(" in text and name not in PARQUET_READERS)
    assert offenders == [], f"read lake data through store.load_stock_minutes instead: {offenders}"


def test_only_approved_modules_touch_the_stock_lake_path():
    offenders = sorted(name for name, text in _sources().items() if '"stock_1m"' in text and name not in STOCK_LAKE_TOUCHERS)
    assert offenders == [], f"stock minutes must be read via store.load_stock_minutes: {offenders}"
