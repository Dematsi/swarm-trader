from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.options_research.corporate_actions import SPLIT_COLUMNS
from src.options_research.events_rules import EVENT_COLUMNS
from src.options_research.market_calendar import get_session, sessions_between
from src.options_research.stage1 import (
    STAGE1_COLUMNS,
    forward_outcomes,
    load_signals,
    run_stage1,
    signals_for_symbol,
    symbol_signals_path,
    tag_events,
    tag_splits,
)
from src.options_research.store import HoldoutAccessError
from src.options_research.stocks import STOCK_COLUMNS
from tests.options_research.setup_helpers import DAY, SESSION, at, make_grid

FRI = date(2025, 5, 30)
START = date(2025, 5, 22)
NO_SPLITS = pd.DataFrame(columns=SPLIT_COLUMNS)


def signal(direction, decision, symbol="TEST", day=DAY, setup="PDL_BREAK"):
    return {"symbol": symbol, "day": day, "setup": setup, "direction": direction, "decision_ts": decision}


def test_forward_outcomes_signed_returns_and_excursions():
    closes = 100 + 0.01 * np.arange(390)
    grid = make_grid(close=closes)
    signals = pd.DataFrame([signal("long", at("10:00")), signal("short", at("10:00")), signal("long", at("15:30")), signal("long", at("16:00"))])
    out = forward_outcomes(signals, grid, SESSION)
    long, short, late, closed = (out.iloc[i] for i in range(4))
    assert long["entry_price"] == pytest.approx(100.30)
    assert long["ret_30"] == pytest.approx(100.60 / 100.30 - 1)
    assert long["ret_60"] == pytest.approx(100.90 / 100.30 - 1)
    assert long["ret_hard"] == pytest.approx(103.75 / 100.30 - 1)
    assert long["mfe_60"] == pytest.approx(100.94 / 100.30 - 1)
    assert long["mae_60"] == pytest.approx(100.25 / 100.30 - 1)
    assert short["ret_60"] == pytest.approx(-(100.90 / 100.30 - 1))
    assert short["mfe_60"] == pytest.approx(1 - 100.25 / 100.30)
    assert short["mae_60"] == pytest.approx(1 - 100.94 / 100.30)
    assert late["ret_60"] == pytest.approx(103.89 / 103.60 - 1)
    assert closed[["entry_price", "ret_60"]].isna().all()


def test_tag_events_windows_earnings_and_day_events():
    events = pd.DataFrame(
        [
            {"date": DAY, "time_et": "10:00", "type": "ism_manufacturing", "tier": "2", "source": "rule", "ticker": None},
            {"date": DAY, "time_et": "08:30", "type": "cpi", "tier": "1", "source": "fred", "ticker": None},
            {"date": DAY, "time_et": None, "type": "opex", "tier": "market", "source": "rule", "ticker": None},
            {"date": DAY, "time_et": None, "type": "earnings_amc", "tier": "earnings", "source": "yfinance", "ticker": "OTHER"},
            {"date": FRI, "time_et": None, "type": "earnings_amc", "tier": "earnings", "source": "yfinance", "ticker": "TEST"},
        ],
        columns=EVENT_COLUMNS,
    )
    sessions = [get_session(FRI), SESSION]
    signals = pd.DataFrame([signal("long", at("09:50")), signal("long", at("11:15")), signal("long", at("11:15"), day=FRI)])
    out = tag_events(signals, events, sessions)
    assert out["event_in_window"].tolist() == [True, False, False]
    assert out["day_events"].tolist() == ["cpi,ism_manufacturing,opex", "cpi,ism_manufacturing,opex", "earnings_amc"]
    assert out["earnings_reaction"].tolist() == [True, True, False]
    assert out["event_day"].tolist() == [True, True, False]


def test_tag_splits_marks_the_split_session_and_its_neighbours():
    sessions = sessions_between(date(2025, 5, 29), date(2025, 6, 3))
    splits = pd.DataFrame([{"symbol": "TEST", "day": FRI, "ratio": 2.0, "factor": 0.5}], columns=SPLIT_COLUMNS)
    days = [s.day for s in sessions]
    signals = pd.DataFrame([signal("long", at("10:00"), day=d) for d in days] + [signal("long", at("10:00"), symbol="OTHER", day=FRI)])
    assert tag_splits(signals, splits, sessions)["near_split"].tolist() == [True, True, True, False, False]


