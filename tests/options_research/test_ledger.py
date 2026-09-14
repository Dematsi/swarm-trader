import re
import subprocess
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from src.options_research.ledger import (
    append_entries,
    code_version,
    config_hash,
    dataset_version,
    expected_false_passes,
    git_commit,
    read_ledger,
    stage1_entries,
)


def test_config_hash_is_order_independent():
    assert config_hash({"a": 1, "b": [1, 2]}) == config_hash({"b": [1, 2], "a": 1})
    assert config_hash({"a": 1}) != config_hash({"a": 2})


def entry(dataset="d1", setup="ORB15"):
    return {"stage": "stage1", "setup": setup, "direction": "long", "config_hash": "h1", "dataset_version": dataset, "n": 1}


def test_append_entries_skips_repeats_of_the_same_configuration(tmp_path):
    path = tmp_path / "ledger.jsonl"
    assert append_entries([entry(), entry(setup="ORB30")], path) == 2
    assert append_entries([entry(), entry(setup="ORB30")], path) == 0
    assert append_entries([entry(dataset="d2")], path) == 1
    assert len(read_ledger(path)) == 3
    assert read_ledger(tmp_path / "missing.jsonl").empty


def test_expected_false_passes():
    assert expected_false_passes(18) == pytest.approx(18 * 0.00135)


def test_dataset_version_tracks_lake_inputs(tmp_path):
    day_file = tmp_path / "stock_1m" / "SPY" / "2024" / "2024-01-02.parquet"
    day_file.parent.mkdir(parents=True)
    day_file.write_bytes(b"abc")
    (tmp_path / "calendar").mkdir()
    (tmp_path / "calendar" / "events.parquet").write_bytes(b"v1")
    first = dataset_version(date(2024, 1, 2), date(2024, 1, 2), root=tmp_path, symbols=["SPY"])
    assert first == dataset_version(date(2024, 1, 2), date(2024, 1, 2), root=tmp_path, symbols=["SPY"])
    (tmp_path / "calendar" / "events.parquet").write_bytes(b"v2")
    assert dataset_version(date(2024, 1, 2), date(2024, 1, 2), root=tmp_path, symbols=["SPY"]) != first


def test_dataset_version_changes_when_a_day_file_changes_with_the_same_size(tmp_path):
    day_file = tmp_path / "stock_1m" / "SPY" / "2024" / "2024-01-02.parquet"
    day_file.parent.mkdir(parents=True)
    (tmp_path / "calendar").mkdir()
    (tmp_path / "calendar" / "events.parquet").write_bytes(b"v1")
    day_file.write_bytes(b"abc")
    first = dataset_version(date(2024, 1, 2), date(2024, 1, 2), root=tmp_path, symbols=["SPY"])
    day_file.write_bytes(b"abd")
    second = dataset_version(date(2024, 1, 2), date(2024, 1, 2), root=tmp_path, symbols=["SPY"])
    assert first != second
    day_file.write_bytes(b"abc")
    third = dataset_version(date(2024, 1, 2), date(2024, 1, 2), root=tmp_path, symbols=["SPY"])
    assert third == first


def test_git_commit_is_a_sha():
    assert re.fullmatch(r"[0-9a-f]{40}(-dirty)?", git_commit())


