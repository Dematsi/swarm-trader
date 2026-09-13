from datetime import date
from pathlib import Path

from src.options_research import config


def test_universe_is_the_twelve_spec_tickers():
    assert config.UNIVERSE == ("SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL", "AMZN", "MSFT", "GOOGL", "META", "AMD", "NFLX")
    assert config.ETFS == frozenset({"SPY", "QQQ", "IWM"})


def test_periods_do_not_overlap_holdout():
    assert config.STAGE1_DEV == (date(2021, 6, 18), date(2025, 12, 31))
    assert config.STAGE2_DEV == (date(2024, 1, 2), date(2025, 12, 31))
    assert config.HOLDOUT == (date(2026, 1, 2), date(2026, 9, 11))
    assert config.STAGE1_DEV[1] < config.HOLDOUT[0]
    assert config.STAGE2_DEV[1] < config.HOLDOUT[0]
    assert config.ZIP_START == date(2021, 6, 18) and config.ZIP_END == date(2026, 6, 18)


def test_paths_are_env_overridable(monkeypatch, tmp_path):
    monkeypatch.setenv("OPTIONS_LAKE_ROOT", str(tmp_path / "lake"))
    monkeypatch.setenv("OPTIONS_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("OPTIONS_EQUITY_ZIP", str(tmp_path / "eq.zip"))
    assert config.lake_root() == tmp_path / "lake"
    assert config.reports_dir() == tmp_path / "reports"
    assert config.equity_zip_path() == tmp_path / "eq.zip"


def test_default_lake_is_under_gitignored_data(monkeypatch):
    monkeypatch.delenv("OPTIONS_LAKE_ROOT", raising=False)
    assert config.lake_root() == config.REPO_ROOT / "data" / "options_lake"
    assert (config.REPO_ROOT / "pyproject.toml").exists()
    assert isinstance(config.REPO_ROOT, Path)