def synthetic_minutes(symbol, sessions, breakout_day=None):
    rows = []
    for session in sessions:
        ts = pd.date_range(session.open_et, session.close_et, freq="1min", inclusive="left").tz_convert("UTC")
        close = np.full(len(ts), 100.0)
        if session.day == breakout_day:
            close[150:] = 101.0
        rows.append(pd.DataFrame({
            "symbol": symbol, "ts": ts, "open": close, "high": close + 0.05, "low": close - 0.05, "close": close, "volume": 1000, "transactions": 10,
            "bad_high": False, "bad_low": False, "high_clean": close + 0.05, "low_clean": close - 0.05, "source": "zip",
        }))
    return pd.concat(rows, ignore_index=True)[STOCK_COLUMNS]


def test_signals_for_symbol_wires_levels_features_setups_and_outcomes():
    sessions = sessions_between(START, DAY)
    minutes = synthetic_minutes("TEST", sessions, breakout_day=DAY)
    spy = synthetic_minutes("SPY", sessions)
    out = signals_for_symbol("TEST", minutes, spy, sessions, NO_SPLITS)
    assert set(out["day"]) == {DAY}
    pdl = out[(out["setup"] == "PDL_BREAK") & (out["direction"] == "long")].iloc[0]
    assert pdl["decision_ts"] == at("12:01")
    assert pdl["entry_price"] == pytest.approx(101.0)
    assert pdl["ret_60"] == pytest.approx(0.0)


def write_lake(root, sessions):
    for symbol, breakout in (("NVDA", DAY), ("SPY", None)):
        minutes = synthetic_minutes(symbol, sessions, breakout_day=breakout)
        for session in sessions:
            day_rows = minutes[minutes["ts"].dt.tz_convert("America/New_York").dt.date == session.day]
            path = root / "stock_1m" / symbol / str(session.day.year) / f"{session.day.isoformat()}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            day_rows.to_parquet(path, index=False)
    (root / "calendar").mkdir(parents=True)
    pd.DataFrame(columns=EVENT_COLUMNS).astype(object).to_parquet(root / "calendar" / "events.parquet", index=False)
    (root / "corporate_actions").mkdir(parents=True)
    pd.DataFrame(columns=SPLIT_COLUMNS).astype({"ratio": float, "factor": float}).to_parquet(root / "corporate_actions" / "splits.parquet", index=False)


def test_run_stage1_writes_resumable_symbol_files_and_tagged_signals(tmp_path):
    write_lake(tmp_path, sessions_between(START, DAY))
    first = run_stage1(["NVDA"], START, DAY, workers=1, root=tmp_path)
    assert first["computed"] == ["NVDA"] and first["signals"] > 0
    assert symbol_signals_path("NVDA", tmp_path, START, DAY).exists()
    signals = load_signals(tmp_path, START, DAY)
    assert list(signals.columns) == STAGE1_COLUMNS
    assert set(signals["day"]) == {DAY}
    assert not signals["near_split"].any() and not signals["event_in_window"].any()
    second = run_stage1(["NVDA"], START, DAY, workers=1, root=tmp_path)
    assert second["computed"] == [] and second["skipped"] == ["NVDA"]


def test_run_stage1_recomputes_for_a_different_period(tmp_path):
    write_lake(tmp_path, sessions_between(START, DAY))
    first = run_stage1(["NVDA"], START, DAY, workers=1, root=tmp_path)
    assert first["computed"] == ["NVDA"]
    other_start = date(2025, 5, 23)
    second = run_stage1(["NVDA"], other_start, DAY, workers=1, root=tmp_path)
    assert second["computed"] == ["NVDA"]
    assert symbol_signals_path("NVDA", tmp_path, START, DAY).exists()
    assert symbol_signals_path("NVDA", tmp_path, other_start, DAY).exists()


def test_run_stage1_refuses_the_holdout(tmp_path):
    write_lake(tmp_path, sessions_between(START, DAY))
    with pytest.raises(HoldoutAccessError):
        run_stage1(["NVDA"], START, date(2026, 1, 5), workers=1, root=tmp_path, overwrite=True)
