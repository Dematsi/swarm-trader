import numpy as np

from src.options_research.setups import SETUPS
from src.options_research.setups.mean_reversion import detect_meanrev
from src.options_research.setups.vwap import detect_vwap_pullback, detect_vwap_reclaim, spy_regime
from tests.options_research.setup_helpers import assert_point_in_time, at, idx, make_ctx, make_grid, set_bar


def summary(signals):
    return [(s["setup"], s["direction"], s["decision_ts"], round(s["inval_value"], 6), s["inval_side"]) for s in signals]


def test_vwap_reclaim_long_after_30_closes_below():
    closes = np.full(390, 100.5)
    closes[: idx("10:15")] = 99.5
    closes[idx("10:15")] = 100.2
    ctx = make_ctx(make_grid(close=closes))
    assert summary(assert_point_in_time(detect_vwap_reclaim, ctx)) == [("VWAP_RECLAIM", "long", at("10:16"), -0.1, "below")]


def test_vwap_reclaim_run_resets_on_a_close_at_or_above_vwap():
    closes = np.full(390, 100.5)
    closes[: idx("10:10")] = 99.5
    closes[idx("10:10")] = 100.05
    closes[idx("10:11"): idx("10:15")] = 99.5
    closes[idx("10:15")] = 100.2
    assert detect_vwap_reclaim(make_ctx(make_grid(close=closes))) == []


def test_vwap_reclaim_short_mirror():
    closes = np.full(390, 99.5)
    closes[: idx("10:15")] = 100.5
    closes[idx("10:15")] = 99.8
    ctx = make_ctx(make_grid(close=closes))
    assert summary(assert_point_in_time(detect_vwap_reclaim, ctx)) == [("VWAP_RECLAIM", "short", at("10:16"), 0.1, "above")]


def spy(close, slope):
    return make_grid(close=close, vwap=100.0 + slope * np.arange(390))


def test_spy_regime_needs_price_and_slope():
    up, down = spy_regime(make_ctx(spy_grid=spy(101.0, 0.001)))
    assert not up[: idx("10:00")].all() and up[idx("10:00"):].all() and not down.any()
    up, down = spy_regime(make_ctx(spy_grid=spy(101.0, 0.0)))
    assert not up.any() and not down.any()
    up, down = spy_regime(make_ctx())
    assert not up.any() and not down.any()


def test_vwap_pullback_long_with_cooldown_and_daily_cap():
    grid = make_grid(close=100.5)
    for t in ("10:30", "10:45", "11:10", "12:00"):
        set_bar(grid, t, 100.2, low=100.05)
    ctx = make_ctx(grid, spy_grid=spy(101.0, 0.001))
    assert summary(assert_point_in_time(detect_vwap_pullback, ctx)) == [
        ("VWAP_PULLBACK", "long", at("10:31"), -0.1, "below"),
        ("VWAP_PULLBACK", "long", at("11:11"), -0.1, "below"),
    ]
    assert detect_vwap_pullback(make_ctx(grid, spy_grid=spy(101.0, 0.0))) == []


def test_vwap_pullback_short_mirror():
    grid = make_grid(close=99.5)
    set_bar(grid, "10:30", 99.8, high=99.95)
    ctx = make_ctx(grid, spy_grid=spy(99.0, -0.001))
    assert summary(assert_point_in_time(detect_vwap_pullback, ctx)) == [("VWAP_PULLBACK", "short", at("10:31"), 0.1, "above")]


def test_meanrev_long_short_adx_filter_cooldown_and_cap():
    grid = make_grid(close=100.0, sigma=0.4, adx14=15.0)
    for t, close, rsi in (("11:00", 98.9, 20.0), ("11:10", 98.8, 22.0), ("11:40", 98.7, 21.0), ("12:30", 98.6, 20.0), ("13:00", 101.1, 80.0)):
        set_bar(grid, t, close)
        grid.loc[idx(t), "rsi14"] = rsi
    ctx = make_ctx(grid)
    assert summary(assert_point_in_time(detect_meanrev, ctx)) == [
        ("MEANREV", "long", at("11:01"), 98.75, "below"),
        ("MEANREV", "long", at("11:41"), 98.55, "below"),
        ("MEANREV", "short", at("13:01"), 101.25, "above"),
    ]
    trending = grid.copy()
    trending["adx14"] = 25.0
    assert detect_meanrev(make_ctx(trending)) == []


def test_registry_has_eight_setups_so_far():
    assert set(SETUPS) == {"ORB15", "ORB30", "GAP_GO", "GAP_FILL", "PDL_BREAK", "VWAP_RECLAIM", "VWAP_PULLBACK", "MEANREV"}
