"""Universe, study periods and paths for the options edge research (spec §1, §9.1)."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

UNIVERSE: tuple[str, ...] = ("SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL", "AMZN", "MSFT", "GOOGL", "META", "AMD", "NFLX")
ETFS: frozenset[str] = frozenset({"SPY", "QQQ", "IWM"})
TZ_ET = "America/New_York"

ZIP_START = date(2021, 6, 18)
ZIP_END = date(2026, 6, 18)
DATA_FREEZE = date(2026, 9, 11)
STAGE1_DEV = (date(2021, 6, 18), date(2025, 12, 31))
STAGE2_DEV = (date(2024, 1, 2), date(2025, 12, 31))
HOLDOUT = (date(2026, 1, 2), DATA_FREEZE)


def lake_root() -> Path:
    return Path(os.environ.get("OPTIONS_LAKE_ROOT", REPO_ROOT / "data" / "options_lake"))


def reports_dir() -> Path:
    return Path(os.environ.get("OPTIONS_REPORTS_DIR", REPO_ROOT / "reports" / "options_research"))


def equity_zip_path() -> Path:
    return Path(os.environ.get("OPTIONS_EQUITY_ZIP", r"C:\Users\tsedi\Downloads\equity-data.zip"))
