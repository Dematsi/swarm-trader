"""Security regressions for autoresearch/evolve.py.

The spawned `claude` agent must not get an unrestricted shell or the trading/LLM
secrets, and the backtest subprocess (which executes agent-written strategy code)
must only get the Alpaca data keys. Nothing here launches a real subprocess.
"""

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

SECRETS = {
    "ALPACA_API_KEY": "alpaca-key",
    "ALPACA_API_SECRET": "alpaca-secret",
    "ALPACA_DAY_API_KEY": "alpaca-day-key",
    "ALPACA_DAY_API_SECRET": "alpaca-day-secret",
    "OPENAI_API_KEY": "openai",
    "GROQ_API_KEY": "groq",
    "DEEPSEEK_API_KEY": "deepseek",
    "GOOGLE_API_KEY": "google",
    "OPENROUTER_API_KEY": "openrouter",
    "FINANCIAL_DATASETS_API_KEY": "fd",
    "PEER_A2A_TOKEN": "peer",
    "OPTIONS_DB_URL": "postgresql://user:pw@localhost/db",
    "AWS_SECRET_ACCESS_KEY": "aws",
    "GITHUB_TOKEN": "gh",
}

BASE = {
    "PATH": "/usr/bin",
    "SYSTEMROOT": "C:\\Windows",
    "HOME": "/home/me",
    "USERPROFILE": "C:\\Users\\me",
    "APPDATA": "C:\\Users\\me\\AppData\\Roaming",
    "LOCALAPPDATA": "C:\\Users\\me\\AppData\\Local",
    "TEMP": "C:\\Temp",
    "TMP": "C:\\Temp",
    "CLAUDECODE": "1",
}


@pytest.fixture(scope="module")
def evolve():
    spec = importlib.util.spec_from_file_location("evolve_under_test", REPO_ROOT / "autoresearch" / "evolve.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_env():
    return {**BASE, **SECRETS, "ANTHROPIC_API_KEY": "anthropic"}


# ---------------------------------------------------------------------------
# Agent environment
# ---------------------------------------------------------------------------

def test_agent_env_excludes_all_non_anthropic_secrets(evolve):
    env = evolve.build_agent_env(_source_env())
    for key in SECRETS:
        assert key not in env, f"{key} leaked to the claude agent"
    assert "CLAUDECODE" not in env


def test_agent_env_keeps_what_claude_needs(evolve):
    env = evolve.build_agent_env(_source_env())
    for key in BASE:
        if key != "CLAUDECODE":
            assert env[key] == BASE[key]
    assert env["ANTHROPIC_API_KEY"] == "anthropic"


def test_agent_env_is_allowlist_not_denylist(evolve):
    env = evolve.build_agent_env({**_source_env(), "SOME_NEW_SECRET": "x", "MY_PASSWORD": "y"})
    assert "SOME_NEW_SECRET" not in env
    assert "MY_PASSWORD" not in env


def test_agent_env_matches_windows_mixed_case_names(evolve):
    env = evolve.build_agent_env({"Path": "C:\\bin", "SystemRoot": "C:\\Windows", "OPENAI_API_KEY": "x"})
    assert env == {"Path": "C:\\bin", "SystemRoot": "C:\\Windows"}


# ---------------------------------------------------------------------------
# Backtest environment
# ---------------------------------------------------------------------------

def test_backtest_env_has_only_alpaca_data_keys(evolve):
    env = evolve.build_backtest_env(_source_env())
    assert env["ALPACA_API_KEY"] == "alpaca-key"
    assert env["ALPACA_API_SECRET"] == "alpaca-secret"
    assert env["PATH"] == "/usr/bin"
    for key in SECRETS:
        if key not in ("ALPACA_API_KEY", "ALPACA_API_SECRET"):
            assert key not in env, f"{key} leaked to the backtest subprocess"
    assert "ANTHROPIC_API_KEY" not in env


# ---------------------------------------------------------------------------
# Agent command / tool permissions
# ---------------------------------------------------------------------------

def _flag_values(cmd, flag):
    values = []
    for i, arg in enumerate(cmd):
        if arg == flag:
            values.append(cmd[i + 1])
    return values


def _run_claude_capturing(evolve, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(evolve.subprocess, "run", fake_run)
    for key, value in _source_env().items():
        monkeypatch.setenv(key, value)
    ok, _ = evolve._run_agent_claude("do the thing", quiet=True)
    assert ok
    return captured


def test_agent_has_no_shell(evolve, monkeypatch):
    captured = _run_claude_capturing(evolve, monkeypatch)
    cmd = captured["cmd"]
    tools = _flag_values(cmd, "--tools")
    assert tools, "built-in tool set must be restricted with --tools"
    assert all("Bash" not in t for t in tools)
    for allowed in _flag_values(cmd, "--allowedTools"):
        for rule in allowed.replace(",", " ").split():
            assert not rule.startswith("Bash"), f"shell allowed via {rule}"
            assert rule not in ("Edit", "Write"), f"unscoped write tool {rule}"


def test_agent_edits_are_scoped_to_strategy(evolve, monkeypatch):
    cmd = _run_claude_capturing(evolve, monkeypatch)["cmd"]
    allowed = " ".join(_flag_values(cmd, "--allowedTools"))
    assert "Edit(./autoresearch/strategy.py)" in allowed
    # Anything not explicitly allowed is denied rather than prompted for.
    assert _flag_values(cmd, "--permission-mode") == ["dontAsk"]


def test_agent_cannot_read_dotenv(evolve, monkeypatch):
    cmd = _run_claude_capturing(evolve, monkeypatch)["cmd"]
    denied = " ".join(_flag_values(cmd, "--disallowedTools"))
    assert "Read(./.env)" in denied


def test_agent_subprocess_gets_filtered_env(evolve, monkeypatch):
    env = _run_claude_capturing(evolve, monkeypatch)["kwargs"]["env"]
    for key in SECRETS:
        assert key not in env
    assert "CLAUDECODE" not in env


def test_backtest_subprocess_gets_filtered_env(evolve, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return SimpleNamespace(returncode=0, stdout='{"fitness_score": 1.0}', stderr="")

    monkeypatch.setattr(evolve.subprocess, "run", fake_run)
    for key, value in _source_env().items():
        monkeypatch.setenv(key, value)
    ok, _ = evolve._run_backtest(5, 10000, quiet=True)
    assert ok
    env = captured["env"]
    assert env is not None, "backtest must not inherit the full parent environment"
    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "PEER_A2A_TOKEN" not in env
    assert env["ALPACA_API_KEY"] == "alpaca-key"
