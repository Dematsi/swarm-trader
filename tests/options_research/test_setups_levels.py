from datetime import date, time

import numpy as np
import pandas as pd
import pytest

from src.options_research.levels import DayLevels
from src.options_research.market_calendar import get_session
from src.options_research.setups import SETUPS, detect_all
from src.options_research.setups.base import SIGNAL_COLUMNS, first_true, grid_signal, previous_run, window_mask, with_cooldown
from src.options_research.setups.gaps_levels import detect_gap_fill, detect_gap_go, detect_pdl_break
from src.options_research.setups.orb import detect_orb
from tests.options_research.setup_helpers import DAY, assert_point_in_time, at, make_ctx, make_grid, set_bar


def summary(signals):
    return [(s["setup"], s["direction"], s["decision_ts"], round(s["inval_value"], 6), s["inval_side"]) for s in signals]


def test_window_mask_is_inclusive_and_capped_one_hour_before_a_half_day_close():
    half = get_session(date(2025, 11, 28))
    decisions = pd.Series(pd.to_datetime(["2025-11-28 10:00", "2025-11-28 12:00", "2025-11-28 12:01"]).tz_localize("America/New_York").tz_convert("UTC"))
    assert window_mask(decisions, half, time(10, 0), time(15, 0)).tolist() == [True, True, False]


def test_previous_run_counts_the_run_before_each_bar():
    assert previous_run(np.array([True, True, False, True])).tolist() == [0, 1, 2, 0]


def test_with_cooldown_skips_within_30_minutes_and_caps_at_two():
    decisions = pd.Series([at(t) for t in ("10:00", "10:10", "10:31", "11:05", "12:00")])
    assert with_cooldown(np.ones(5, dtype=bool), decisions) == [0, 2]


def orb_levels(median=10000.0):
    return DayLevels(day=DAY, or_volume_median={15: median, 30: median})


def test_orb_long_on_first_close_above_the_range():
    grid = make_grid()
    set_bar(grid, "10:05", 100.5)
    ctx = make_ctx(grid, levels=orb_levels())
    assert summary(assert_point_in_time(lambda c: detect_orb(c, 15), ctx)) == [("ORB15", "long", at("10:06"), 100.0, "below")]
    assert summary(assert_point_in_time(lambda c: detect_orb(c, 30), ctx)) == [("ORB30", "long", at("10:06"), 100.0, "below")]


def test_orb_short_and_filters():
    grid = make_grid()
    set_bar(grid, "10:20", 99.4)
    assert summary(detect_orb(make_ctx(grid, levels=orb_levels()), 15)) == [("ORB15", "short", at("10:21"), 100.0, "above")]
    assert detect_orb(make_ctx(grid, levels=orb_levels(13000.0)), 15) == []
    assert detect_orb(make_ctx(grid, levels=DayLevels(day=DAY, or_volume_median={15: None, 30: None})), 15) == []
    late = make_grid()
    set_bar(late, "11:40", 100.5)
    assert detect_orb(make_ctx(late, levels=orb_levels()), 15) == []


def test_gap_up_go_long_and_fill_short():
    grid = make_grid()
    set_bar(grid, "10:05", 100.5)
    set_bar(grid, "10:30", 99.5)
    ctx = make_ctx(grid, levels=DayLevels(day=DAY, prior_close=99.0, premarket_high=100.3, premarket_low=99.8))
    assert summary(assert_point_in_time(detect_gap_go, ctx)) == [("GAP_GO", "long", at("10:06"), 99.95, "below")]
    assert summary(assert_point_in_time(detect_gap_fill, ctx)) == [("GAP_FILL", "short", at("10:31"), 100.05, "above")]


def test_gap_down_go_short_and_fill_long():
    grid = make_grid()
    set_bar(grid, "10:05", 99.5)
    set_bar(grid, "10:40", 100.5)
    ctx = make_ctx(grid, levels=DayLevels(day=DAY, prior_close=101.0, premarket_high=100.4, premarket_low=99.7))
    assert summary(assert_point_in_time(detect_gap_go, ctx)) == [("GAP_GO", "short", at("10:06"), 100.05, "above")]
    assert summary(assert_point_in_time(detect_gap_fill, ctx)) == [("GAP_FILL", "long", at("10:41"), 99.95, "below")]


def test_small_gap_and_late_fill_produce_nothing():
    grid = make_grid()
    set_bar(grid, "10:05", 100.5)
    assert detect_gap_go(make_ctx(grid, levels=DayLevels(day=DAY, prior_close=99.9, premarket_high=100.3))) == []
    late = make_grid()
    set_bar(late, "11:10", 99.5)
    assert detect_gap_fill(make_ctx(late, levels=DayLevels(day=DAY, prior_close=99.0))) == []


def test_prior_day_level_breaks_need_the_atr_buffer():
    grid = make_grid()
    set_bar(grid, "11:00", 100.34)
    set_bar(grid, "12:00", 100.4)
    set_bar(grid, "13:00", 98.9)
    ctx = make_ctx(grid, levels=DayLevels(day=DAY, prior_high=100.3, prior_low=99.0))
    assert summary(assert_point_in_time(detect_pdl_break, ctx)) == [
        ("PDL_BREAK", "long", at("12:01"), 100.2, "below"),
        ("PDL_BREAK", "short", at("13:01"), 99.1, "above"),
    ]


def test_point_in_time_helper_catches_a_look_ahead_detector():
    def peek(ctx):
        window = window_mask(ctx.grid["decision_ts"], ctx.session, time(10, 0), time(15, 0))
        close = ctx.grid["close"].to_numpy()
        peeked = np.zeros(len(close), dtype=bool)
        peeked[:-1] = close[1:] > 100.2
        i = first_true(window & peeked)
        if i is None:
            return []
        return [grid_signal(ctx, "PEEK", "long", i, "level", "below", 99.0, "peek")]

    grid = make_grid()
    set_bar(grid, "10:05", 100.5)
    with pytest.raises(AssertionError):
        assert_point_in_time(peek, make_ctx(grid))


def test_registry_and_signal_shape():
    assert {"ORB15", "ORB30", "GAP_GO", "GAP_FILL", "PDL_BREAK"} <= set(SETUPS)
    assert detect_all(make_ctx()) == []
    grid = make_grid()
    set_bar(grid, "10:05", 100.5)
    signals = detect_all(make_ctx(grid, levels=orb_levels()))
    assert signals and all(list(s) == SIGNAL_COLUMNS for s in signals)
    assert all(s["symbol"] == "TEST" and s["day"] == DAY and s["bar_ts"] == s["decision_ts"] - pd.Timedelta(minutes=1) for s in signals)
