import numpy as np
import pandas as pd
import pytest

from src.options_research.quality import apply_clean, classify_print, find_print_candidates


def day_frame(closes, lows=None, highs=None, opens=None, start="2023-02-01T21:00:00Z"):
    n = len(closes)
    ts = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    closes = [float(c) for c in closes]
    return pd.DataFrame({
        "ts": ts,
        "open": opens or closes,
        "high": highs or [c + 0.05 for c in closes],
        "low": lows or [c - 0.05 for c in closes],
        "close": closes,
    })


def wobble(level, n=30):
    return [level + (0.05 if i % 2 else -0.05) for i in range(n)]


def test_snapback_low_wick_is_a_candidate():
    closes = wobble(183.0)
    lows = [c - 0.05 for c in closes]
    lows[15] = 153.12
    cands = find_print_candidates(day_frame(closes, lows=lows))
    assert list(cands.columns) == ["ts", "side", "extreme", "reference", "band"]
    assert len(cands) == 1
    row = cands.iloc[0]
    assert row["side"] == "low" and row["extreme"] == 153.12
    assert row["reference"] == pytest.approx(183.0, abs=0.1)
    assert row["band"] == pytest.approx(0.03 * row["reference"])


def test_clean_step_move_produces_no_candidates():
    closes = [100.0] * 15 + [106.0] * 15
    assert find_print_candidates(day_frame(closes)).empty


def test_spike_that_does_not_snap_back_is_not_a_candidate():
    closes = [100.0] * 15 + [120.0] * 15
    highs = [c + 0.05 for c in closes]
    highs[14] = 125.0
    assert find_print_candidates(day_frame(closes, highs=highs)).empty


def test_sessions_shorter_than_six_bars_have_no_reference():
    closes = [50.0] * 5
    lows = [49.95] * 5
    lows[2] = 30.0
    assert find_print_candidates(day_frame(closes, lows=lows)).empty


def trades(prices_exchanges):
    return [{"t": "2023-02-01T21:15:00Z", "price": p, "size": 100, "exchange": x, "conditions": ["@"]} for p, x in prices_exchanges]


def test_single_off_exchange_print_is_isolated_and_cleans_to_extreme_in_band_trade():
    result = classify_print(trades([(182.75, "V"), (182.90, "P"), (182.94, "V"), (153.12, "D")]), "low", 183.0, 5.49)
    assert result["decision"] == "isolated"
    assert result["n_trades"] == 4 and result["n_outliers"] == 1
    assert result["outlier_prices"] == [153.12] and result["outlier_exchanges"] == ["D"]
    assert result["clean_value"] == 182.75


def test_high_side_clean_value_is_max_in_band_trade():
    result = classify_print(trades([(299.26, "Q"), (299.67, "V"), (309.35, "D")]), "high", 299.45, 8.98)
    assert result["decision"] == "isolated" and result["clean_value"] == 299.67


def test_on_exchange_outlier_is_genuine():
    result = classify_print(trades([(177.5, "V"), (169.0, "P")]), "low", 177.88, 5.34)
    assert result["decision"] == "genuine" and result["clean_value"] is None


def test_more_than_three_outliers_is_genuine_even_off_exchange():
    result = classify_print(trades([(177.5, "V")] + [(169.0, "D")] * 4), "low", 177.88, 5.34)
    assert result["decision"] == "genuine"


def test_no_trades_and_no_outliers_decisions():
    assert classify_print([], "low", 100.0, 3.0)["decision"] == "no_trades"
    assert classify_print(trades([(100.1, "V")]), "low", 100.0, 3.0)["decision"] == "no_outlier_trades"


def test_isolated_without_in_band_trades_has_empty_clean_value():
    result = classify_print(trades([(195.0, "D"), (190.0, "D")]), "high", 171.82, 5.15)
    assert result["decision"] == "isolated" and result["clean_value"] is None


def test_apply_clean_resets_then_applies_isolated_decisions():
    day = day_frame(wobble(183.0))
    day.loc[15, "low"] = 153.12
    day["bad_high"] = True  # stale values must be reset
    checks = pd.DataFrame({"ts": [day.loc[15, "ts"], day.loc[3, "ts"], day.loc[5, "ts"]],
                           "side": ["low", "high", "low"],
                           "decision": ["isolated", "genuine", "isolated"],
                           "clean_value": [182.75, 999.0, None]})
    out = apply_clean(day, checks)
    assert out.loc[15, "bad_low"] and out.loc[15, "low_clean"] == 182.75
    assert not out["bad_high"].any() and out.loc[3, "high_clean"] == out.loc[3, "high"]
    assert out.loc[5, "bad_low"] and np.isnan(out.loc[5, "low_clean"])
    untouched = out.drop(index=[5, 15])
    assert (untouched["low_clean"] == untouched["low"]).all() and (untouched["high_clean"] == untouched["high"]).all()


def test_apply_clean_without_checks_is_pass_through():
    day = day_frame(wobble(50.0, n=8))
    out = apply_clean(day, None)
    assert not out["bad_high"].any() and not out["bad_low"].any()
    assert (out["high_clean"] == out["high"]).all() and (out["low_clean"] == out["low"]).all()


def test_apply_clean_never_leaves_the_raw_bar_range():
    rng = np.random.RandomState(0)
    n = 200
    mid = 100 + rng.randn(n).cumsum() * 0.1
    day = pd.DataFrame({"ts": pd.date_range("2024-01-02T14:30:00Z", periods=n, freq="1min", tz="UTC"),
                        "open": mid, "high": mid + rng.rand(n), "low": mid - rng.rand(n), "close": mid})
    picks = rng.choice(n, 40, replace=False)
    checks = pd.DataFrame({"ts": day["ts"].iloc[picks].reset_index(drop=True), "side": rng.choice(["high", "low"], 40),
                           "decision": "isolated", "clean_value": mid[picks] + rng.randn(40) * 5})
    checks.loc[checks.index[:5], "clean_value"] = np.nan
    out = apply_clean(day, checks)
    hc, lc = out["high_clean"], out["low_clean"]
    assert ((hc.isna()) | ((hc >= out["low"] - 1e-12) & (hc <= out["high"] + 1e-12))).all()
    assert ((lc.isna()) | ((lc >= out["low"] - 1e-12) & (lc <= out["high"] + 1e-12))).all()
    both = hc.notna() & lc.notna()
    assert (lc[both] <= hc[both] + 1e-12).all()


def test_apply_clean_inverted_pair_becomes_empty():
    day = day_frame([100.0] * 8)
    t = day.loc[4, "ts"]
    checks = pd.DataFrame({"ts": [t, t], "side": ["high", "low"], "decision": ["isolated", "isolated"],
                           "clean_value": [99.96, 100.04]})
    out = apply_clean(day, checks)
    assert np.isnan(out.loc[4, "high_clean"]) and np.isnan(out.loc[4, "low_clean"])
