"""Stage-1 evaluation (spec §8.3): day-block bootstrap t-stat, year consistency, cost-aware break-even, signal count."""

from __future__ import annotations

from datetime import date, time, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from src.options_research.config import DATA_FREEZE, TZ_ET
from src.options_research.costs import CostModel, dte_bucket, tod_bucket
from src.options_research.market_calendar import get_session, previous_session_on_or_before
from src.options_research.store import load_stock_minutes

PRIMARY = "ret_60"
T_MIN = 3.0
MIN_SIGNALS = 300
MIN_POSITIVE_YEARS = 4
COST_MULTIPLE = 1.5
RESAMPLES = 10_000
DESCRIPTIVE_RESAMPLES = 2_000
SEED = 20260912
ATM_DELTA = 0.5
COST_CALIBRATION = (date(2026, 8, 21), DATA_FREEZE)
FEES_PER_CONTRACT_SIDE = CostModel.__dataclass_fields__["fees_per_side"].default
EVAL_PARAMS = {
    "primary": PRIMARY, "t_min": T_MIN, "min_signals": MIN_SIGNALS, "min_positive_years": MIN_POSITIVE_YEARS, "cost_multiple": COST_MULTIPLE,
    "resamples": RESAMPLES, "seed": SEED, "atm_delta": ATM_DELTA, "near_expiry": "that week's Friday (prior session if holiday)",
    "cost_scaling": f"ATM level-3 mid premium; h x price / median RTH close {COST_CALIBRATION[0]}..{COST_CALIBRATION[1]}",
    "fees_per_contract_side": FEES_PER_CONTRACT_SIDE,
}
EVALUATION_COLUMNS = ["setup", "direction", "n", "mean_ret_60", "se", "t", "positive_years", "pooled_break_even", "cost_ratio", "pass_t", "pass_years", "pass_cost", "pass_n", "passed"]


def day_block_bootstrap(values, days, resamples: int = RESAMPLES, seed: int = SEED) -> tuple[float, float, float]:
    """Mean per signal, with SE and t from resampling whole trading days with replacement."""
    frame = pd.DataFrame({"value": np.asarray(values, dtype=float), "day": np.asarray(days)}).dropna(subset=["value"])
    if frame.empty:
        return float("nan"), float("nan"), float("nan")
    grouped = frame.groupby("day")["value"].agg(["sum", "count"])
    sums, counts = grouped["sum"].to_numpy(dtype=float), grouped["count"].to_numpy(dtype=float)
    mean = float(sums.sum() / counts.sum())
    if len(sums) < 2:
        return mean, float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    boots = np.empty(resamples)
    for start in range(0, resamples, 500):
        size = min(500, resamples - start)
        picks = rng.integers(0, len(sums), size=(size, len(sums)))
        boots[start:start + size] = sums[picks].sum(axis=1) / counts[picks].sum(axis=1)
    se = float(boots.std(ddof=1))
    return mean, se, (mean / se if se > 0 else float("nan"))


@lru_cache(maxsize=None)
def near_expiry_dte(day: date) -> int:
    """Calendar days to that week's Friday expiration, or to the prior session when Friday is a holiday."""
    friday = day + timedelta(days=4 - day.weekday())
    if get_session(friday) is None:
        friday = previous_session_on_or_before(friday)
    return max(0, (friday - day).days)


def atm_mid(table: pd.DataFrame, symbol: str, bucket: str) -> float:
    cell = table[(table["underlying"] == symbol) & (table["dte_bucket"] == bucket) & (table["moneyness"] == "ATM") & table["premium"].isna() & table["tod_bucket"].isna()]
    if cell.empty:
        raise KeyError(f"no ATM level-3 cost cell for {symbol} DTE bucket {bucket}")
    return float(cell["mid"].iloc[0])


def _break_even(h_cal: float, price: float, calibration_spot: float, fees_per_side: float) -> float:
    half_spread = h_cal * price / calibration_spot
    fee_per_share = fees_per_side / 100.0
    return (2.0 * half_spread + 2.0 * fee_per_share) / (ATM_DELTA * price)


def break_even_frac(model: CostModel, symbol: str, day: date, decision_time: time, price: float, calibration_spot: float) -> float:
    """Stock move (fraction of price) that pays the round-trip spread and fees of an ATM NEAR option (spec §8.3)."""
    dte = near_expiry_dte(day)
    h_cal, _ = model.base_half_spread(symbol, dte, 0.0, atm_mid(model.table, symbol, dte_bucket(dte)), decision_time)
    return _break_even(h_cal, price, calibration_spot, model.fees_per_side)


