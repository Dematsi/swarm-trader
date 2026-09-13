from src.options_research.setups import SETUP_PARAMS, SETUPS, detect_all
from src.options_research.setups.squeeze import detect_squeeze
from tests.options_research.setup_helpers import assert_point_in_time, at, five_idx, make_ctx, make_five


def summary(signals):
    return [(s["setup"], s["direction"], s["decision_ts"], s["bar_ts"], s["inval_kind"], s["inval_side"]) for s in signals]


def squeezed(first: str, last: str):
    five = make_five()
    five.loc[five_idx(first): five_idx(last), "squeeze"] = True
    return five


def test_squeeze_long_after_six_squeeze_bars_decides_at_bar_end():
    five = squeezed("09:30", "09:55")
    five.loc[five_idx("10:00"), "close"] = 101.5
    ctx = make_ctx(five=five)
    assert summary(assert_point_in_time(detect_squeeze, ctx)) == [("SQUEEZE", "long", at("10:05"), at("10:00"), "kc_mid", "below")]


def test_squeeze_short_mirror():
    five = squeezed("11:00", "11:25")
    five.loc[five_idx("11:30"), "close"] = 98.5
    ctx = make_ctx(five=five)
    assert summary(assert_point_in_time(detect_squeeze, ctx)) == [("SQUEEZE", "short", at("11:35"), at("11:30"), "kc_mid", "above")]


def test_squeeze_needs_six_bars_and_the_window():
    five = squeezed("09:35", "09:55")
    five.loc[five_idx("10:00"), "close"] = 101.5
    assert detect_squeeze(make_ctx(five=five)) == []
    late = squeezed("14:30", "14:55")
    late.loc[five_idx("15:00"), "close"] = 101.5
    assert detect_squeeze(make_ctx(five=late)) == []
    assert detect_squeeze(make_ctx()) == []


def test_registry_is_complete():
    assert set(SETUPS) == {"ORB15", "ORB30", "VWAP_RECLAIM", "VWAP_PULLBACK", "MEANREV", "GAP_GO", "GAP_FILL", "PDL_BREAK", "SQUEEZE"}
    assert set(SETUP_PARAMS) == set(SETUPS)
    assert detect_all(make_ctx()) == []
