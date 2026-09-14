"""Append-only multiple-testing ledger (spec §9.3). One JSON line per evaluated configuration."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from src.options_research.config import REPO_ROOT, UNIVERSE, lake_root, reports_dir
from src.options_research.store import stock_minute_files

ONE_SIDED_P_AT_T3 = 0.00135
LEDGER_KEY = ("stage", "setup", "direction", "config_hash", "dataset_version")
_DATASET_INPUTS = (("calendar", "events.parquet"), ("corporate_actions", "splits.parquet"), ("quality", "print_checks.parquet"), ("costs", "half_spread_table.parquet"))


def ledger_path(directory: Path | None = None) -> Path:
    return (directory or reports_dir()) / "ledger.jsonl"


def config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def git_commit(repo: Path = REPO_ROOT) -> str:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    return f"{head}-dirty" if dirty else head


def _hash_stock_files(digest, symbols, start: date, end: date, root: Path) -> None:
    for path in stock_minute_files(symbols, start, end, root=root):
        digest.update(f"{path.parent.parent.name}/{path.parent.name}/{path.name}\n".encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)


def dataset_version(start: date, end: date, root: Path | None = None, symbols=UNIVERSE, extra_ranges: tuple[tuple[date, date], ...] = ()) -> str:
    """Fingerprint of the lake inputs: stock day-file contents in the period (plus any extra ranges, e.g. cost
    calibration) and the events/splits/print-check/cost files."""
    root = root or lake_root()
    digest = hashlib.sha256()
    for range_start, range_end in ((start, end), *extra_ranges):
        _hash_stock_files(digest, symbols, range_start, range_end, root)
    for parts in _DATASET_INPUTS:
        path = root.joinpath(*parts)
        digest.update(path.read_bytes() if path.exists() else b"missing")
    return digest.hexdigest()[:16]


_CODE_VERSION_FILES = ("features.py", "levels.py", "stage1.py", "evaluate.py")
PACKAGE_ROOT = Path(__file__).resolve().parent


def code_version(root: Path = PACKAGE_ROOT) -> str:
    """16-hex SHA-256 over the relative path plus bytes of every module whose behaviour drives stage-1 results."""
    paths = [root / name for name in _CODE_VERSION_FILES] + list((root / "setups").glob("*.py"))
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\n")
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def read_ledger(path: Path | None = None) -> pd.DataFrame:
    path = path or ledger_path()
    if not path.exists():
        return pd.DataFrame()
    return pd.DataFrame([json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])


def append_entries(entries: list[dict], path: Path | None = None) -> int:
    path = path or ledger_path()
    existing = read_ledger(path)
    seen = {tuple(record.get(k) for k in LEDGER_KEY) for record in existing.to_dict("records")}
    new = [e for e in entries if tuple(e.get(k) for k in LEDGER_KEY) not in seen]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for e in new:
                handle.write(json.dumps(e, sort_keys=True, default=str) + "\n")
    return len(new)


def expected_false_passes(n_tests: int) -> float:
    return n_tests * ONE_SIDED_P_AT_T3


def _number(value) -> float | None:
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)


def stage1_entries(
    evaluation: pd.DataFrame,
    setup_params: dict,
    eval_params: dict,
    commit: str,
    dataset: str,
    period: str,
    now: datetime | None = None,
    shared_params: dict | None = None,
    code: str | None = None,
) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    shared_params = shared_params or {}
    code = code or ""
    entries = []
    for row in evaluation.to_dict("records"):
        config = {
            "setup": row["setup"],
            "direction": row["direction"],
            "setup_params": setup_params[row["setup"]],
            "shared_params": shared_params,
            "evaluation": eval_params,
            "code_version": code,
        }
        entries.append({
            "timestamp": now.isoformat(),
            "stage": "stage1",
            "setup": row["setup"],
            "direction": row["direction"],
            "config_hash": config_hash(config),
            "code_version": code,
            "git_commit": commit,
            "dataset_version": dataset,
            "period": period,
            "n": int(row["n"]),
            "mean_ret_60": _number(row["mean_ret_60"]),
            "t": _number(row["t"]),
            "positive_years": int(row["positive_years"]),
            "pooled_break_even": _number(row["pooled_break_even"]),
            "cost_ratio": _number(row["cost_ratio"]),
            "pass_n": bool(row["pass_n"]),
            "pass_t": bool(row["pass_t"]),
            "pass_years": bool(row["pass_years"]),
            "pass_cost": bool(row["pass_cost"]),
            "passed": bool(row["passed"]),
            "schema": 2,
        })
    return entries
