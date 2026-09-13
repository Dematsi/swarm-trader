import re
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from src.options_research.ledger import (
    append_entries,
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


def test_stage1_entries_hash_setup_and_evaluation_parameters():
    evaluation = pd.DataFrame([{"setup": "ORB15", "direction": "long", "n": 350, "mean_ret_60": 0.001, "t": 3.2, "passed": True}])
    now = datetime(2026, 9, 13, tzinfo=timezone.utc)
    [row] = stage1_entries(evaluation, {"ORB15": {"x": 1}}, {"t_min": 3.0}, "abc", "d1", "2021-06-18..2025-12-31", now)
    assert row["config_hash"] == config_hash({"setup": "ORB15", "direction": "long", "setup_params": {"x": 1}, "evaluation": {"t_min": 3.0}})
    assert row["stage"] == "stage1" and row["timestamp"] == now.isoformat() and row["passed"] is True and row["n"] == 350
