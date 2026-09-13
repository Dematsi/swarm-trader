"""Stage-1 signal generation and forward stock outcomes (spec §6, §8).

Per symbol and session, the pipeline goes:
- build today's raw grid and features plus the split-adjusted after-window levels
- run every setup
- attach forward returns measured from the open of the bar starting at decision time

Per-symbol results are cached so an interrupted run resumes. The combined file adds event and split
tags. Only `store.load_stock_minutes` reads stock minutes, so the holdout guard applies.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, time
from pathlib import Path

import numpy as np
import pandas as pd

from src.options_research.config import STAGE1_DEV, UNIVERSE, lake_root
from src.options_research.corporate_actions import load_splits
from src.options_research.events_sources import load_events
from src.options_research.features import add_vwap, enrich_session, session_grid, split_by_day
from src.options_research.levels import clean_grid, day_levels, history_minutes, session_summaries
from src.options_research.market_calendar import ET, Session, entry_exit_cutoffs, sessions_between
from src.options_research.setups import detect_all
from src.options_research.setups.base import LONG, SIGNAL_COLUMNS, DayContext
from src.options_research.store import load_stock_minutes

HORIZONS = (30, 60)
EXCURSION_MINUTES = 60
OUTCOME_COLUMNS = ["entry_price", "ret_30", "ret_60", "ret_hard", "mfe_60", "mae_60"]
TAG_COLUMNS = ["day_events", "earnings_reaction", "event_day", "event_in_window", "near_split"]
STAGE1_COLUMNS = SIGNAL_COLUMNS + OUTCOME_COLUMNS + TAG_COLUMNS
INTRADAY_TIERS = {"1", "2"}
EVENT_BEFORE = pd.Timedelta(minutes=15)
EVENT_AFTER = pd.Timedelta(minutes=70)


def stage1_dir(root: Path | None = None) -> Path:
    return (root or lake_root()) / "signals" / "stage1"


def symbol_signals_path(symbol: str, root: Path | None = None) -> Path:
    return stage1_dir(root) / f"{symbol}.parquet"


def signals_path(root: Path | None = None) -> Path:
    return stage1_dir(root) / "signals.parquet"


def _write_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def forward_outcomes(signals: pd.DataFrame, grid: pd.DataFrame, session: Session) -> pd.DataFrame:
    """Signed forward returns from the open of the bar starting at T (spec §8.1); MFE/MAE over [T, T+60)."""
    out = signals.copy()
    position = pd.Series(np.arange(len(grid)), index=grid["ts"])
    opens, highs, lows = (grid[c].to_numpy(dtype=float) for c in ("open", "high", "low"))
    last_close = float(grid["close"].iloc[-1])
    hard_exit = pd.Timestamp(entry_exit_cutoffs(session.day, is_0dte=False)[1]).tz_convert("UTC")

    def exit_price(ts: pd.Timestamp) -> float:
        j = position.get(ts)
        return opens[j] if j is not None else last_close

    rows = []
    for decision, direction in zip(out["decision_ts"], out["direction"]):
        start = position.get(decision)
        if start is None:
            rows.append([np.nan] * len(OUTCOME_COLUMNS))
            continue
        entry = opens[start]
        sign = 1.0 if direction == LONG else -1.0
        values = [entry] + [sign * (exit_price(decision + pd.Timedelta(minutes=h)) / entry - 1.0) for h in HORIZONS]
        values.append(sign * (exit_price(hard_exit) / entry - 1.0) if hard_exit > decision else np.nan)
        stop = min(start + EXCURSION_MINUTES, len(grid))
        high, low = highs[start:stop].max(), lows[start:stop].min()
        values += [high / entry - 1.0, low / entry - 1.0] if sign > 0 else [1.0 - low / entry, 1.0 - high / entry]
        rows.append(values)
    out[OUTCOME_COLUMNS] = pd.DataFrame(rows, columns=OUTCOME_COLUMNS, index=out.index)
    return out


def tag_events(signals: pd.DataFrame, events: pd.DataFrame, sessions: list[Session]) -> pd.DataFrame:
    """Event tags per signal (spec §8.6)."""
    out = signals.copy()
    previous = {sessions[i].day: sessions[i - 1].day for i in range(1, len(sessions))}
    empty = events.iloc[0:0]
    by_day = {day: frame for day, frame in events.groupby("date")}
    day_events, reaction, event_day, in_window = [], [], [], []
    for symbol, day, decision in zip(out["symbol"], out["day"], out["decision_ts"]):
        today = by_day.get(day, empty)
        relevant = today[today["ticker"].isna() | (today["ticker"] == symbol)]
        day_events.append(",".join(sorted(set(relevant["type"]))))
        prior = by_day.get(previous.get(day), empty)
        reported = bool(((prior["type"] == "earnings_amc") & (prior["ticker"] == symbol)).any() or ((today["type"] == "earnings_bmo") & (today["ticker"] == symbol)).any())
        reaction.append(reported)
        tiered = today[today["tier"].isin(INTRADAY_TIERS)]
        event_day.append(bool(len(tiered)) or reported)
        released = [pd.Timestamp(datetime.combine(day, time.fromisoformat(t), tzinfo=ET)) for t in tiered["time_et"].dropna()]
        in_window.append(any(decision - EVENT_BEFORE <= r <= decision + EVENT_AFTER for r in released))
    out["day_events"] = day_events
    out["earnings_reaction"] = reaction
    out["event_day"] = event_day
    out["event_in_window"] = in_window
    return out


def tag_splits(signals: pd.DataFrame, splits: pd.DataFrame, sessions: list[Session]) -> pd.DataFrame:
    """`near_split`: the signal day is a split session for that symbol, or the session before or after it (spec §8.5)."""
    order = {s.day: i for i, s in enumerate(sessions)}
    near = set()
    for symbol, split_day in zip(splits["symbol"], splits["day"]):
        i = order.get(split_day)
        if i is None:
            continue
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(sessions):
                near.add((symbol, sessions[j].day))
    out = signals.copy()
    out["near_split"] = [(symbol, day) in near for symbol, day in zip(out["symbol"], out["day"])]
    return out


def signals_for_symbol(symbol: str, minutes: pd.DataFrame, spy_minutes: pd.DataFrame, sessions: list[Session], splits: pd.DataFrame) -> pd.DataFrame:
    """Signals with outcomes for one symbol. `minutes` must come from `load_stock_minutes(..., clean=True)`."""
    by_day = split_by_day(minutes)
    spy_by_day = by_day if symbol == "SPY" else split_by_day(spy_minutes)
    summaries = session_summaries(by_day, sessions)
    clean_grids = {s.day: clean_grid(by_day.get(s.day), s) for s in sessions}
    frames = []
    for index, session in enumerate(sessions):
        today = by_day.get(session.day)
        history = history_minutes(clean_grids, splits, symbol, sessions, index)
        if today is None or history is None:
            continue
        grid = session_grid(today, session)
        if grid.empty:
            continue
        grid, five = enrich_session(grid, history)
        if symbol == "SPY":
            spy_grid = grid
        else:
            spy_raw = session_grid(spy_by_day[session.day], session) if session.day in spy_by_day else pd.DataFrame()
            spy_grid = None if spy_raw.empty else add_vwap(spy_raw)
        ctx = DayContext(symbol, session, grid, five, day_levels(summaries, splits, symbol, sessions, index), spy_grid)
        found = detect_all(ctx)
        if found:
            frames.append(forward_outcomes(pd.DataFrame(found, columns=SIGNAL_COLUMNS), grid, session))
    if not frames:
        return pd.DataFrame(columns=SIGNAL_COLUMNS + OUTCOME_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def _symbol_job(job: tuple) -> str:
    symbol, start, end, root = job
    minutes = load_stock_minutes([symbol], start, end, root=root, clean=True)
    spy = minutes if symbol == "SPY" else load_stock_minutes(["SPY"], start, end, root=root)
    frame = signals_for_symbol(symbol, minutes, spy, sessions_between(start, end), load_splits(root))
    _write_atomic(frame, symbol_signals_path(symbol, root))
    return symbol


def combine_stage1(symbols, start: date, end: date, root: Path | None = None) -> pd.DataFrame:
    frames = [pd.read_parquet(symbol_signals_path(s, root)) for s in symbols if symbol_signals_path(s, root).exists()]
    frames = [f for f in frames if not f.empty]
    signals = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SIGNAL_COLUMNS + OUTCOME_COLUMNS)
    signals["day"] = pd.to_datetime(signals["day"]).dt.date
    sessions = sessions_between(start, end)
    signals = tag_splits(tag_events(signals, load_events(root), sessions), load_splits(root), sessions)
    signals = signals.sort_values(["symbol", "decision_ts", "setup", "direction"]).reset_index(drop=True)[STAGE1_COLUMNS]
    _write_atomic(signals, signals_path(root))
    return signals


def run_stage1(symbols=UNIVERSE, start: date = STAGE1_DEV[0], end: date = STAGE1_DEV[1], workers: int = 4, overwrite: bool = False, root: Path | None = None) -> dict:
    symbols = list(symbols)
    todo = [s for s in symbols if overwrite or not symbol_signals_path(s, root).exists()]
    jobs = [(s, start, end, root) for s in todo]
    if workers <= 1 or len(jobs) <= 1:
        computed = [_symbol_job(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            computed = list(pool.map(_symbol_job, jobs))
    combined = combine_stage1(symbols, start, end, root)
    return {"computed": computed, "skipped": [s for s in symbols if s not in todo], "signals": int(len(combined))}


def load_signals(root: Path | None = None) -> pd.DataFrame:
    frame = pd.read_parquet(signals_path(root))
    frame["day"] = pd.to_datetime(frame["day"]).dt.date
    return frame
