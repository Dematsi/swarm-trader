"""Bad-print cleaning for 1-minute stock bars (spec §5.1): two-sided candidates + trade-level confirmation.

The candidate step uses bars AFTER each bar, so clean columns are hindsight values: they may only feed levels
read once the relevant window is over (prior-day high/low/close, ATR history, pre-market high/low at/after 09:30).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW = 15
MIN_WINDOW_BARS = 6
MAD_MULT = 8.0
MIN_BAND_PCT = 0.03
SNAPBACK_BARS = 5
MAX_ISOLATED_TRADES = 3
OFF_EXCHANGE_CODE = "D"
CANDIDATE_COLUMNS = ["ts", "side", "extreme", "reference", "band"]


def find_print_candidates(day: pd.DataFrame) -> pd.DataFrame:
    if day.empty:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS)
    bars = day.sort_values("ts").reset_index(drop=True)
    close = bars["close"].astype(float)
    reference = close.rolling(WINDOW, center=True, min_periods=MIN_WINDOW_BARS).median()
    mad = (close - reference).abs().rolling(WINDOW, center=True, min_periods=MIN_WINDOW_BARS).median()
    band = np.maximum(MAD_MULT * mad, MIN_BAND_PCT * reference)
    next_closes = pd.concat([close.shift(-k) for k in range(1, SNAPBACK_BARS + 1)], axis=1)
    snapped_back = (next_closes.median(axis=1, skipna=True) - reference).abs() <= band
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    rows = []
    for side, extreme, outside in (("high", high, high - reference > band), ("low", low, reference - low > band)):
        for i in np.flatnonzero((outside & snapped_back).to_numpy()):
            rows.append({
                "ts": bars.loc[i, "ts"],
                "side": side,
                "extreme": float(extreme.iloc[i]),
                "reference": float(reference.iloc[i]),
                "band": float(band.iloc[i]),
            })
    if not rows:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS)
    return pd.DataFrame(rows, columns=CANDIDATE_COLUMNS).sort_values(["ts", "side"]).reset_index(drop=True)


def classify_print(trades: list[dict], side: str, reference: float, band: float) -> dict:
    upper, lower = reference + band, reference - band
    if side == "high":
        outliers = [t for t in trades if t["price"] > upper]
    else:
        outliers = [t for t in trades if t["price"] < lower]
    in_band = [t["price"] for t in trades if lower <= t["price"] <= upper]
    isolated = 0 < len(outliers) <= MAX_ISOLATED_TRADES and all(t["exchange"] == OFF_EXCHANGE_CODE for t in outliers)
    if not trades:
        decision = "no_trades"
    elif not outliers:
        decision = "no_outlier_trades"
    else:
        decision = "isolated" if isolated else "genuine"
    clean_value = None
    if decision == "isolated" and in_band:
        clean_value = max(in_band) if side == "high" else min(in_band)
    return {
        "decision": decision,
        "n_trades": len(trades),
        "n_outliers": len(outliers),
        "outlier_prices": [t["price"] for t in outliers],
        "outlier_exchanges": [t["exchange"] for t in outliers],
        "outlier_conditions": [",".join(t["conditions"]) for t in outliers],
        "clean_value": clean_value,
    }


def apply_clean(day: pd.DataFrame, checks: pd.DataFrame | None) -> pd.DataFrame:
    """Spec §5.1: a clean value is the most extreme in-band traded price, and is empty (NaN) when no
    in-band trade exists on that side. Clean values never lie outside the raw bar and are never invented
    by clipping a confirmed value into a bar that can't contain it.
    """
    out = day.copy()
    out["bad_high"] = False
    out["bad_low"] = False
    out["high_clean"] = out["high"].astype(float)
    out["low_clean"] = out["low"].astype(float)
    if checks is not None and not checks.empty:
        for check in checks[checks["decision"] == "isolated"].itertuples(index=False):
            matches = out.index[out["ts"] == check.ts]
            if len(matches) == 0:
                continue
            i = matches[0]
            side = check.side
            out.loc[i, f"bad_{side}"] = True
            low = float(out.loc[i, "low"])
            high = float(out.loc[i, "high"])
            reference = float(check.reference)
            band = float(check.band)
            # Whole bar beyond the band: the bar is only the bad print, so neither side has a trustworthy value.
            beyond_band = (high < reference - band) if side == "low" else (low > reference + band)
            if beyond_band:
                out.loc[i, ["high_clean", "low_clean"]] = np.nan
                continue
            column = f"{side}_clean"
            value = check.clean_value
            if value is None or pd.isna(value):
                out.loc[i, column] = np.nan
            else:
                value = float(value)
                if value < low - 1e-9 or value > high + 1e-9:
                    out.loc[i, column] = np.nan
                else:
                    out.loc[i, column] = value
    inverted = out["high_clean"].notna() & out["low_clean"].notna() & (out["low_clean"] > out["high_clean"])
    out.loc[inverted, ["high_clean", "low_clean"]] = np.nan
    return out