def add_break_even(signals: pd.DataFrame, model: CostModel, spots: dict[str, float]) -> pd.DataFrame:
    out = signals.copy()
    clock = pd.to_datetime(out["decision_ts"], utc=True).dt.tz_convert(TZ_ET).dt.time
    cache: dict[tuple, float] = {}
    values = []
    for symbol, day, decided, price in zip(out["symbol"], out["day"], clock, out["price"]):
        dte = near_expiry_dte(day)
        key = (symbol, dte, tod_bucket(decided))
        if key not in cache:
            cache[key] = model.base_half_spread(symbol, dte, 0.0, atm_mid(model.table, symbol, dte_bucket(dte)), decided)[0]
        values.append(_break_even(cache[key], float(price), spots[symbol], model.fees_per_side))
    out["be_frac"] = values
    return out


def evaluate_stage1(signals: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (setup, direction), group in signals.groupby(["setup", "direction"], sort=True):
        valid = group[group[PRIMARY].notna()]
        mean, se, t = day_block_bootstrap(valid[PRIMARY], valid["day"])
        years = valid.groupby(pd.to_datetime(valid["day"]).dt.year)[PRIMARY].mean()
        positive_years = int((years > 0).sum())
        pooled = float(valid.groupby("symbol")["be_frac"].median().median()) if len(valid) else float("nan")
        ratio = mean / pooled if pooled > 0 else float("nan")
        checks = {"pass_t": bool(t >= T_MIN), "pass_years": positive_years >= MIN_POSITIVE_YEARS, "pass_cost": bool(ratio >= COST_MULTIPLE), "pass_n": len(valid) >= MIN_SIGNALS}
        rows.append({"setup": setup, "direction": direction, "n": int(len(valid)), "mean_ret_60": mean, "se": se, "t": t, "positive_years": positive_years, "pooled_break_even": pooled, "cost_ratio": ratio, **checks, "passed": all(checks.values())})
    return pd.DataFrame(rows, columns=EVALUATION_COLUMNS)


def horizon_table(signals: pd.DataFrame) -> pd.DataFrame:
    grouped = signals.groupby(["setup", "direction"], sort=True)
    return pd.DataFrame({
        "n": grouped.size(),
        "mean_ret_30": grouped["ret_30"].mean(),
        "mean_ret_60": grouped["ret_60"].mean(),
        "mean_ret_hard": grouped["ret_hard"].mean(),
        "median_mfe_60": grouped["mfe_60"].median(),
        "median_mae_60": grouped["mae_60"].median(),
    }).reset_index()


def event_table(signals: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (setup, direction), group in signals.groupby(["setup", "direction"], sort=True):
        quiet = group[~group["event_day"].astype(bool)]
        mean_all, _, t_all = day_block_bootstrap(group[PRIMARY], group["day"], resamples=DESCRIPTIVE_RESAMPLES)
        mean_ex, _, t_ex = day_block_bootstrap(quiet[PRIMARY], quiet["day"], resamples=DESCRIPTIVE_RESAMPLES)
        rows.append({"setup": setup, "direction": direction, "n_all": len(group), "mean_all": mean_all, "t_all": t_all, "n_ex_event": len(quiet), "mean_ex_event": mean_ex, "t_ex_event": t_ex})
    return pd.DataFrame(rows)


def per_ticker_means(signals: pd.DataFrame) -> pd.DataFrame:
    """Mean primary return in basis points, rows setup/direction, columns ticker."""
    return (signals.pivot_table(index=["setup", "direction"], columns="symbol", values=PRIMARY, aggfunc="mean") * 1e4).round(1)


def per_ticker_break_even(signals: pd.DataFrame) -> pd.Series:
    """Median break-even move per ticker in basis points."""
    return (signals.groupby("symbol")["be_frac"].median() * 1e4).round(2)


def calibration_spots(symbols, root: Path | None = None) -> dict[str, float]:
    # Cost-model calibration exception to the holdout guard (spec §9.1): spot levels that scale the
    # 2026-calibrated half-spreads to each signal's price. No signals or returns are computed here.
    minutes = load_stock_minutes(list(symbols), *COST_CALIBRATION, holdout=True, root=root)
    et = minutes["ts"].dt.tz_convert(TZ_ET)
    minute_of_day = et.dt.hour * 60 + et.dt.minute
    rth = minutes[(minute_of_day >= 570) & (minute_of_day < 960)]
    return {symbol: float(value) for symbol, value in rth.groupby("symbol")["close"].median().items()}
