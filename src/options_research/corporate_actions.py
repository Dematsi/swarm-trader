"""Split detection from raw (unadjusted) minute bars and price/volume adjustment factors (spec §5.1)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.options_research.config import TZ_ET, lake_root
from src.options_research.market_calendar import get_session

SPLIT_RATIOS = (2, 3, 4, 5, 10, 15, 20)
EXPECTED_SPLITS: frozenset[tuple[str, date, float]] = frozenset({
    ("NVDA", date(2021, 7, 20), 4.0),
    ("AMZN", date(2022, 6, 6), 20.0),
    ("GOOGL", date(2022, 7, 18), 20.0),
    ("TSLA", date(2022, 8, 25), 3.0),
    ("NVDA", date(2024, 6, 10), 10.0),
})
SPLIT_COLUMNS = ["symbol", "day", "ratio", "factor"]


def daily_rth_summary(minutes: pd.DataFrame) -> pd.DataFrame:
    frame = minutes.assign(ts_et=minutes["ts"].dt.tz_convert(TZ_ET))
    frame["day"] = frame["ts_et"].dt.date
    closes = {d: get_session(d) for d in frame["day"].unique()}
    in_rth = [
        closes[d] is not None and closes[d].open_et <= t < closes[d].close_et
        for d, t in zip(frame["day"], frame["ts_et"])
    ]
    rth = frame[np.array(in_rth, dtype=bool)].sort_values("ts")
    summary = rth.groupby(["symbol", "day"], sort=True).agg(
        rth_open=("open", "first"), rth_close=("close", "last"), rth_volume=("volume", "sum")
    ).reset_index()
    summary["rth_volume"] = summary["rth_volume"].astype("int64")
    return summary


def detect_splits(daily: pd.DataFrame, tol: float = 0.03) -> pd.DataFrame:
    found: list[dict] = []
    for symbol, group in daily.sort_values(["symbol", "day"]).groupby("symbol", sort=True):
        group = group.reset_index(drop=True)
        prior_close = group["rth_close"].shift(1)
        median_volume = group["rth_volume"].shift(1).rolling(20, min_periods=5).median()
        for i in range(1, len(group)):
            if not median_volume.iloc[i] or np.isnan(median_volume.iloc[i]):
                continue
            price_ratio = prior_close.iloc[i] / group.loc[i, "rth_open"]
            volume_ratio = group.loc[i, "rth_volume"] / median_volume.iloc[i]
            for r in SPLIT_RATIOS:
                if abs(price_ratio / r - 1) <= tol and volume_ratio >= max(1.5, 0.5 * r):
                    found.append({"symbol": symbol, "day": group.loc[i, "day"], "ratio": float(r), "factor": 1.0 / r})
                    break
                if abs(price_ratio * r - 1) <= tol and volume_ratio <= 2.0 / r:
                    found.append({"symbol": symbol, "day": group.loc[i, "day"], "ratio": 1.0 / r, "factor": float(r)})
                    break
    return pd.DataFrame(found, columns=SPLIT_COLUMNS)


def adjustment_factors(splits: pd.DataFrame, symbol: str, days: pd.Series) -> pd.Series:
    factors = pd.Series(1.0, index=days.index)
    for _, split in splits[splits["symbol"] == symbol].iterrows():
        factors[days < split["day"]] *= split["factor"]
    return factors


def write_splits(df: pd.DataFrame, root: Path | None = None) -> Path:
    path = (root or lake_root()) / "corporate_actions" / "splits.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def load_splits(root: Path | None = None) -> pd.DataFrame:
    frame = pd.read_parquet((root or lake_root()) / "corporate_actions" / "splits.parquet")
    frame["day"] = pd.to_datetime(frame["day"]).dt.date
    return frame[SPLIT_COLUMNS]
