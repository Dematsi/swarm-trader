import pandas as pd

from src.options_research.quality import flag_bad_prints


def bars(closes, highs=None, lows=None):
    closes = [float(c) for c in closes]
    highs = highs or [c + 0.05 for c in closes]
    lows = lows or [c - 0.05 for c in closes]
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes})


def test_normal_bars_are_not_flagged():
    out = flag_bad_prints(bars([100 + 0.01 * i for i in range(30)]))
    assert not out["bad_high"].any() and not out["bad_low"].any()
    assert (out["high_clean"] == out["high"]).all()


def test_spike_high_is_flagged_and_clipped_to_body():
    closes = [121.0 + 0.02 * i for i in range(30)]
    highs = [c + 0.05 for c in closes]
    highs[20] = 195.95
    out = flag_bad_prints(bars(closes, highs=highs))
    assert out.loc[20, "bad_high"]
    assert out["bad_high"].sum() == 1
    assert out.loc[20, "high_clean"] == max(out.loc[20, "open"], out.loc[20, "close"])


def test_spike_low_is_flagged_and_clipped():
    closes = [50.0] * 30
    lows = [49.95] * 30
    lows[10] = 30.0
    out = flag_bad_prints(bars(closes, lows=lows))
    assert out.loc[10, "bad_low"] and out.loc[10, "low_clean"] == 50.0


def test_single_print_outlier_bar_is_clipped_to_reference_band():
    closes = [121.0] * 30
    opens = closes.copy()
    highs = [121.05] * 30
    lows = [120.95] * 30
    closes[20] = opens[20] = highs[20] = lows[20] = 195.95
    out = flag_bad_prints(pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes}))
    assert out.loc[20, "bad_high"] and out.loc[20, "bad_close"] and out.loc[20, "bad_low"]
    assert out.loc[20, "high_clean"] < 125.0
    assert out.loc[20, "low_clean"] <= out.loc[20, "high_clean"]
    assert not out.loc[21, "bad_high"]


def test_flags_use_only_past_bars():
    closes = [100.0] * 30
    base = flag_bad_prints(bars(closes))
    changed = closes.copy()
    changed[25] = 150.0
    later = flag_bad_prints(bars(changed))
    pd.testing.assert_frame_equal(base.iloc[:25], later.iloc[:25])
