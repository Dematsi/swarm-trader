import json
from datetime import date

import pandas as pd

from src.options_research import cli
from src.options_research.corporate_actions import write_splits
from src.options_research.costs import COST_KEYS, save_calibration, save_cost_table
from src.options_research.events_sources import write_events
from src.options_research.reports import m1_report, m2_report, write_report
from src.options_research.stocks import write_day


def seed_lake(root):
    frame = pd.DataFrame({
        "symbol": ["NVDA", "NVDA"], "ts": pd.to_datetime(["2024-06-10T13:30:00Z", "2024-06-10T13:31:00Z"], utc=True),
        "open": [120.0, 121.0], "high": [195.95, 121.5], "low": [119.0, 120.5], "close": [121.0, 121.2],
        "volume": [100, 200], "transactions": [1, 2], "bad_high": [True, False], "bad_low": [False, False],
        "high_clean": [121.0, 121.5], "low_clean": [119.0, 120.5], "source": ["zip", "zip"],
    })
    write_day(frame, date(2024, 6, 10), root)
    write_splits(pd.DataFrame([{"symbol": "NVDA", "day": date(2024, 6, 10), "ratio": 10.0, "factor": 0.1}]), root=root)
    events = pd.DataFrame([
        {"date": date(2024, 6, 12), "time_et": "14:00", "type": "fomc_decision", "tier": "1", "source": "fomc_csv", "ticker": None},
        {"date": date(2024, 5, 23), "time_et": None, "type": "earnings_amc", "tier": "earnings", "source": "yfinance", "ticker": "NVDA"},
    ])
    write_events(events, {"fred": "skipped: FRED_API_KEY not set"}, root=root)
    (root / "validation").mkdir(parents=True, exist_ok=True)
    (root / "validation" / "zip_vs_alpaca.json").write_text(json.dumps({"2026-06-18": {"compared": 10, "ohlc_mismatch": 0, "volume_mismatch": 0, "zip_only": 0, "alpaca_only": 0}}))
    save_cost_table(pd.DataFrame([
        ("SPY", "1-2", "ATM", None, None, 400, 0.015, 2.0),
        ("SPY", "1-2", None, None, None, 900, 0.020, 3.0),
        ("SPY", None, None, None, None, 5000, 0.030, 4.0),
    ], columns=COST_KEYS + ["n", "half_spread", "mid"]), root=root)
    save_calibration({"rv_cal": 0.12, "sessions": 15, "window": "2026-08-21..2026-09-11"}, root=root)


def test_stock_aggregates_counts_session_days_not_utc_dates(tmp_path):
    from src.options_research.reports import _stock_aggregates

    # Session day 2022-01-11 (ET) has an open-time bar plus a genuine post-market bar
    # (19:30 ET) that lands on the NEXT UTC calendar day (2022-01-12T00:30:00Z). Both
    # bars belong to the same file: stock_1m/NVDA/2022/2022-01-11.parquet.
    frame = pd.DataFrame({
        "symbol": ["NVDA", "NVDA"],
        "ts": pd.to_datetime(["2022-01-11T14:30:00Z", "2022-01-12T00:30:00Z"], utc=True),
        "open": [10.0, 10.0], "high": [10.0, 10.5], "low": [10.0, 9.0], "close": [10.0, 9.5],
        "volume": [100, 100], "transactions": [1, 1],
        "bad_high": [False, True], "bad_low": [False, False],
        "high_clean": [10.0, 10.0], "low_clean": [10.0, 9.0], "source": ["zip", "zip"],
    })
    write_day(frame, date(2022, 1, 11), tmp_path)
    agg = _stock_aggregates(tmp_path)
    row = agg[(agg["symbol"] == "NVDA") & (agg["year"] == 2022)].iloc[0]
    assert row["days"] == 1
    assert row["rows"] == 2
    assert row["bad_high"] == 1


def test_m1_report_sections(tmp_path):
    seed_lake(tmp_path)
    text = m1_report(root=tmp_path)
    for heading in (
        "# M1 Data Foundation Report",
        "## Stock minute coverage",
        "## Bad prints",
        "## Largest bad-print adjustments",
        "## Splits",
        "## Zip vs Alpaca overlap",
        "## Events",
        "## Earnings spot-check",
    ):
        assert heading in text
    assert "NVDA" in text and "2024-06-10" in text
    assert "missing expected" in text  # the seeded lake lacks 4 of the 5 expected splits
    assert "UNCONFIRMED" in text
    assert "skipped: FRED_API_KEY not set" in text
    assert "195.95" in text
    assert "volume differs between vendors" in text
    assert "## Print checks (trade-level confirmation)" in text
    assert "Not run." in text  # no audit file seeded
    assert "+00:00" in text  # adjustments table ts rendered in UTC


def test_m2_report_sections(tmp_path):
    seed_lake(tmp_path)
    text = m2_report(root=tmp_path)
    assert "# M2 Cost Model Report" in text
    assert "rv_cal" in text and "0.12" in text
    assert "SPY" in text and "1-2" in text


def test_write_report(tmp_path):
    path = write_report("m1_data_foundation", "# hi\n", directory=tmp_path)
    assert path == tmp_path / "m1_data_foundation.md" and path.read_text() == "# hi\n"


def test_write_report_is_utf8(tmp_path):
    path = write_report("m1_data_foundation", "a — b §", directory=tmp_path)
    assert path.read_bytes().decode("utf-8") == "a — b §"


