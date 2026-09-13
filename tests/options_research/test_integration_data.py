from datetime import date, time

import pytest

from src.options_research.config import UNIVERSE, lake_root

pytestmark = pytest.mark.integration


def test_expected_splits_detected():
    from src.options_research.corporate_actions import EXPECTED_SPLITS, load_splits

    splits = load_splits()
    found = {(r.symbol, r.day, float(r.ratio)) for r in splits.itertuples()}
    assert EXPECTED_SPLITS <= found


def test_nvda_split_day_minutes_are_clean():
    from src.options_research.store import load_stock_minutes

    nvda = load_stock_minutes(["NVDA"], date(2024, 6, 10), date(2024, 6, 10), clean=True)
    assert nvda["high"].max() < 130
    assert not nvda["bad_high"].any()
    assert not nvda["bad_low"].any()


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
        assert result["rth_compared"] > 1000, day
        assert result["rth_max_close_diff_pct"] < 0.005, (day, result)
        assert result["rth_close_mismatch"] / result["rth_compared"] < 0.05, (day, result)
        assert result["ohlc_mismatch"] / result["compared"] < 0.05, (day, result)


def test_cost_model_covers_universe():
    from src.options_research.costs import load_cost_model

    model = load_cost_model()
    for symbol in UNIVERSE:
        h, level = model.base_half_spread(symbol, 2, 0.0, 2.0, time(11, 0))
        assert 0.005 <= h < 1.0 and level >= 1, symbol


def _bar(symbol, iso_ts):
    import pandas as pd

    from src.options_research.store import load_stock_minutes

    ts = pd.Timestamp(iso_ts)
    day = ts.tz_convert("America/New_York").date()
    minutes = load_stock_minutes([symbol], day, day, clean=True)
    return minutes[minutes["ts"] == ts].iloc[0]


def test_clean_values_never_outside_raw_bar():
    import duckdb

    pattern = (lake_root() / "stock_1m" / "*" / "*" / "*.parquet").as_posix()
    con = duckdb.connect()
    bad = con.execute(
        f"SELECT count(*) FROM read_parquet('{pattern}', union_by_name=true) "
        "WHERE high_clean > high + 1e-9 OR low_clean < low - 1e-9 OR low_clean > high_clean + 1e-9"
    ).fetchone()[0]
    assert bad == 0


def test_known_isolated_prints_are_cleaned():
    meta = _bar("META", "2023-02-01T23:15:00Z")
    assert meta["bad_low"] and abs(meta["low_clean"] - 182.75) <= 0.02
    googl = _bar("GOOGL", "2024-04-25T22:54:00Z")
    assert googl["bad_low"] and abs(googl["low_clean"] - 174.80) <= 0.02
    qqq = _bar("QQQ", "2022-05-09T18:58:00Z")
    assert qqq["bad_high"] and abs(qqq["high_clean"] - 299.67) <= 0.02
    iwm = _bar("IWM", "2023-03-17T21:53:00Z")
    assert iwm["bad_high"] and abs(iwm["high_clean"] - 171.77) <= 0.02


def test_genuine_moves_keep_raw_values():
    meta = _bar("META", "2022-04-27T17:01:00Z")
    assert not meta["bad_low"] and meta["low_clean"] == meta["low"] == 169.0
    amzn = _bar("AMZN", "2022-10-27T20:01:00Z")
    assert not amzn["bad_low"] and not amzn["bad_high"]
    assert amzn["low_clean"] == amzn["low"] and amzn["high_clean"] == amzn["high"]


def test_isolated_checks_match_lake_flags_and_clean_values():
    """Spec §5.1 invariant (this is the check that would have caught review Important #1): every isolated
    print check must (a) sum to the lake-wide bad_high/bad_low flag count and (b) leave the flagged bar's
    clean value on that side either empty or within the confirmed reference +/- band. Read-only, and joined
    in DuckDB rather than looped in Python since the lake has ~11.6M rows.
    """
    import duckdb

    from src.options_research.print_checks import candidates_path, checks_path

    root = lake_root()
    cand_path = candidates_path(root)
    chk_path = checks_path(root)
    if not cand_path.exists() or not chk_path.exists():
        pytest.skip("print_checks candidates/checks not present in this lake")

    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        # Only checks whose (symbol, ts, side) key is among the *current* candidates (mirrors rebuild_clean).
        current_checks = con.execute(
            f"""
            SELECT c.symbol, c.ts, c.side, c.decision, c.reference, c.band
            FROM read_parquet('{chk_path.as_posix()}') c
            JOIN read_parquet('{cand_path.as_posix()}') d
              ON c.symbol = d.symbol AND c.ts = d.ts AND c.side = d.side
            """
        ).df()
        isolated = current_checks[current_checks["decision"] == "isolated"].reset_index(drop=True)

        stock_pattern = (root / "stock_1m" / "*" / "*" / "*.parquet").as_posix()
        bad_high, bad_low = con.execute(
            f"SELECT sum(CAST(bad_high AS BIGINT)), sum(CAST(bad_low AS BIGINT)) "
            f"FROM read_parquet('{stock_pattern}', union_by_name=true)"
        ).fetchone()
        assert (bad_high or 0) + (bad_low or 0) == len(isolated)

        if isolated.empty:
            return

        con.register("isolated_checks", isolated)
        joined = con.execute(
            f"""
            SELECT ic.symbol, ic.ts, ic.side, ic.reference, ic.band, b.bad_high, b.bad_low, b.high_clean, b.low_clean
            FROM isolated_checks ic
            JOIN read_parquet('{stock_pattern}', union_by_name=true) b
              ON ic.symbol = b.symbol AND ic.ts = b.ts
            """
        ).df()
        assert len(joined) == len(isolated), "every isolated check must match exactly one lake bar"

        import pandas as pd

        for row in joined.itertuples(index=False):
            flag = row.bad_high if row.side == "high" else row.bad_low
            clean = row.high_clean if row.side == "high" else row.low_clean
            assert flag, (row.symbol, row.ts, row.side)
            in_band = (row.reference - row.band - 1e-6) <= clean <= (row.reference + row.band + 1e-6)
            assert pd.isna(clean) or in_band, (row.symbol, row.ts, row.side, clean, row.reference, row.band)
    finally:
        con.close()
