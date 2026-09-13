"""Feature code must read lake data only through approved modules (spec §11 M3-0).

Scans the whole package tree (not just the top-level files) so a new subpackage can't quietly
bypass these rules by living one directory deeper.
"""

import re
from pathlib import Path

import src.options_research as pkg

PACKAGE = Path(pkg.__file__).parent

PARQUET_READERS = {"store.py", "reports.py", "stocks_alpaca.py", "corporate_actions.py", "costs.py", "events_sources.py", "print_checks.py"}
STOCK_LAKE_TOUCHERS = {"stocks.py", "store.py", "reports.py", "print_checks.py"}
HINDSIGHT_COLUMN_USERS = {"quality.py", "stocks.py", "store.py", "print_checks.py", "reports.py"}
LOOK_AHEAD_IMPORTERS = {"stocks.py", "print_checks.py", "reports.py", "cli.py"}

_PARQUET_READ_MARKERS = ("read_parquet(", "read_table(", "ParquetFile(")
_STOCK_LAKE_MARKERS = ('"stock_1m"', "'stock_1m'")
_HINDSIGHT_COLUMN_MARKERS = ("high_clean", "low_clean", "bad_high", "bad_low")
_LOOK_AHEAD_IMPORT_RE = re.compile(r"(from|import)\s+src\.options_research(\.|\s+import\s+)(quality|print_checks)")


def _sources() -> dict[str, str]:
    """POSIX path (relative to the package root) -> file text, for every .py file except __pycache__."""
    sources = {}
    for path in PACKAGE.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        key = path.relative_to(PACKAGE).as_posix()
        sources[key] = path.read_text(encoding="utf-8")
    return sources


def test_scan_finds_the_package_at_all():
    # A glob that silently matched nothing would make every rule below vacuously pass.
    sources = _sources()
    assert "store.py" in sources, "recursive scan of the options_research package found no store.py"
    assert "quality.py" in sources, "recursive scan of the options_research package found no quality.py"


def test_only_approved_modules_read_parquet():
    offenders = sorted(
        name
        for name, text in _sources().items()
        if any(marker in text for marker in _PARQUET_READ_MARKERS) and name not in PARQUET_READERS
    )
    assert offenders == [], f"read lake data through store.load_stock_minutes instead: {offenders}"


def test_only_approved_modules_touch_the_stock_lake_path():
    offenders = sorted(
        name
        for name, text in _sources().items()
        if any(marker in text for marker in _STOCK_LAKE_MARKERS) and name not in STOCK_LAKE_TOUCHERS
    )
    assert offenders == [], f"stock minutes must be read via store.load_stock_minutes: {offenders}"


def test_only_approved_modules_touch_hindsight_columns():
    offenders = sorted(
        name
        for name, text in _sources().items()
        if any(marker in text for marker in _HINDSIGHT_COLUMN_MARKERS) and name not in HINDSIGHT_COLUMN_USERS
    )
    assert offenders == [], (
        "bad_high/bad_low/high_clean/low_clean are hindsight columns computed from future bars; "
        f"only the approved cleaning/loading modules may reference them: {offenders}"
    )


def test_only_approved_modules_import_look_ahead_detectors():
    offenders = sorted(
        name
        for name, text in _sources().items()
        if _LOOK_AHEAD_IMPORT_RE.search(text) and name not in LOOK_AHEAD_IMPORTERS
    )
    assert offenders == [], (
        "find_print_candidates looks at bars after the one it is judging (a snap-back window), so "
        "quality.py/print_checks.py must never be imported into feature code or a live filter: "
        f"{offenders}"
    )
