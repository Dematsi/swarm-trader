"""Fix 5: the LLM-written autoresearch strategy must not be loaded by default."""

import argparse
import sys

import pytest

import run_hedge_fund


class _StopAfterParse(Exception):
    pass


def _parse(monkeypatch, argv):
    captured = {}
    original = argparse.ArgumentParser.parse_args

    def capture(self, *args, **kwargs):
        captured["args"] = original(self, *args, **kwargs)
        raise _StopAfterParse

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", capture)
    monkeypatch.setattr(sys, "argv", ["run_hedge_fund.py", *argv])
    with pytest.raises(_StopAfterParse):
        run_hedge_fund.main()
    return captured["args"]


def test_autoresearch_not_in_default_analysts(monkeypatch):
    args = _parse(monkeypatch, [])
    analysts = [a.strip() for a in args.analysts.split(",")]
    assert "autoresearch" not in analysts
    assert analysts  # still has a sensible default set


def test_autoresearch_still_selectable_explicitly(monkeypatch):
    from src.utils.analysts import ANALYST_CONFIG

    assert "autoresearch" in ANALYST_CONFIG
    args = _parse(monkeypatch, ["--analysts", "autoresearch,technical_analyst"])
    assert args.analysts.split(",") == ["autoresearch", "technical_analyst"]
