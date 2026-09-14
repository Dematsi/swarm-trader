"""SQUEEZE breakout on 5-min bars (spec §6). Decision time is the trigger bar's end."""

from __future__ import annotations

from src.options_research.features import BB_K, BB_N, KC_K, KC_N
from src.options_research.setups.base import DEFAULT_WINDOW_END, DEFAULT_WINDOW_START, LONG, SHORT, DayContext, first_true, make_signal, previous_run, window_mask

MIN_SQUEEZE_BARS = 6
PARAMS = {
    "bollinger": f"{BB_N} bars, {BB_K:g} sigma (ddof=0)",
    "keltner": f"EMA{KC_N} +/- {KC_K:g} x Wilder ATR{KC_N}",
    "min_squeeze_bars": MIN_SQUEEZE_BARS,
    "squeeze_count": "today's 5-min bars only",
    "window": f"{DEFAULT_WINDOW_START.strftime('%H:%M')}-{DEFAULT_WINDOW_END.strftime('%H:%M')} on 5-min bar end",
    "invalidation": "5-min close vs KC midline",
}


def detect_squeeze(ctx: DayContext) -> list[dict]:
    five = ctx.five
    if five.empty:
        return []
    window = window_mask(five["end"], ctx.session, DEFAULT_WINDOW_START, DEFAULT_WINDOW_END)
    ready = previous_run(five["squeeze"].to_numpy(dtype=bool)) >= MIN_SQUEEZE_BARS
    close = five["close"].to_numpy(dtype=float)
    candidates = (
        (LONG, close > five["bb_up"].to_numpy(dtype=float), "below", "5m close>bb_up after 6 squeeze bars"),
        (SHORT, close < five["bb_lo"].to_numpy(dtype=float), "above", "5m close<bb_lo after 6 squeeze bars"),
    )
    signals = []
    for direction, hit, side, trigger in candidates:
        i = first_true(window & ready & hit)
        if i is not None:
            row = five.iloc[i]
            signals.append(make_signal(ctx, "SQUEEZE", direction, row["ts"], row["end"], row["close"], row["atr14"], "kc_mid", side, 0.0, trigger))
    return signals
