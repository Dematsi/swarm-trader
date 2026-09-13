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


def dataset_version(start: date, end: date, root: Path | None = None, symbols=UNIVERSE) -> str:
    """Fingerprint of the lake inputs: stock day-file contents in the period plus the events/splits/print-check/cost files."""
    root = root or lake_root()
    digest = hashlib.sha256()
    for path in stock_minute_files(symbols, start, end, root=root):
        digest.update(f"{path.parent.parent.name}/{path.parent.name}/{path.name}\n".encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    for parts in _DATASET_INPUTS:
        path = root.joinpath(*parts)
        digest.update(path.read_bytes() if path.exists() else b"missing")
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


def stage1_entries(evaluation: pd.DataFrame, setup_params: dict, eval_params: dict, commit: str, dataset: str, period: str, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    entries = []
    for row in evaluation.to_dict("records"):
        config = {"setup": row["setup"], "direction": row["direction"], "setup_params": setup_params[row["setup"]], "evaluation": eval_params}
        entries.append({
            "timestamp": now.isoformat(), "stage": "stage1", "setup": row["setup"], "direction": row["direction"], "config_hash": config_hash(config),
            "git_commit": commit, "dataset_version": dataset, "period": period, "n": int(row["n"]), "mean_ret_60": _number(row["mean_ret_60"]),
            "t": _number(row["t"]), "passed": bool(row["passed"]),
        })
    return entries
