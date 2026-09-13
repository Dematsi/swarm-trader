"""Rebuild bad-print flags and clean columns across the stock lake (spec §5.1).

Data-maintenance exception to the holdout guard (spec §9.1): reads and rewrites lake day files for all dates
(including the holdout period) and computes no signals or strategy metrics.
Phases: scan (offline, parallel) -> confirm (Alpaca SIP trades, resumable) -> rewrite (offline, parallel).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd

from src.options_research.config import UNIVERSE, lake_root
from src.options_research.quality import apply_clean, classify_print, find_print_candidates
from src.options_research.stocks import STOCK_COLUMNS

CANDIDATES_COLUMNS = ["symbol", "session_date", "ts", "side", "extreme", "reference", "band"]
CHECK_COLUMNS = CANDIDATES_COLUMNS + ["decision", "n_trades", "n_outliers", "outlier_prices", "outlier_exchanges", "outlier_conditions", "clean_value"]
PHASES = ("all", "scan", "confirm", "rewrite")


def candidates_path(root: Path) -> Path:
    return root / "quality" / "print_candidates.parquet"


def checks_path(root: Path) -> Path:
    return root / "quality" / "print_checks.parquet"


def lake_day_files(root: Path, symbols: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for symbol in symbols:
        files.extend(sorted((root / "stock_1m" / symbol).glob("*/*.parquet")))
    return files


def _scan_file(path: Path) -> pd.DataFrame:
    day = pd.read_parquet(path, columns=["ts", "open", "high", "low", "close"])
    candidates = find_print_candidates(day)
    if candidates.empty:
        return pd.DataFrame(columns=CANDIDATES_COLUMNS)
    candidates.insert(0, "session_date", date.fromisoformat(path.stem))
    candidates.insert(0, "symbol", path.parent.parent.name)
    return candidates[CANDIDATES_COLUMNS]


def _map(func, items: list, workers: int) -> list:
    if workers <= 1:
        return [func(item) for item in items]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(func, items, chunksize=32))


def scan_candidates(root: Path | None = None, symbols: Iterable[str] = UNIVERSE, workers: int = 4) -> pd.DataFrame:
    root = root or lake_root()
    parts = [p for p in _map(_scan_file, lake_day_files(root, symbols), workers) if not p.empty]
    candidates = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=CANDIDATES_COLUMNS)
    path = candidates_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_parquet(path, index=False)
    return candidates


def _key(symbol: str, ts, side: str) -> tuple[str, pd.Timestamp, str]:
    return symbol, pd.Timestamp(ts).tz_convert("UTC"), side


def _write_checks(existing: pd.DataFrame, rows: list[dict], path: Path) -> pd.DataFrame:
    if not rows:
        combined = existing
    else:
        new = pd.DataFrame(rows, columns=CHECK_COLUMNS)
        combined = new if existing.empty else pd.concat([existing, new], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)
    return combined


def confirm_candidates(
    candidates: pd.DataFrame,
    fetch_trades: Callable[[str, pd.Timestamp], list[dict]],
    root: Path | None = None,
    flush_every: int = 100,
) -> pd.DataFrame:
    root = root or lake_root()
    path = checks_path(root)
    existing = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=CHECK_COLUMNS)
    done = {_key(s, t, side) for s, t, side in zip(existing["symbol"], existing["ts"], existing["side"])}
    rows: list[dict] = []
    trade_cache: dict[tuple[str, pd.Timestamp], list[dict]] = {}
    for candidate in candidates.itertuples(index=False):
        key = _key(candidate.symbol, candidate.ts, candidate.side)
        if key in done:
            continue
        minute = (key[0], key[1])
        if minute not in trade_cache:
            trade_cache[minute] = fetch_trades(key[0], key[1])
        result = classify_print(trade_cache[minute], candidate.side, float(candidate.reference), float(candidate.band))
        rows.append({
            "symbol": candidate.symbol, "session_date": candidate.session_date, "ts": key[1], "side": candidate.side,
            "extreme": float(candidate.extreme), "reference": float(candidate.reference), "band": float(candidate.band),
            **result,
        })
        done.add(key)
        if len(rows) >= flush_every:
            existing = _write_checks(existing, rows, path)
            rows = []
    return _write_checks(existing, rows, path)


def _rewrite_file(job: tuple[Path, pd.DataFrame | None]) -> int:
    path, checks = job
    day = pd.read_parquet(path)
    cleaned = apply_clean(day.drop(columns=["bad_close"], errors="ignore"), checks)
    cleaned[STOCK_COLUMNS].to_parquet(path, index=False)
    return int(cleaned["bad_high"].sum() + cleaned["bad_low"].sum())


def rewrite_clean_columns(
    checks: pd.DataFrame,
    root: Path | None = None,
    symbols: Iterable[str] = UNIVERSE,
    workers: int = 4,
) -> dict:
    root = root or lake_root()
    by_file: dict[tuple[str, str], pd.DataFrame] = {}
    if not checks.empty:
        for (symbol, session_date), group in checks.groupby(["symbol", "session_date"]):
            by_file[(symbol, str(pd.Timestamp(session_date).date()))] = group[["ts", "side", "decision", "clean_value"]].reset_index(drop=True)
    files = lake_day_files(root, symbols)
    jobs = [(f, by_file.get((f.parent.parent.name, f.stem))) for f in files]
    flags = _map(_rewrite_file, jobs, workers)
    return {"files": len(files), "flags": int(sum(flags))}


def rebuild_clean(
    client,
    phase: str = "all",
    root: Path | None = None,
    symbols: Iterable[str] = UNIVERSE,
    workers: int = 4,
) -> dict:
    from src.options_research.stocks_alpaca import fetch_minute_trades

    if phase not in PHASES:
        raise ValueError(f"phase must be one of {PHASES}")
    root = root or lake_root()
    symbols = tuple(symbols)
    summary: dict = {"phase": phase}
    if phase in ("all", "scan"):
        candidates = scan_candidates(root, symbols, workers)
    else:
        candidates = pd.read_parquet(candidates_path(root))
    summary["candidates"] = int(len(candidates))
    if phase == "scan":
        return summary
    if phase in ("all", "confirm"):
        checks = confirm_candidates(candidates, lambda s, ts: fetch_minute_trades(client, s, ts), root=root)
    else:
        checks = pd.read_parquet(checks_path(root))
    current = {_key(s, t, side) for s, t, side in zip(candidates["symbol"], candidates["ts"], candidates["side"])}
    checks = checks[[_key(s, t, side) in current for s, t, side in zip(checks["symbol"], checks["ts"], checks["side"])]]
    summary.update({k: int(v) for k, v in checks["decision"].value_counts().items()})
    summary["checked"] = int(len(checks))
    if phase == "confirm":
        return summary
    summary.update(rewrite_clean_columns(checks, root, symbols, workers))
    return summary
