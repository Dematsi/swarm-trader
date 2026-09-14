from datetime import time

import pytest

from src.options_research.config import STAGE1_DEV, TZ_ET

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def signals():
    from src.options_research.stage1 import load_signals, signals_path

    if not signals_path().exists():
        pytest.skip("stage-1 signals not built (run: python -m src.options_research stage1)")
    return load_signals()


def test_every_setup_and_direction_has_signals(signals):
    from src.options_research.setups import SETUPS

    assert set(zip(signals["setup"], signals["direction"])) == {(s, d) for s in SETUPS for d in ("long", "short")}


def test_signals_stay_inside_the_development_period(signals):
    assert signals["day"].min() >= STAGE1_DEV[0] and signals["day"].max() <= STAGE1_DEV[1]


EARLIEST_DECISION_BY_SETUP = {
    "ORB15": time(9, 46),
    "GAP_GO": time(9, 46),
    "PDL_BREAK": time(9, 46),
    "GAP_FILL": time(9, 46),
    "ORB30": time(10, 1),
    "VWAP_RECLAIM": time(10, 0),
    "VWAP_PULLBACK": time(10, 0),
    "MEANREV": time(10, 0),
    "SQUEEZE": time(10, 0),
}
LATEST_DECISION_BY_SETUP = {
    "ORB15": time(11, 30),
    "ORB30": time(11, 30),
    "GAP_GO": time(11, 30),
    "GAP_FILL": time(11, 0),
}
DEFAULT_LATEST_DECISION = time(15, 0)


def test_signals_respect_each_setups_decision_window(signals):
    clock = signals["decision_ts"].dt.tz_convert(TZ_ET).dt.time
    by_setup = signals.assign(clock=clock).groupby("setup")["clock"]
    for setup, group in by_setup:
        assert group.min() >= EARLIEST_DECISION_BY_SETUP[setup], f"{setup} earliest {group.min()}"
        assert group.max() <= LATEST_DECISION_BY_SETUP.get(setup, DEFAULT_LATEST_DECISION), f"{setup} latest {group.max()}"


def test_frequency_limits(signals):
    counts = signals.groupby(["symbol", "day", "setup", "direction"]).size()
    repeatable = counts.index.get_level_values("setup").isin(["VWAP_PULLBACK", "MEANREV"])
    assert counts[~repeatable].max() == 1 and counts[repeatable].max() <= 2


def test_outcomes_are_complete_and_plausible(signals):
    assert signals["ret_60"].notna().mean() > 0.99
    assert signals[["ret_30", "ret_60", "mfe_60", "mae_60"]].abs().max().max() < 0.5


def test_split_neighbourhoods_are_tagged(signals):
    assert signals["near_split"].any()
