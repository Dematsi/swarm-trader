from datetime import date, time

import pytest

from src.options_research.config import UNIVERSE, lake_root

pytestmark = pytest.mark.integration


def test_expected_splits_detected():
    from src.options_research.corporate_actions import EXPECTED_SPLITS, load_splits

    splits = load_splits()
    found = {(r.symbol, r.day, float(r.ratio)) for r in splits.itertuples()}
    assert EXPECTED_SPLITS <= found


def test_nvda_split_day_bad_high_is_flagged():
    from src.options_research.store import load_stock_minutes

    nvda = load_stock_minutes(["NVDA"], date(2024, 6, 10), date(2024, 6, 10))
    assert nvda["high"].max() > 190
    assert nvda["high_clean"].max() < 130


def test_every_ticker_has_zip_and_tail_coverage():
    from src.options_research.stocks import day_path

    for symbol in UNIVERSE:
        assert day_path(lake_root(), symbol, date(2021, 6, 18)).exists(), symbol
        assert day_path(lake_root(), symbol, date(2026, 9, 11)).exists(), symbol


def test_zip_matches_alpaca_on_sampled_days():
    import json

    overlap = json.loads((lake_root() / "validation" / "zip_vs_alpaca.json").read_text())
    assert overlap
    for day, result in overlap.items():
        assert result["compared"] > 1000, day
        assert result["ohlc_mismatch"] / result["compared"] < 0.001, (day, result)


def test_cost_model_covers_universe():
    from src.options_research.costs import load_cost_model

    model = load_cost_model()
    for symbol in UNIVERSE:
        h, level = model.base_half_spread(symbol, 2, 0.0, 2.0, time(11, 0))
        assert 0.005 <= h < 1.0 and level >= 1, symbol
