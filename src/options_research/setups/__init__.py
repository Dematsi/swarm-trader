"""Stage-1 setup registry (spec §6): setup ID -> detector(DayContext) -> signal dicts (both directions)."""

from __future__ import annotations

from collections.abc import Callable

from src.options_research.setups import gaps_levels, orb
from src.options_research.setups.base import DayContext

SETUPS: dict[str, Callable[[DayContext], list[dict]]] = {
    "ORB15": lambda ctx: orb.detect_orb(ctx, 15),
    "ORB30": lambda ctx: orb.detect_orb(ctx, 30),
    "GAP_GO": gaps_levels.detect_gap_go,
    "GAP_FILL": gaps_levels.detect_gap_fill,
    "PDL_BREAK": gaps_levels.detect_pdl_break,
}

SETUP_PARAMS: dict[str, dict] = {
    "ORB15": {**orb.PARAMS, "or_minutes": 15},
    "ORB30": {**orb.PARAMS, "or_minutes": 30},
    "GAP_GO": gaps_levels.GAP_GO_PARAMS,
    "GAP_FILL": gaps_levels.GAP_FILL_PARAMS,
    "PDL_BREAK": gaps_levels.PDL_PARAMS,
}


def detect_all(ctx: DayContext) -> list[dict]:
    return [signal for detect in SETUPS.values() for signal in detect(ctx)]