def test_cli_report_commands_write_files(tmp_path, monkeypatch):
    seed_lake(tmp_path / "lake")
    monkeypatch.setenv("OPTIONS_LAKE_ROOT", str(tmp_path / "lake"))
    monkeypatch.setenv("OPTIONS_REPORTS_DIR", str(tmp_path / "reports"))
    assert cli.main(["report-m1"]) == 0
    assert cli.main(["report-m2"]) == 0
    assert (tmp_path / "reports" / "m1_data_foundation.md").exists()
    assert (tmp_path / "reports" / "m2_cost_model.md").exists()


def test_m1_report_summarizes_print_checks(tmp_path):
    from src.options_research.print_checks import CHECK_COLUMNS, checks_path

    seed_lake(tmp_path)
    checks = pd.DataFrame([{
        "symbol": "META", "session_date": pd.Timestamp("2023-02-01").date(), "ts": pd.Timestamp("2023-02-01T23:15:00Z"),
        "side": "low", "extreme": 153.12, "reference": 182.99, "band": 5.49, "decision": "isolated", "n_trades": 151,
        "n_outliers": 1, "outlier_prices": [153.12], "outlier_exchanges": ["D"], "outlier_conditions": ["@,T"], "clean_value": 182.75,
    }], columns=CHECK_COLUMNS)
    checks_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    checks.to_parquet(checks_path(tmp_path), index=False)
    text = m1_report(root=tmp_path)
    section = text.split("## Print checks (trade-level confirmation)")[1].split("## Splits")[0]
    assert "isolated" in section and "2023" in section


def test_cli_requires_a_command():
    import pytest
    with pytest.raises(SystemExit):
        cli.main([])


def test_m3_report_sections():
    from src.options_research.reports import m3_report

    evaluation = pd.DataFrame([
        {"setup": "ORB15", "direction": "long", "n": 400, "mean_ret_60": 0.0012, "se": 0.0003, "t": 4.0, "positive_years": 5, "pooled_break_even": 0.0006, "cost_ratio": 2.0, "pass_t": True, "pass_years": True, "pass_cost": True, "pass_n": True, "passed": True},
        {"setup": "MEANREV", "direction": "short", "n": 120, "mean_ret_60": -0.0001, "se": 0.0004, "t": -0.25, "positive_years": 2, "pooled_break_even": 0.0006, "cost_ratio": -0.17, "pass_t": False, "pass_years": False, "pass_cost": False, "pass_n": False, "passed": False},
        {"setup": "SQUEEZE", "direction": "long", "n": 3247, "mean_ret_60": 0.000438, "se": 0.0001, "t": 2.99, "positive_years": 5, "pooled_break_even": 0.000454, "cost_ratio": 0.97, "pass_t": True, "pass_years": True, "pass_cost": False, "pass_n": True, "passed": False},
    ])
    horizons = pd.DataFrame([{"setup": "ORB15", "direction": "long", "n": 400, "mean_ret_30": 0.001, "mean_ret_60": 0.0012, "mean_ret_hard": 0.002, "median_mfe_60": 0.004, "median_mae_60": -0.002}])
    events = pd.DataFrame([{"setup": "ORB15", "direction": "long", "n_all": 400, "mean_all": 0.0012, "t_all": 4.0, "n_ex_event": 300, "mean_ex_event": 0.0011, "t_ex_event": 3.5}])
    means = pd.DataFrame({"SPY": [12.0]}, index=pd.MultiIndex.from_tuples([("ORB15", "long")], names=["setup", "direction"]))
    break_even = pd.Series({"SPY": 6.0}, name="be_frac")
    ledger = pd.DataFrame([{"stage": "stage1", "config_hash": f"h{i}", "dataset_version": "d1"} for i in range(18)])
    summary = {"signals": 520, "ledger entries recorded for this configuration set": 18, "ledger entries appended this run": 0}
    text = m3_report(evaluation, horizons, events, means, break_even, summary, ledger)
    for heading in ("# M3 Stage-1 Report", "## Pass/fail", "## Criteria", "## Horizons", "## With and without event days", "## Mean +60 min return by ticker (bps)", "## Break-even move by ticker (bps, median)", "## Multiple-testing ledger"):
        assert heading in text
    assert "Passing setup x direction pairs: 1 of 3: ORB15 long" in text
    by_ticker = text.split("## Mean +60 min return by ticker (bps)")[1].split("##")[0]
    assert "SPY" in by_ticker and "12" in by_ticker
    assert "Expected false passes under the null (one-sided p at t = 3): 0.024" in text
    assert "ledger entries recorded for this configuration set: 18" in text
    assert "ledger entries appended this run: 0" in text
    pass_fail = text.split("## Pass/fail")[1].split("##")[0]
    assert "notes" in pass_fail
    meanrev_row = [line for line in pass_fail.splitlines() if "MEANREV" in line][0]
    assert "insufficient signals (untestable)" in meanrev_row
    squeeze_row = [line for line in pass_fail.splitlines() if "SQUEEZE" in line][0]
    assert "t within Monte Carlo noise of 3.0" in squeeze_row and "binding: cost" in squeeze_row
    orb_row = [line for line in pass_fail.splitlines() if "ORB15" in line][0]
    assert "insufficient" not in orb_row and "binding" not in orb_row
    assert "Monte Carlo error is about ±0.02" in text


def test_stage1_cli_passes_symbols_workers_and_overwrite(monkeypatch, capsys):
    import src.options_research.stage1 as stage1
    from src.options_research.cli import main

    calls = []
    monkeypatch.setattr(stage1, "run_stage1", lambda symbols, workers, overwrite: calls.append((symbols, workers, overwrite)) or {"computed": symbols, "skipped": [], "signals": 0})
    assert main(["stage1", "--symbols", "SPY,QQQ", "--workers", "1", "--overwrite"]) == 0
    assert calls == [(["SPY", "QQQ"], 1, True)]
    assert '"signals": 0' in capsys.readouterr().out
