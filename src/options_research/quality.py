"""Trailing-window bad-print detection for 1-minute stock bars (spec §5.1)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def flag_bad_prints(df: pd.DataFrame, window: int = 15, mad_mult: float = 8.0, min_pct: float = 0.03) -> pd.DataFrame:
    out = df.copy()
    close = out["close"].astype(float)
    previous = close.shift(1)
    reference = previous.rolling(window, min_periods=1).median()
    mad = (previous - reference).abs().rolling(window, min_periods=1).median()
    threshold = np.maximum(mad_mult * mad, min_pct * reference)
    lower, upper = reference - threshold, reference + threshold

    def outside(values: pd.Series) -> pd.Series:
        return (values.astype(float) - reference).abs() > threshold  # NaN reference (first bar) -> False

    out["bad_high"] = outside(out["high"])
    out["bad_low"] = outside(out["low"])
    out["bad_close"] = outside(close)
    body_high = out[["open", "close"]].max(axis=1).astype(float).clip(lower=lower, upper=upper)
    body_low = out[["open", "close"]].min(axis=1).astype(float).clip(lower=lower, upper=upper)
    out["high_clean"] = out["high"].astype(float).where(~out["bad_high"], body_high)
    out["low_clean"] = out["low"].astype(float).where(~out["bad_low"], body_low)
    out["low_clean"] = np.minimum(out["low_clean"], out["high_clean"])
    return out
