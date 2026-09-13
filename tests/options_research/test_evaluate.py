from datetime import date, time

import numpy as np
import pandas as pd
import pytest

from src.options_research.costs import COST_KEYS, CostModel
from src.options_research.evaluate import (
    EVALUATION_COLUMNS,
    add_break_even,
    break_even_frac,
    calibration_spots,
    day_block_bootstrap,
    evaluate_stage1,
    event_table,
    horizon_table,
    near_expiry_dte,
    per_ticker_break_even,
)
from src.options_research.market_calendar import sessions_between
from src.options_research.stocks import STOCK_COLUMNS


def test_bootstrap_mean_and_day_blocks():
    days = [date(2024, 1, 2)] * 2 + [date(2024, 1, 3)] + [date(2024, 1, 4)] * 3
    values = [0.01, 0.03, 0.02, -0.01, 0.01, 0.02]
    mean, se, t = day_block_bootstrap(values, days)
    assert mean == pytest.approx(0.08 / 6)
    assert se > 0 and t == pytest.approx(mean / se)
    assert day_block_bootstrap(values, days) == (mean, se, t)


def test_bootstrap_does_not_reward_duplicate_signals_within_a_day():
    days = list(sessions_between(date(2024, 1, 2), date(2024, 3, 29)))
    rng = np.random.default_rng(1)
    base = rng.normal(0.001, 0.01, len(days))
    once = day_block_bootstrap(base, [s.day for s in days])
    tenfold = day_block_bootstrap(np.repeat(base, 10), np.repeat([s.day for s in days], 10))
    assert tenfold[0] == pytest.approx(once[0]) and tenfold[1] == pytest.approx(once[1])


def test_near_expiry_dte_counts_to_friday_or_the_holiday_thursday():
    assert near_expiry_dte(date(2025, 6, 2)) == 4
    assert near_expiry_dte(date(2025, 5, 30)) == 0
    assert near_expiry_dte(date(2025, 4, 16)) == 1
    assert near_expiry_dte(date(2025, 4, 17)) == 0


def cost_model():
    rows = [
        {"underlying": "TEST", "dte_bucket": "3-7", "moneyness": "ATM", "premium": None, "tod_bucket": None, "n": 100, "half_spread": 0.10, "mid": 2.0},
        {"underlying": "TEST", "dte_bucket": "3-7", "moneyness": "ATM", "premium": "1-3", "tod_bucket": "mid", "n": 50, "half_spread": 0.08, "mid": 2.0},
    ]
    return CostModel(pd.DataFrame(rows, columns=COST_KEYS + ["n", "half_spread", "mid"]))


def test_break_even_scales_the_half_spread_to_the_signal_price():
    be = break_even_frac(cost_model(), "TEST", date(2025, 6, 2), time(11, 0), 200.0, 100.0)
    assert be == pytest.approx((2 * 0.16 + 2 * 0.0005) / (0.5 * 200.0))
    signals = pd.DataFrame({"symbol": ["TEST"], "day": [date(2025, 6, 2)], "decision_ts": [pd.Timestamp("2025-06-02 11:00", tz="America/New_York").tz_convert("UTC")], "price": [200.0]})
    assert add_break_even(signals, cost_model(), {"TEST": 100.0})["be_frac"].iloc[0] == pytest.approx(be)


def spread_days(count):
    days = [s.day for s in sessions_between(date(2021, 7, 1), date(2025, 12, 31))]
    return [days[i] for i in np.linspace(0, len(days) - 1, count).astype(int)]


def synthetic_signals():
    rows = []
    for i, day in enumerate(spread_days(400)):
        rows.append({"setup": "A", "direction": "long", "symbol": "SPY" if i % 2 else "QQQ", "day": day, "ret_60": 0.002 + 0.001 * np.sin(i), "be_frac": 0.001})
    for i, day in enumerate(spread_days(100)):
        rows.append({"setup": "B", "direction": "short", "symbol": "SPY", "day": day, "ret_60": 0.002 + 0.001 * np.sin(i), "be_frac": 0.001})
    for i, day in enumerate(spread_days(400)):
        rows.append({"setup": "C", "direction": "long", "symbol": "SPY", "day": day, "ret_60": 0.0005 + 0.0001 * np.sin(i), "be_frac": 0.001})
    frame = pd.DataFrame(rows)
    for column in ("ret_30", "ret_hard"):
        frame[column] = frame["ret_60"]
    frame["mfe_60"], frame["mae_60"], frame["event_day"] = 0.004, -0.002, [i % 5 == 0 for i in range(len(frame))]
    return frame


def test_evaluate_stage1_applies_every_criterion():
    result = evaluate_stage1(synthetic_signals()).set_index("setup")
    assert list(evaluate_stage1(synthetic_signals()).columns) == EVALUATION_COLUMNS
    a, b, c = result.loc["A"], result.loc["B"], result.loc["C"]
    assert a["n"] == 400 and a["positive_years"] == 5 and a["t"] > 3 and a["cost_ratio"] == pytest.approx(a["mean_ret_60"] / 0.001)
    assert bool(a["passed"])
    assert not bool(b["pass_n"]) and not bool(b["passed"])
    assert bool(c["pass_t"]) and not bool(c["pass_cost"]) and not bool(c["passed"])


def test_descriptive_tables():
    signals = synthetic_signals()
    horizons = horizon_table(signals)
    assert {"n", "mean_ret_30", "mean_ret_60", "mean_ret_hard", "median_mfe_60", "median_mae_60"} <= set(horizons.columns)
    events = event_table(signals)
    assert {"n_all", "mean_all", "t_all", "n_ex_event", "mean_ex_event", "t_ex_event"} <= set(events.columns)
    assert per_ticker_break_even(signals).loc["SPY"] == pytest.approx(10.0)


def test_calibration_spots_read_regular_hours_closes_in_the_calibration_window(tmp_path):
    day = date(2026, 8, 24)
    rows = []
    for hhmm, close in (("08:00", 500.0), ("10:00", 100.0), ("11:00", 102.0), ("12:00", 104.0)):
        ts = pd.Timestamp(f"{day} {hhmm}", tz="America/New_York").tz_convert("UTC")
        rows.append({"symbol": "NVDA", "ts": ts, "open": close, "high": close, "low": close, "close": close, "volume": 100, "transactions": 1, "bad_high": False, "bad_low": False, "high_clean": close, "low_clean": close, "source": "alpaca"})
    path = tmp_path / "stock_1m" / "NVDA" / "2026" / f"{day.isoformat()}.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(rows, columns=STOCK_COLUMNS).to_parquet(path, index=False)
    assert calibration_spots(["NVDA"], root=tmp_path) == {"NVDA": pytest.approx(102.0)}
