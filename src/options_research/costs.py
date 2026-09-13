"""Option half-spread cost model calibrated from Schwab quotes in the sibling DB (spec §5.6)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

import numpy as np
import pandas as pd

from src.options_research.config import TZ_ET, lake_root

COST_KEYS = ["underlying", "dte_bucket", "moneyness", "premium", "tod_bucket"]
MIN_CELL_N = 30


def dte_bucket(dte: int) -> str:
    if dte <= 0:
        return "0"
    if dte <= 2:
        return "1-2"
    if dte <= 7:
        return "3-7"
    return "8+"


def otm_pct(strike: float, spot: float, option_type: str) -> float:
    if option_type.lower().startswith("c"):
        return (strike / spot - 1.0) * 100.0
    return (1.0 - strike / spot) * 100.0


def moneyness_bucket(otm: float) -> str:
    if otm < -0.5:
        return "ITM"
    if otm <= 0.5:
        return "ATM"
    if otm <= 2.0:
        return "OTM1"
    return "OTM2"


def premium_bucket(mid: float) -> str:
    if mid < 1.0:
        return "<1"
    if mid < 3.0:
        return "1-3"
    if mid < 10.0:
        return "3-10"
    return "10+"


def tod_bucket(t: time) -> str:
    if t < time(10, 0):
        return "open"
    if t < time(15, 0):
        return "mid"
    return "close"


SCHWAB_COST_SQL = """
WITH x AS (
    SELECT underlying,
           dte,
           CASE WHEN lower(option_type) LIKE 'c%%' THEN (strike / underlying_spot - 1) * 100
                ELSE (1 - strike / underlying_spot) * 100 END AS otm,
           (bid + ask) / 2 AS mid,
           (ask - bid) / 2 AS half_spread,
           (bucket_time AT TIME ZONE 'America/New_York')::time AS tod
    FROM contract_greeks
    WHERE underlying = ANY(%(underlyings)s)
      AND snapshot_time >= %(start)s AND snapshot_time < %(end)s
      AND bid > 0 AND ask > bid AND underlying_spot > 0
      AND dte BETWEEN 0 AND 45
      AND extract(minute FROM bucket_time)::int %% 15 = 0
), q AS (
    SELECT underlying,
           CASE WHEN dte = 0 THEN '0' WHEN dte <= 2 THEN '1-2' WHEN dte <= 7 THEN '3-7' ELSE '8+' END AS dte_bucket,
           CASE WHEN otm < -0.5 THEN 'ITM' WHEN otm <= 0.5 THEN 'ATM' WHEN otm <= 2 THEN 'OTM1' ELSE 'OTM2' END AS moneyness,
           CASE WHEN mid < 1 THEN '<1' WHEN mid < 3 THEN '1-3' WHEN mid < 10 THEN '3-10' ELSE '10+' END AS premium,
           CASE WHEN tod < time '10:00' THEN 'open' WHEN tod < time '15:00' THEN 'mid' ELSE 'close' END AS tod_bucket,
           half_spread, mid
    FROM x
    WHERE tod >= time '09:30' AND tod < time '16:00'
)
SELECT underlying, dte_bucket, moneyness, premium, tod_bucket,
       count(*) AS n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY half_spread) AS half_spread,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY mid) AS mid
FROM q
GROUP BY GROUPING SETS (
    (underlying, dte_bucket, moneyness, premium, tod_bucket),
    (underlying, dte_bucket, moneyness, premium),
    (underlying, dte_bucket, moneyness),
    (underlying, dte_bucket),
    (underlying)
)
"""


def build_cost_table(conn, underlyings, start: datetime, end: datetime) -> pd.DataFrame:
    rows = conn.execute(SCHWAB_COST_SQL, {"underlyings": list(underlyings), "start": start, "end": end}).fetchall()
    frame = pd.DataFrame(rows, columns=COST_KEYS + ["n", "half_spread", "mid"])
    frame["n"] = frame["n"].astype("int64")
    frame["half_spread"] = frame["half_spread"].astype(float)
    frame["mid"] = frame["mid"].astype(float)
    return frame


def scale_half_spread(h: float, rv_prev: float | None, rv_cal: float | None, in_event_window: bool, floor: float = 0.005) -> float:
    ratio = 1.0 if not rv_prev or not rv_cal else min(3.0, max(1.0, rv_prev / rv_cal))
    return max(floor, h * ratio * (2.0 if in_event_window else 1.0))


@dataclass
class CostModel:
    table: pd.DataFrame
    fees_per_side: float = 0.05
    min_half_spread: float = 0.005
    _lookup: dict = field(init=False, repr=False)

    def __post_init__(self) -> None:
        keys = self.table[COST_KEYS].astype(object).where(self.table[COST_KEYS].notna(), None)
        self._lookup = {
            tuple(key): (int(n), float(h))
            for key, n, h in zip(keys.itertuples(index=False, name=None), self.table["n"], self.table["half_spread"])
        }

    def base_half_spread(self, underlying: str, dte: int, otm: float, premium: float, tod: time) -> tuple[float, int]:
        full = (underlying, dte_bucket(dte), moneyness_bucket(otm), premium_bucket(premium), tod_bucket(tod))
        for level in (5, 4, 3, 2, 1):
            hit = self._lookup.get(full[:level] + (None,) * (5 - level))
            if hit and hit[0] >= MIN_CELL_N:
                return max(hit[1], self.min_half_spread), level
        raise KeyError(f"no cost cell for {underlying}")

    def half_spread(
        self,
        underlying: str,
        dte: int,
        otm: float,
        premium: float,
        tod: time,
        rv_prev: float | None = None,
        rv_cal: float | None = None,
        in_event_window: bool = False,
    ) -> float:
        h, _ = self.base_half_spread(underlying, dte, otm, premium, tod)
        return scale_half_spread(h, rv_prev, rv_cal, in_event_window, floor=self.min_half_spread)


def session_realized_vol(minutes: pd.DataFrame) -> pd.Series:
    et = minutes["ts"].dt.tz_convert(TZ_ET)
    minute_of_day = et.dt.hour * 60 + et.dt.minute
    mask = (minute_of_day >= 570) & (minute_of_day < 960)
    rth = minutes.loc[mask].assign(day=et[mask].dt.date).sort_values("ts")
    log_returns = rth.groupby("day")["close"].transform(lambda s: np.log(s.astype(float)).diff())
    return log_returns.groupby(rth["day"]).std().mul(np.sqrt(390)).rename("rv")


def save_cost_table(df: pd.DataFrame, root: Path | None = None) -> Path:
    path = (root or lake_root()) / "costs" / "half_spread_table.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def save_calibration(payload: dict, root: Path | None = None) -> Path:
    path = (root or lake_root()) / "costs" / "calibration.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def load_cost_model(root: Path | None = None, fees_per_side: float = 0.05) -> CostModel:
    table = pd.read_parquet((root or lake_root()) / "costs" / "half_spread_table.parquet")
    return CostModel(table, fees_per_side=fees_per_side)
