from datetime import time

import pandas as pd
import pytest

from src.options_research.costs import (
    COST_KEYS,
    CostModel,
    dte_bucket,
    load_cost_model,
    moneyness_bucket,
    otm_pct,
    premium_bucket,
    save_cost_table,
    scale_half_spread,
    session_realized_vol,
    tod_bucket,
)


@pytest.mark.parametrize("dte,expected", [(0, "0"), (1, "1-2"), (2, "1-2"), (3, "3-7"), (7, "3-7"), (8, "8+")])
def test_dte_bucket(dte, expected):
    assert dte_bucket(dte) == expected


@pytest.mark.parametrize("pct,expected", [(-0.51, "ITM"), (-0.5, "ATM"), (0.5, "ATM"), (0.51, "OTM1"), (2.0, "OTM1"), (2.01, "OTM2")])
def test_moneyness_bucket(pct, expected):
    assert moneyness_bucket(pct) == expected


def test_otm_pct_sign_convention():
    assert otm_pct(606.0, 600.0, "call") == pytest.approx(1.0)
    assert otm_pct(594.0, 600.0, "put") == pytest.approx(1.0)
    assert otm_pct(594.0, 600.0, "CALL") == pytest.approx(-1.0)


@pytest.mark.parametrize("mid,expected", [(0.99, "<1"), (1.0, "1-3"), (2.99, "1-3"), (3.0, "3-10"), (10.0, "10+")])
def test_premium_bucket(mid, expected):
    assert premium_bucket(mid) == expected


@pytest.mark.parametrize("t,expected", [(time(9, 30), "open"), (time(9, 59), "open"), (time(10, 0), "mid"), (time(14, 59), "mid"), (time(15, 0), "close")])
def test_tod_bucket(t, expected):
    assert tod_bucket(t) == expected


def table(rows):
    return pd.DataFrame(rows, columns=COST_KEYS + ["n", "half_spread", "mid"])


SAMPLE = table([
    ("SPY", "1-2", "ATM", "1-3", "mid", 120, 0.010, 2.6),
    ("SPY", "1-2", "ATM", "1-3", "open", 10, 0.050, 2.6),
    ("SPY", "1-2", "ATM", "1-3", None, 200, 0.012, 2.6),
    ("SPY", "1-2", "ATM", None, None, 400, 0.015, 2.0),
    ("SPY", "1-2", None, None, None, 900, 0.020, 3.0),
    ("SPY", None, None, None, None, 5000, 0.030, 4.0),
])


def test_exact_cell_used_when_populated():
    model = CostModel(SAMPLE)
    assert model.base_half_spread("SPY", 2, 0.1, 2.5, time(11, 0)) == (0.010, 5)


def test_sparse_cell_backs_off_to_coarser_level():
    model = CostModel(SAMPLE)
    assert model.base_half_spread("SPY", 1, 0.2, 2.0, time(9, 45)) == (0.012, 4)
    assert model.base_half_spread("SPY", 1, 1.5, 2.0, time(11, 0)) == (0.020, 2)
    assert model.base_half_spread("SPY", 5, 0.0, 2.0, time(11, 0)) == (0.030, 1)


def test_unknown_underlying_raises():
    with pytest.raises(KeyError):
        CostModel(SAMPLE).base_half_spread("ZZZ", 1, 0.0, 2.0, time(11, 0))


def test_floor_applies():
    model = CostModel(table([("SPY", None, None, None, None, 100, 0.001, 0.2)]))
    assert model.half_spread("SPY", 0, 0.0, 0.2, time(11, 0)) == 0.005


@pytest.mark.parametrize("rv_prev,rv_cal,event,expected", [
    (None, None, False, 0.02), (0.5, 1.0, False, 0.02), (2.0, 1.0, False, 0.04), (9.0, 1.0, False, 0.06), (2.0, 1.0, True, 0.08),
])
def test_scale_half_spread(rv_prev, rv_cal, event, expected):
    assert scale_half_spread(0.02, rv_prev, rv_cal, event) == pytest.approx(expected)


def test_save_and_load_cost_model(tmp_path):
    path = save_cost_table(SAMPLE, root=tmp_path)
    assert path == tmp_path / "costs" / "half_spread_table.parquet"
    model = load_cost_model(root=tmp_path)
    assert model.fees_per_side == 0.05
    assert model.base_half_spread("SPY", 2, 0.1, 2.5, time(11, 0)) == (0.010, 5)


def test_session_realized_vol_uses_rth_log_returns():
    ts = pd.to_datetime(["2025-06-11T13:29:00Z", "2025-06-11T13:30:00Z", "2025-06-11T13:31:00Z", "2025-06-11T13:32:00Z"], utc=True)
    minutes = pd.DataFrame({"symbol": "SPY", "ts": ts, "close": [50.0, 100.0, 101.0, 100.0]})
    rv = session_realized_vol(minutes)
    import numpy as np
    expected = pd.Series([np.log(101 / 100), np.log(100 / 101)]).std() * np.sqrt(390)
    assert rv.name == "rv"
    assert rv.loc[pd.Timestamp("2025-06-11").date()] == pytest.approx(expected)
