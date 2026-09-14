"""Stage-1 setup registry (spec §6): setup ID -> detector(DayContext) -> signal dicts (both directions)."""

from __future__ import annotations

from collections.abc import Callable

from src.options_research import features, levels
from src.options_research.setups import base, gaps_levels, mean_reversion, orb, squeeze, vwap
from src.options_research.setups.base import DayContext

SETUPS: dict[str, Callable[[DayContext], list[dict]]] = {
    "ORB15": lambda ctx: orb.detect_orb(ctx, 15),
    "ORB30": lambda ctx: orb.detect_orb(ctx, 30),
    "VWAP_RECLAIM": vwap.detect_vwap_reclaim,
    "VWAP_PULLBACK": vwap.detect_vwap_pullback,
    "MEANREV": mean_reversion.detect_meanrev,
    "GAP_GO": gaps_levels.detect_gap_go,
    "GAP_FILL": gaps_levels.detect_gap_fill,
    "PDL_BREAK": gaps_levels.detect_pdl_break,
    "SQUEEZE": squeeze.detect_squeeze,
}

SETUP_PARAMS: dict[str, dict] = {
    "ORB15": {**orb.PARAMS, "or_minutes": 15},
    "ORB30": {**orb.PARAMS, "or_minutes": 30},
    "VWAP_RECLAIM": vwap.RECLAIM_PARAMS,
    "VWAP_PULLBACK": vwap.PULLBACK_PARAMS,
    "MEANREV": mean_reversion.PARAMS,
    "GAP_GO": gaps_levels.GAP_GO_PARAMS,
    "GAP_FILL": gaps_levels.GAP_FILL_PARAMS,
    "PDL_BREAK": gaps_levels.PDL_PARAMS,
    "SQUEEZE": squeeze.PARAMS,
}


def detect_all(ctx: DayContext) -> list[dict]:
    return [signal for detect in SETUPS.values() for signal in detect(ctx)]


def _hhmm(value) -> str:
    return value.strftime("%H:%M")


def _build_shared_params() -> dict:
    # Deferred: stage1.py imports this package (`from src.options_research.setups import detect_all`), so
    # importing stage1 at module scope here would create an import cycle. This is only evaluated the first
    # time `SHARED_PARAMS` is accessed (see module __getattr__ below), by which point the cycle has resolved.
    from src.options_research import stage1

    return {
        "features": {
            "atr_n": features.ATR_N,
            "rsi_n": features.RSI_N,
            "adx_n": features.ADX_N,
            "bb_n": features.BB_N,
            "bb_k": features.BB_K,
            "kc_n": features.KC_N,
            "kc_k": features.KC_K,
        },
        "levels": {
            "premarket_min_volume": levels.PREMARKET_MIN_VOLUME,
            "earliest_premarket_read": _hhmm(levels.EARLIEST_PREMARKET_READ),
            "or_volume_lookback": levels.OR_VOLUME_LOOKBACK,
            "warmup_sessions": levels.WARMUP_SESSIONS,
            "or_minutes": list(levels.OR_MINUTES),
        },
        "base": {
            "default_window_start": _hhmm(base.DEFAULT_WINDOW_START),
            "default_window_end": _hhmm(base.DEFAULT_WINDOW_END),
            "last_entry_before_close_min": int(base.LAST_ENTRY_BEFORE_CLOSE.total_seconds() // 60),
            "cooldown_min": int(base.COOLDOWN.total_seconds() // 60),
            "max_per_day": base.MAX_PER_DAY,
        },
        "stage1": {"horizons": list(stage1.HORIZONS), "excursion_minutes": stage1.EXCURSION_MINUTES},
    }


_SHARED_PARAMS_CACHE: dict | None = None


def __getattr__(name: str):
    global _SHARED_PARAMS_CACHE
    if name == "SHARED_PARAMS":
        if _SHARED_PARAMS_CACHE is None:
            _SHARED_PARAMS_CACHE = _build_shared_params()
        return _SHARED_PARAMS_CACHE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