def test_git_commit_dirty_check_excludes_generated_reports(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        stdout = ("a" * 40 + "\n") if cmd[:2] == ["git", "rev-parse"] else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    import src.options_research.ledger as ledger_module

    monkeypatch.setattr(ledger_module.subprocess, "run", fake_run)
    assert git_commit() == "a" * 40
    status_calls = [c for c in calls if c[:2] == ["git", "status"]]
    assert len(status_calls) == 1
    assert ":(exclude)reports/options_research" in status_calls[0]


def test_dataset_version_includes_extra_ranges(tmp_path):
    dev = tmp_path / "stock_1m" / "SPY" / "2024" / "2024-01-02.parquet"
    dev.parent.mkdir(parents=True)
    dev.write_bytes(b"dev")
    calibration = tmp_path / "stock_1m" / "SPY" / "2026" / "2026-08-21.parquet"
    calibration.parent.mkdir(parents=True)
    calibration.write_bytes(b"cal-v1")
    (tmp_path / "calendar").mkdir()
    (tmp_path / "calendar" / "events.parquet").write_bytes(b"v1")
    extra_ranges = ((date(2026, 8, 21), date(2026, 8, 21)),)
    first = dataset_version(date(2024, 1, 2), date(2024, 1, 2), root=tmp_path, symbols=["SPY"], extra_ranges=extra_ranges)
    assert first == dataset_version(date(2024, 1, 2), date(2024, 1, 2), root=tmp_path, symbols=["SPY"], extra_ranges=extra_ranges)
    # Without the extra range, the calibration file's content isn't tracked.
    assert first != dataset_version(date(2024, 1, 2), date(2024, 1, 2), root=tmp_path, symbols=["SPY"])
    calibration.write_bytes(b"cal-v2")
    assert dataset_version(date(2024, 1, 2), date(2024, 1, 2), root=tmp_path, symbols=["SPY"], extra_ranges=extra_ranges) != first


def test_code_version_changes_when_a_tracked_file_changes(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "setups").mkdir(parents=True)
    for name in ("features.py", "levels.py", "stage1.py", "evaluate.py"):
        (pkg / name).write_text("x = 1")
    (pkg / "setups" / "orb.py").write_text("y = 1")
    (pkg / "setups" / "__init__.py").write_text("")
    first = code_version(pkg)
    assert first == code_version(pkg)
    (pkg / "levels.py").write_text("x = 2")
    second = code_version(pkg)
    assert second != first
    (pkg / "setups" / "orb.py").write_text("y = 2")
    third = code_version(pkg)
    assert third != second


def test_code_version_ignores_untracked_files(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "setups").mkdir(parents=True)
    for name in ("features.py", "levels.py", "stage1.py", "evaluate.py"):
        (pkg / name).write_text("x = 1")
    (pkg / "setups" / "orb.py").write_text("y = 1")
    before = code_version(pkg)
    (pkg / "config.py").write_text("z = 1")  # not a tracked file
    assert code_version(pkg) == before


def test_stage1_entries_hash_setup_and_evaluation_parameters():
    evaluation = pd.DataFrame([{
        "setup": "ORB15", "direction": "long", "n": 350, "mean_ret_60": 0.001, "t": 3.2,
        "positive_years": 5, "pooled_break_even": 0.0006, "cost_ratio": 1.7,
        "pass_n": True, "pass_t": True, "pass_years": True, "pass_cost": True, "passed": True,
    }])
    now = datetime(2026, 9, 13, tzinfo=timezone.utc)
    [row] = stage1_entries(evaluation, {"ORB15": {"x": 1}}, {"t_min": 3.0}, "abc", "d1", "2021-06-18..2025-12-31", now, shared_params={"y": 2}, code="code1")
    assert row["config_hash"] == config_hash({
        "setup": "ORB15", "direction": "long", "setup_params": {"x": 1}, "shared_params": {"y": 2}, "evaluation": {"t_min": 3.0}, "code_version": "code1",
    })
    assert row["stage"] == "stage1" and row["timestamp"] == now.isoformat() and row["passed"] is True and row["n"] == 350


def test_config_hash_changes_with_shared_params_or_code_version():
    base = {"setup": "ORB15", "direction": "long", "setup_params": {}, "shared_params": {"a": 1}, "evaluation": {}, "code_version": "c1"}
    assert config_hash(base) != config_hash({**base, "shared_params": {"a": 2}})
    assert config_hash(base) != config_hash({**base, "code_version": "c2"})


def test_stage1_entries_carries_the_new_fields():
    evaluation = pd.DataFrame([{
        "setup": "SQUEEZE", "direction": "long", "n": 3247, "mean_ret_60": 0.000438, "t": 2.99,
        "positive_years": 5, "pooled_break_even": 0.000454, "cost_ratio": 0.97,
        "pass_n": True, "pass_t": False, "pass_years": True, "pass_cost": False, "passed": False,
    }])
    [row] = stage1_entries(evaluation, {"SQUEEZE": {"x": 1}}, {}, "abc", "d1", "period", shared_params={"s": 1}, code="code1")
    assert row["schema"] == 2
    assert row["code_version"] == "code1"
    assert row["positive_years"] == 5
    assert row["pooled_break_even"] == pytest.approx(0.000454)
    assert row["cost_ratio"] == pytest.approx(0.97)
    assert row["pass_n"] is True and row["pass_t"] is False and row["pass_years"] is True and row["pass_cost"] is False


def test_stage1_entries_nan_values_become_null():
    evaluation = pd.DataFrame([{
        "setup": "MEANREV", "direction": "short", "n": 45, "mean_ret_60": -0.0046, "t": float("nan"),
        "positive_years": 2, "pooled_break_even": float("nan"), "cost_ratio": float("nan"),
        "pass_n": False, "pass_t": False, "pass_years": False, "pass_cost": False, "passed": False,
    }])
    [row] = stage1_entries(evaluation, {"MEANREV": {}}, {}, "abc", "d1", "period")
    assert row["t"] is None and row["pooled_break_even"] is None and row["cost_ratio"] is None
