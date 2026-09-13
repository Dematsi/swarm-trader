# Options Research M1+M2 (Data Foundation & Cost Model) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the tested data foundation for the intraday options edge study:
- 1-minute stock bars for 12 tickers (2021-06-18 → 2026-09-11), with bad prints flagged and
  splits detected
- an NYSE session calendar with entry/exit cutoffs
- an economic/earnings events table
- a read-only Alpaca data client
- a Schwab-calibrated option half-spread cost model
- M1/M2 validation reports

**Architecture:**
- **Package:** everything lives in a new, self-contained package `src/options_research/` that
  never imports the repo's trading code.
- **Storage:** raw inputs are the user's Polygon/Massive equity zip, Alpaca read-only data
  endpoints, FRED and yfinance. They are normalized into a local Parquet lake under
  `data/options_lake/` (gitignored) and read back through DuckDB.
- **Schwab quotes:** come from the sibling bot's Postgres, read-only.
- **Tests and reports:** modules are small and tested offline with synthetic fixtures. A final
  task runs the real pipeline and commits aggregate Markdown reports.

**Tech Stack:** Python 3.12 via uv; pandas 2.3, numpy 1.26, httpx, psycopg 3, yfinance 1.7
(already installed). New: `duckdb`, `pyarrow`, `exchange-calendars` (4.13.x).

**Spec:** `docs/superpowers/specs/2026-09-12-options-edge-research-design.md` (read §2, §3, §5,
§9.1 and §10 before starting). This plan covers spec milestones **M1** and **M2** only. M3–M6 get
their own plans after the stage-1 checkpoint.

## Global Constraints

- **Tooling:** run everything from the repo root `C:\Users\tsedi\swarm-trader-fork` with `uv`
  (at `~/.local/bin/uv` if it isn't on PATH). The shell is Git Bash. If output contains non-ASCII
  characters, prefix commands with `PYTHONIOENCODING=utf-8`.
- **Isolation:** `src/options_research/` must NOT import from root scripts, `src/agents`,
  `src/alpaca_integration.py` or `src/accounts.py`.
- **Alpaca access:** only through `src/options_research/alpaca_data.py`.
  - GET only.
  - Allowlist exactly `data.alpaca.markets` `/v1beta1/options/bars`, `/v1beta1/options/trades`,
    `/v2/stocks/bars` and `api.alpaca.markets` `/v2/options/contracts`.
  - Keys come only from `ALPACA_DATA_API_KEY` / `ALPACA_DATA_SECRET_KEY` (live-host keys). Never
    read `ALPACA_API_KEY`.
  - Client-side rate limit of 180 requests/min.
- **Sibling Postgres:** only via `OPTIONS_DB_URL`, which already forces read-only sessions.
- **No vendor data committed.** Lake data lives under `data/` (already gitignored). Reports under
  `reports/options_research/` hold aggregates only and are committed.
- **Time conventions:** all timestamps are tz-aware UTC in storage. A bar `ts` is the bar
  **start**. Time windows are start-inclusive, end-exclusive. Convert to `America/New_York` for
  any time-of-day logic.
- **Dates:** zip coverage 2021-06-18 → 2026-06-18; data freeze 2026-09-11; stage-1 dev
  2021-06-18 → 2025-12-31; stage-2 dev 2024-01-02 → 2025-12-31; holdout 2026-01-02 → 2026-09-11.
- **Holdout guard:** loaders refuse ranges touching 2026-01-02 or later unless `holdout=True`.
  Allowed `holdout=True` call sites are only data validation, split detection and cost calibration,
  each with a comment naming the exception.
- **Universe:** `SPY QQQ IWM NVDA TSLA AAPL AMZN MSFT GOOGL META AMD NFLX`.
- **Tests:** TDD. Unit tests are offline. Tests needing the zip, the sibling DB, Alpaca or the
  network are marked `@pytest.mark.integration` and excluded by default.
- **Commits:** every commit message ends with exactly these two lines, after a blank line:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
  ```
- Work on branch `local-setup`. Do not push unless the user asks.

## File Structure

| File | Responsibility |
|---|---|
| `src/options_research/__init__.py` | Package marker |
| `src/options_research/config.py` | Universe, study periods, path resolution (env-overridable) |
| `src/options_research/alpaca_data.py` | Read-only allowlisted Alpaca client, rate limiter, pagination |
| `src/options_research/market_calendar.py` | NYSE sessions, half-days, entry/exit cutoffs |
| `src/options_research/events_rules.py` | Rule-computed events (OPEX, witching, VIX exp, month/quarter end, ISM, Conference Board, Russell) + FOMC from CSV |
| `src/options_research/data/fomc_meetings.csv` | Scheduled FOMC meetings 2021–2026 (from federalreserve.gov) |
| `src/options_research/events_sources.py` | FRED release dates, yfinance earnings, `build_events`, `write_events` |
| `src/options_research/quality.py` | Trailing-window bad-print flags and clipped highs/lows |
| `src/options_research/stocks.py` | Zip minute ingest, normalization, day-file writer |
| `src/options_research/stocks_alpaca.py` | Alpaca SIP 1-min tail ingest and zip-vs-Alpaca comparison |
| `src/options_research/corporate_actions.py` | RTH daily summary, split detection, adjustment factors |
| `src/options_research/store.py` | Holdout guard and DuckDB loaders for the lake |
| `src/options_research/costs.py` | Bucket functions, Schwab SQL, `CostModel`, spread scaling, realized vol |
| `src/options_research/reports.py` | M1 and M2 Markdown reports |
| `src/options_research/cli.py`, `__main__.py` | `uv run python -m src.options_research <command>` |
| `tests/options_research/...` | One test module per source module + `test_integration_data.py` |

---

### Task 1: Package skeleton, config, dependencies, pytest markers

**Files:**
- Create: `src/options_research/__init__.py`
- Create: `src/options_research/config.py`
- Create: `tests/options_research/__init__.py`
- Create: `tests/options_research/test_config.py`
- Modify: `pyproject.toml` (dependencies via `uv add`; `[tool.pytest.ini_options]` table)

**Interfaces:**
- Produces:
  - constants `UNIVERSE: tuple[str, ...]`, `ETFS: frozenset[str]`, `TZ_ET: str`
  - dates `ZIP_START`, `ZIP_END`, `DATA_FREEZE` (`date`)
  - periods `STAGE1_DEV`, `STAGE2_DEV`, `HOLDOUT` (`tuple[date, date]`)
  - `REPO_ROOT: Path`
  - `lake_root() -> Path`, `reports_dir() -> Path`, `equity_zip_path() -> Path`

- [ ] **Step 1: Add dependencies**

Run: `uv add duckdb pyarrow "exchange-calendars>=4.13,<5"`
Expected: `pyproject.toml` and `uv.lock` updated; output lists `+ duckdb`, `+ pyarrow`, `+ exchange-calendars`.

- [ ] **Step 2: Add pytest marker config**

In `pyproject.toml`, keep the existing `[tool.pytest.ini_options]` keys (`pythonpath`, `testpaths`)
and add these two keys to the same table:

```toml
markers = ["integration: needs the equity zip, the sibling Postgres, Alpaca or the network"]
addopts = "-m \"not integration\""
```

- [ ] **Step 3: Write the failing test**

`tests/options_research/__init__.py`: empty file.

`tests/options_research/test_config.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/options_research/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.options_research'`

- [ ] **Step 5: Write minimal implementation**

`src/options_research/__init__.py`:

```python
"""Intraday single-leg options edge research (docs/superpowers/specs/2026-09-12-options-edge-research-design.md)."""
```

`src/options_research/config.py`:

```python
"""Universe, study periods and paths for the options edge research (spec §1, §9.1)."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

UNIVERSE: tuple[str, ...] = ("SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL", "AMZN", "MSFT", "GOOGL", "META", "AMD", "NFLX")
ETFS: frozenset[str] = frozenset({"SPY", "QQQ", "IWM"})
TZ_ET = "America/New_York"

ZIP_START = date(2021, 6, 18)
ZIP_END = date(2026, 6, 18)
DATA_FREEZE = date(2026, 9, 11)
STAGE1_DEV = (date(2021, 6, 18), date(2025, 12, 31))
STAGE2_DEV = (date(2024, 1, 2), date(2025, 12, 31))
HOLDOUT = (date(2026, 1, 2), DATA_FREEZE)


def lake_root() -> Path:
    return Path(os.environ.get("OPTIONS_LAKE_ROOT", REPO_ROOT / "data" / "options_lake"))


def reports_dir() -> Path:
    return Path(os.environ.get("OPTIONS_REPORTS_DIR", REPO_ROOT / "reports" / "options_research"))


def equity_zip_path() -> Path:
    return Path(os.environ.get("OPTIONS_EQUITY_ZIP", r"C:\Users\tsedi\Downloads\equity-data.zip"))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/options_research/test_config.py -v`
Expected: 4 passed

Run: `uv run pytest -q`
Expected: all existing tests still pass (97 passed at plan time)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/options_research/__init__.py src/options_research/config.py tests/options_research/__init__.py tests/options_research/test_config.py
git commit -F- <<'EOF'
feat(options_research): package skeleton, config and data dependencies

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 2: Read-only Alpaca data client

**Files:**
- Create: `src/options_research/alpaca_data.py`
- Test: `tests/options_research/test_alpaca_data.py`

**Interfaces:**
- Produces:
  - `ALLOWED_ENDPOINTS: frozenset[tuple[str, str]]`
  - `DisallowedEndpointError(ValueError)`
  - `check_allowed(url: str) -> None`
  - `RateLimiter(max_per_minute: int = 180, clock=time.monotonic, sleep=time.sleep)` with `.acquire() -> None`
  - `AlpacaDataClient(key=None, secret=None, http: httpx.Client | None = None, limiter: RateLimiter | None = None, max_retries: int = 5, sleep=time.sleep)` with:
    - `.get(url: str, params: dict) -> dict`
    - `.paginate(url: str, params: dict) -> Iterator[dict]`, which follows `next_page_token` by setting `page_token`

- [ ] **Step 1: Write the failing test**

`tests/options_research/test_alpaca_data.py`:

```python
import httpx
import pytest

from src.options_research.alpaca_data import (
    ALLOWED_ENDPOINTS,
    AlpacaDataClient,
    DisallowedEndpointError,
    RateLimiter,
    check_allowed,
)

BARS = "https://data.alpaca.markets/v1beta1/options/bars"


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def make_client(handler, **kwargs):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    clock = FakeClock()
    limiter = RateLimiter(1000, clock=clock.now, sleep=clock.sleep)
    return AlpacaDataClient(key="data-key", secret="data-secret", http=http, limiter=limiter, sleep=clock.sleep, **kwargs), clock


def test_allowlist_is_exactly_the_spec_endpoints():
    assert ALLOWED_ENDPOINTS == frozenset({
        ("data.alpaca.markets", "/v1beta1/options/bars"),
        ("data.alpaca.markets", "/v1beta1/options/trades"),
        ("data.alpaca.markets", "/v2/stocks/bars"),
        ("api.alpaca.markets", "/v2/options/contracts"),
    })


@pytest.mark.parametrize("url", [
    "https://api.alpaca.markets/v2/orders",
    "https://paper-api.alpaca.markets/v2/options/contracts",
    "http://data.alpaca.markets/v1beta1/options/bars",
    "https://data.alpaca.markets/v2/stocks/trades",
])
def test_rejects_non_allowlisted_urls_without_calling_http(url):
    calls = []
    client, _ = make_client(lambda request: calls.append(request) or httpx.Response(200, json={}))
    with pytest.raises(DisallowedEndpointError):
        client.get(url, {})
    assert calls == []
    with pytest.raises(DisallowedEndpointError):
        check_allowed(url)


def test_client_has_no_order_capable_methods():
    for name in ("post", "put", "patch", "delete", "submit_order", "place_order"):
        assert not hasattr(AlpacaDataClient, name)


def test_requires_data_keys_and_ignores_trading_keys(monkeypatch):
    monkeypatch.delenv("ALPACA_DATA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_DATA_SECRET_KEY", raising=False)
    monkeypatch.setenv("ALPACA_API_KEY", "trading-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "trading-secret")
    with pytest.raises(RuntimeError, match="ALPACA_DATA_API_KEY"):
        AlpacaDataClient()


def test_sends_get_with_data_key_headers():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"bars": {}})

    client, _ = make_client(handler)
    assert client.get(BARS, {"symbols": "SPY250611C00604000"}) == {"bars": {}}
    assert seen[0].method == "GET"
    assert seen[0].headers["APCA-API-KEY-ID"] == "data-key"
    assert seen[0].headers["APCA-API-SECRET-KEY"] == "data-secret"
    assert seen[0].url.params["symbols"] == "SPY250611C00604000"


def test_retries_429_with_backoff_then_succeeds():
    responses = iter([httpx.Response(429), httpx.Response(503), httpx.Response(200, json={"ok": True})])
    client, clock = make_client(lambda request: next(responses))
    assert client.get(BARS, {}) == {"ok": True}
    assert clock.sleeps == [1.0, 2.0]


def test_gives_up_after_max_retries():
    client, _ = make_client(lambda request: httpx.Response(429), max_retries=2)
    with pytest.raises(httpx.HTTPStatusError):
        client.get(BARS, {})


def test_non_retryable_error_raises_immediately():
    calls = []
    client, _ = make_client(lambda request: calls.append(1) or httpx.Response(403))
    with pytest.raises(httpx.HTTPStatusError):
        client.get(BARS, {})
    assert len(calls) == 1


def test_paginate_follows_next_page_token():
    def handler(request):
        token = request.url.params.get("page_token")
        if token is None:
            return httpx.Response(200, json={"bars": {"A": [1]}, "next_page_token": "t2"})
        assert token == "t2"
        return httpx.Response(200, json={"bars": {"A": [2]}, "next_page_token": None})

    client, _ = make_client(handler)
    pages = list(client.paginate(BARS, {"symbols": "A"}))
    assert [p["bars"]["A"] for p in pages] == [[1], [2]]


def test_rate_limiter_waits_when_window_full():
    clock = FakeClock()
    limiter = RateLimiter(2, clock=clock.now, sleep=clock.sleep)
    limiter.acquire()
    limiter.acquire()
    clock.t = 10.0
    limiter.acquire()
    assert clock.sleeps == [50.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/options_research/test_alpaca_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.options_research.alpaca_data'`

- [ ] **Step 3: Write minimal implementation**

`src/options_research/alpaca_data.py`:

```python
"""Read-only Alpaca market-data client (spec §2). The ONLY module in this package allowed to call Alpaca.

Uses the ALPACA_DATA_* key pair, which authenticates on the LIVE host, so the endpoint allowlist is a
safety boundary: GET only, four data/listing endpoints only, no method that can send an order.
"""

from __future__ import annotations

import os
import time
from collections import deque
from collections.abc import Callable, Iterator
from urllib.parse import urlsplit

import httpx

ALLOWED_ENDPOINTS: frozenset[tuple[str, str]] = frozenset({
    ("data.alpaca.markets", "/v1beta1/options/bars"),
    ("data.alpaca.markets", "/v1beta1/options/trades"),
    ("data.alpaca.markets", "/v2/stocks/bars"),
    ("api.alpaca.markets", "/v2/options/contracts"),
})
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class DisallowedEndpointError(ValueError):
    """Raised when a URL is not on the read-only allowlist."""


def check_allowed(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname, parts.path) not in ALLOWED_ENDPOINTS:
        raise DisallowedEndpointError(f"endpoint not allowlisted: {url}")


class RateLimiter:
    """Sliding window: at most `max_per_minute` acquisitions in any 60-second window."""

    def __init__(self, max_per_minute: int = 180, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.max_per_minute = max_per_minute
        self._clock = clock
        self._sleep = sleep
        self._stamps: deque[float] = deque()

    def _evict(self, now: float) -> None:
        while self._stamps and now - self._stamps[0] >= 60.0:
            self._stamps.popleft()

    def acquire(self) -> None:
        now = self._clock()
        self._evict(now)
        if len(self._stamps) >= self.max_per_minute:
            self._sleep(60.0 - (now - self._stamps[0]))
            now = self._clock()
            self._evict(now)
        self._stamps.append(now)


class AlpacaDataClient:
    """GET-only client for Alpaca market data and contract listings."""

    def __init__(
        self,
        key: str | None = None,
        secret: str | None = None,
        http: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
        max_retries: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ):
        key = key or os.environ.get("ALPACA_DATA_API_KEY")
        secret = secret or os.environ.get("ALPACA_DATA_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError("ALPACA_DATA_API_KEY and ALPACA_DATA_SECRET_KEY must be set; trading keys are never used")
        self._headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        self._http = http or httpx.Client(timeout=60)
        self._limiter = limiter or RateLimiter()
        self._max_retries = max_retries
        self._sleep = sleep

    def get(self, url: str, params: dict) -> dict:
        check_allowed(url)
        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()
            response = self._http.request("GET", url, params=params, headers=self._headers)
            if response.status_code in RETRY_STATUS and attempt < self._max_retries:
                self._sleep(min(60.0, 2.0 ** attempt))
                continue
            response.raise_for_status()
            return response.json()
        raise AssertionError("retry loop exited without returning or raising")

    def paginate(self, url: str, params: dict) -> Iterator[dict]:
        page_params = dict(params)
        while True:
            page = self.get(url, page_params)
            yield page
            token = page.get("next_page_token")
            if not token:
                return
            page_params["page_token"] = token
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/options_research/test_alpaca_data.py -v`
Expected: 13 passed (the parametrized rejection test counts 4)

- [ ] **Step 5: Commit**

```bash
git add src/options_research/alpaca_data.py tests/options_research/test_alpaca_data.py
git commit -F- <<'EOF'
feat(options_research): read-only allowlisted Alpaca data client

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 3: Market calendar and cutoffs

**Files:**
- Create: `src/options_research/market_calendar.py`
- Test: `tests/options_research/test_market_calendar.py`

**Interfaces:**
- Consumes: `config.TZ_ET`
- Produces:
  - `ET: ZoneInfo`
  - `Session(day: date, open_et: datetime, close_et: datetime)` with `.is_half_day -> bool`
  - `get_session(day: date) -> Session | None`
  - `sessions_between(start: date, end: date) -> list[Session]` (inclusive)
  - `previous_session_on_or_before(day: date) -> date`
  - `next_session_on_or_after(day: date) -> date`
  - `entry_exit_cutoffs(day: date, is_0dte: bool) -> tuple[datetime, datetime]`, returning
    `(last_entry_et, hard_exit_et)`

- [ ] **Step 1: Write the failing test**

`tests/options_research/test_market_calendar.py`:

```python
from datetime import date, datetime, time

import pytest

from src.options_research.market_calendar import (
    ET,
    entry_exit_cutoffs,
    get_session,
    next_session_on_or_after,
    previous_session_on_or_before,
    sessions_between,
)


def test_regular_session_open_close_in_eastern_time():
    s = get_session(date(2025, 6, 11))
    assert s.open_et == datetime(2025, 6, 11, 9, 30, tzinfo=ET)
    assert s.close_et == datetime(2025, 6, 11, 16, 0, tzinfo=ET)
    assert s.is_half_day is False


def test_half_day_close_1300():
    s = get_session(date(2025, 11, 28))
    assert s.close_et.time() == time(13, 0)
    assert s.is_half_day is True


def test_holiday_is_not_a_session():
    assert get_session(date(2025, 12, 25)) is None


@pytest.mark.parametrize("day", [date(2025, 3, 10), date(2025, 11, 3)])
def test_close_is_1600_et_across_dst_changes(day):
    assert get_session(day).close_et.hour == 16


def test_cutoffs_0dte_regular_day():
    last_entry, hard_exit = entry_exit_cutoffs(date(2025, 6, 11), is_0dte=True)
    assert (last_entry.time(), hard_exit.time()) == (time(15, 0), time(15, 25))


def test_cutoffs_other_expiries_regular_day():
    last_entry, hard_exit = entry_exit_cutoffs(date(2025, 6, 11), is_0dte=False)
    assert (last_entry.time(), hard_exit.time()) == (time(15, 15), time(15, 45))


def test_cutoffs_follow_half_day_close():
    last_entry, hard_exit = entry_exit_cutoffs(date(2025, 11, 28), is_0dte=True)
    assert (last_entry.time(), hard_exit.time()) == (time(12, 0), time(12, 25))


def test_cutoffs_reject_non_session():
    with pytest.raises(ValueError):
        entry_exit_cutoffs(date(2025, 12, 25), is_0dte=False)


def test_session_navigation_and_range():
    assert previous_session_on_or_before(date(2025, 12, 25)) == date(2025, 12, 24)
    assert next_session_on_or_after(date(2025, 12, 25)) == date(2025, 12, 26)
    assert [s.day for s in sessions_between(date(2025, 12, 22), date(2025, 12, 29))] == [
        date(2025, 12, 22), date(2025, 12, 23), date(2025, 12, 24), date(2025, 12, 26), date(2025, 12, 29)
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/options_research/test_market_calendar.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.options_research.market_calendar'`

- [ ] **Step 3: Write minimal implementation**

`src/options_research/market_calendar.py`:

```python
"""NYSE sessions, half-days and per-day entry/exit cutoffs (spec §5.2, §7.5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from src.options_research.config import TZ_ET

ET = ZoneInfo(TZ_ET)
_REGULAR_CLOSE = time(16, 0)


@dataclass(frozen=True)
class Session:
    day: date
    open_et: datetime
    close_et: datetime

    @property
    def is_half_day(self) -> bool:
        return self.close_et.time() < _REGULAR_CLOSE


@lru_cache(maxsize=1)
def _schedule() -> pd.DataFrame:
    return xcals.get_calendar("XNYS", start="2021-01-04", end="2026-12-31").schedule


def _to_session(index: pd.Timestamp, row: pd.Series) -> Session:
    return Session(
        day=index.date(),
        open_et=row["open"].tz_convert(ET).to_pydatetime(),
        close_et=row["close"].tz_convert(ET).to_pydatetime(),
    )


def get_session(day: date) -> Session | None:
    key = pd.Timestamp(day)
    schedule = _schedule()
    if key not in schedule.index:
        return None
    return _to_session(key, schedule.loc[key])


def sessions_between(start: date, end: date) -> list[Session]:
    window = _schedule().loc[pd.Timestamp(start):pd.Timestamp(end)]
    return [_to_session(index, row) for index, row in window.iterrows()]


def previous_session_on_or_before(day: date) -> date:
    candidate = day
    for _ in range(10):
        if get_session(candidate) is not None:
            return candidate
        candidate -= timedelta(days=1)
    raise ValueError(f"no session within 10 days on or before {day}")


def next_session_on_or_after(day: date) -> date:
    candidate = day
    for _ in range(10):
        if get_session(candidate) is not None:
            return candidate
        candidate += timedelta(days=1)
    raise ValueError(f"no session within 10 days on or after {day}")


def entry_exit_cutoffs(day: date, is_0dte: bool) -> tuple[datetime, datetime]:
    session = get_session(day)
    if session is None:
        raise ValueError(f"{day} is not a trading session")
    if is_0dte:
        return session.close_et - timedelta(minutes=60), session.close_et - timedelta(minutes=35)
    return session.close_et - timedelta(minutes=45), session.close_et - timedelta(minutes=15)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/options_research/test_market_calendar.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/options_research/market_calendar.py tests/options_research/test_market_calendar.py
git commit -F- <<'EOF'
feat(options_research): NYSE session calendar and 0DTE-aware cutoffs

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 4: Rule-based and FOMC events

**Files:**
- Create: `src/options_research/data/fomc_meetings.csv`
- Create: `src/options_research/events_rules.py`
- Test: `tests/options_research/test_events_rules.py`

**Interfaces:**
- Consumes: `market_calendar.get_session`, `previous_session_on_or_before`,
  `next_session_on_or_after`, `sessions_between`
- Produces:
  - `EVENT_COLUMNS = ["date", "time_et", "type", "tier", "source", "ticker"]`
  - `make_event(day: date, time_et: str | None, type_: str, tier: str, source: str, ticker: str | None = None) -> dict`
  - `third_friday(year: int, month: int) -> date`, `fourth_friday(year: int, month: int) -> date`
  - `rule_events(start: date, end: date) -> list[dict]`
  - `fomc_events(start: date, end: date, csv_path: Path = FOMC_CSV) -> list[dict]`
- Event type strings:
  - rules: `opex`, `quad_witching`, `vix_expiration`, `month_end`, `quarter_end`,
    `ism_manufacturing`, `ism_services`, `consumer_confidence`, `russell_reconstitution`
  - FOMC: `fomc_decision`, `fomc_press_conference`, `fomc_minutes`
- Tier strings: `"1"`, `"2"`, `"market"`

- [ ] **Step 1: Create the FOMC CSV** (scheduled meetings only, transcribed from federalreserve.gov/monetarypolicy/fomccalendars.htm on 2026-09-12; the 2025-08-22 notation vote is deliberately excluded)

`src/options_research/data/fomc_meetings.csv`:

```csv
start_date,end_date,sep
2021-01-26,2021-01-27,false
2021-03-16,2021-03-17,true
2021-04-27,2021-04-28,false
2021-06-15,2021-06-16,true
2021-07-27,2021-07-28,false
2021-09-21,2021-09-22,true
2021-11-02,2021-11-03,false
2021-12-14,2021-12-15,true
2022-01-25,2022-01-26,false
2022-03-15,2022-03-16,true
2022-05-03,2022-05-04,false
2022-06-14,2022-06-15,true
2022-07-26,2022-07-27,false
2022-09-20,2022-09-21,true
2022-11-01,2022-11-02,false
2022-12-13,2022-12-14,true
2023-01-31,2023-02-01,false
2023-03-21,2023-03-22,true
2023-05-02,2023-05-03,false
2023-06-13,2023-06-14,true
2023-07-25,2023-07-26,false
2023-09-19,2023-09-20,true
2023-10-31,2023-11-01,false
2023-12-12,2023-12-13,true
2024-01-30,2024-01-31,false
2024-03-19,2024-03-20,true
2024-04-30,2024-05-01,false
2024-06-11,2024-06-12,true
2024-07-30,2024-07-31,false
2024-09-17,2024-09-18,true
2024-11-06,2024-11-07,false
2024-12-17,2024-12-18,true
2025-01-28,2025-01-29,false
2025-03-18,2025-03-19,true
2025-05-06,2025-05-07,false
2025-06-17,2025-06-18,true
2025-07-29,2025-07-30,false
2025-09-16,2025-09-17,true
2025-10-28,2025-10-29,false
2025-12-09,2025-12-10,true
2026-01-27,2026-01-28,false
2026-03-17,2026-03-18,true
2026-04-28,2026-04-29,false
2026-06-16,2026-06-17,true
2026-07-28,2026-07-29,false
2026-09-15,2026-09-16,true
2026-10-27,2026-10-28,false
2026-12-08,2026-12-09,true
```

- [ ] **Step 2: Write the failing test**

`tests/options_research/test_events_rules.py`:

```python
from datetime import date

from src.options_research.events_rules import (
    EVENT_COLUMNS,
    fomc_events,
    fourth_friday,
    rule_events,
    third_friday,
)


def _find(events, type_):
    return [e for e in events if e["type"] == type_]


def test_event_columns():
    assert EVENT_COLUMNS == ["date", "time_et", "type", "tier", "source", "ticker"]


def test_third_and_fourth_friday():
    assert third_friday(2025, 6) == date(2025, 6, 20)
    assert fourth_friday(2023, 6) == date(2023, 6, 23)


def test_opex_moves_to_thursday_on_good_friday_2022():
    events = rule_events(date(2022, 4, 1), date(2022, 4, 30))
    assert [e["date"] for e in _find(events, "opex")] == [date(2022, 4, 14)]


def test_quad_witching_only_in_quarter_months():
    events = rule_events(date(2025, 1, 1), date(2025, 12, 31))
    assert [e["date"].month for e in _find(events, "quad_witching")] == [3, 6, 9, 12]
    assert len(_find(events, "opex")) == 12


def test_vix_expiration_june_2025():
    events = rule_events(date(2025, 6, 1), date(2025, 6, 30))
    assert [e["date"] for e in _find(events, "vix_expiration")] == [date(2025, 6, 18)]


def test_ism_and_conference_board_rules_sep_aug_2025():
    sep = rule_events(date(2025, 9, 1), date(2025, 9, 30))
    assert [e["date"] for e in _find(sep, "ism_manufacturing")] == [date(2025, 9, 2)]
    assert [e["date"] for e in _find(sep, "ism_services")] == [date(2025, 9, 4)]
    assert _find(sep, "ism_manufacturing")[0]["time_et"] == "10:00"
    aug = rule_events(date(2025, 8, 1), date(2025, 8, 31))
    assert [e["date"] for e in _find(aug, "consumer_confidence")] == [date(2025, 8, 26)]


def test_month_and_quarter_end_are_last_sessions():
    events = rule_events(date(2025, 5, 1), date(2025, 6, 30))
    assert [e["date"] for e in _find(events, "month_end")] == [date(2025, 5, 30), date(2025, 6, 30)]
    assert [e["date"] for e in _find(events, "quarter_end")] == [date(2025, 6, 30)]


def test_russell_reconstitution_is_fourth_friday_of_june():
    events = rule_events(date(2023, 1, 1), date(2023, 12, 31))
    assert [e["date"] for e in _find(events, "russell_reconstitution")] == [date(2023, 6, 23)]


def test_fomc_decision_press_and_minutes_june_2025():
    events = fomc_events(date(2025, 6, 1), date(2025, 7, 31))
    decisions = _find(events, "fomc_decision")
    assert [(e["date"], e["time_et"], e["tier"]) for e in decisions] == [
        (date(2025, 6, 18), "14:00", "1"), (date(2025, 7, 30), "14:00", "1")
    ]
    assert [e["date"] for e in _find(events, "fomc_press_conference")] == [date(2025, 6, 18), date(2025, 7, 30)]
    assert [e["date"] for e in _find(events, "fomc_minutes")] == [date(2025, 7, 9)]


def test_fomc_decision_count_over_study_window():
    events = fomc_events(date(2021, 6, 18), date(2026, 9, 11))
    assert len(_find(events, "fomc_decision")) == 41
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/options_research/test_events_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.options_research.events_rules'`

- [ ] **Step 4: Write minimal implementation**

`src/options_research/events_rules.py`:

```python
"""Rule-computed market-structure/macro events and FOMC events (spec §5.2)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.options_research.market_calendar import (
    get_session,
    next_session_on_or_after,
    previous_session_on_or_before,
    sessions_between,
)

EVENT_COLUMNS = ["date", "time_et", "type", "tier", "source", "ticker"]
FOMC_CSV = Path(__file__).parent / "data" / "fomc_meetings.csv"
_FRIDAY = 4
_TUESDAY = 1


def make_event(day: date, time_et: str | None, type_: str, tier: str, source: str, ticker: str | None = None) -> dict:
    return {"date": day, "time_et": time_et, "type": type_, "tier": tier, "source": source, "ticker": ticker}


def _nth_friday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(_FRIDAY - first.weekday()) % 7 + 7 * (n - 1))


def third_friday(year: int, month: int) -> date:
    return _nth_friday(year, month, 3)


def fourth_friday(year: int, month: int) -> date:
    return _nth_friday(year, month, 4)


def _months(start: date, end: date) -> Iterator[tuple[int, int]]:
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _last_calendar_day(year: int, month: int) -> date:
    next_first = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return next_first - timedelta(days=1)


def _vix_expiration(year: int, month: int) -> date:
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    friday = third_friday(next_year, next_month)
    if get_session(friday) is None:
        friday = previous_session_on_or_before(friday - timedelta(days=1))
    return previous_session_on_or_before(friday - timedelta(days=30))


def rule_events(start: date, end: date) -> list[dict]:
    events: list[dict] = []

    def add(day: date, time_et: str | None, type_: str, tier: str) -> None:
        if start <= day <= end:
            events.append(make_event(day, time_et, type_, tier, "rule"))

    for year, month in _months(start, end):
        opex = previous_session_on_or_before(third_friday(year, month))
        add(opex, None, "opex", "market")
        if month in (3, 6, 9, 12):
            add(opex, None, "quad_witching", "market")
        add(_vix_expiration(year, month), None, "vix_expiration", "market")

        month_end = previous_session_on_or_before(_last_calendar_day(year, month))
        add(month_end, "16:00", "month_end", "market")
        if month in (3, 6, 9, 12):
            add(month_end, "16:00", "quarter_end", "market")

        month_sessions = sessions_between(date(year, month, 1), _last_calendar_day(year, month))
        if month_sessions:
            add(month_sessions[0].day, "10:00", "ism_manufacturing", "2")
        if len(month_sessions) >= 3:
            add(month_sessions[2].day, "10:00", "ism_services", "2")

        last_day = _last_calendar_day(year, month)
        last_tuesday = last_day - timedelta(days=(last_day.weekday() - _TUESDAY) % 7)
        add(previous_session_on_or_before(last_tuesday), "10:00", "consumer_confidence", "2")

        if month == 6:
            add(previous_session_on_or_before(fourth_friday(year, 6)), "16:00", "russell_reconstitution", "market")
    return events


def fomc_events(start: date, end: date, csv_path: Path = FOMC_CSV) -> list[dict]:
    meetings = pd.read_csv(csv_path, parse_dates=["start_date", "end_date"])
    events: list[dict] = []
    for decision in (ts.date() for ts in meetings["end_date"]):
        if start <= decision <= end:
            events.append(make_event(decision, "14:00", "fomc_decision", "1", "fomc_csv"))
            events.append(make_event(decision, "14:30", "fomc_press_conference", "1", "fomc_csv"))
        minutes_day = next_session_on_or_after(decision + timedelta(days=21))
        if start <= minutes_day <= end:
            events.append(make_event(minutes_day, "14:00", "fomc_minutes", "2", "fomc_csv"))
    return events
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/options_research/test_events_rules.py -v`
Expected: 10 passed

- [ ] **Step 6: Commit**

```bash
git add src/options_research/data/fomc_meetings.csv src/options_research/events_rules.py tests/options_research/test_events_rules.py
git commit -F- <<'EOF'
feat(options_research): rule-based market/macro events and FOMC calendar

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 5: FRED release dates, earnings, events table builder

**Files:**
- Create: `src/options_research/events_sources.py`
- Test: `tests/options_research/test_events_sources.py`

**Interfaces:**
- Consumes:
  - `events_rules.make_event`, `EVENT_COLUMNS`, `rule_events`, `fomc_events`
  - `market_calendar.get_session`, `next_session_on_or_after`
  - `config.UNIVERSE`, `ETFS`, `TZ_ET`, `lake_root`
- Produces:
  - `FRED_URL: str`
  - `FRED_RELEASES: dict[int, tuple[str, str, str]]`, mapping release_id to `(type, tier, time_et)`
  - `fred_release_events(api_key: str, start: date, end: date, http: httpx.Client | None = None) -> list[dict]`
  - `earnings_events(tickers, start: date, end: date, fetch: Callable[[str], pd.DataFrame] | None = None) -> list[dict]`
    - types `earnings_bmo` / `earnings_amc`
    - tier `"earnings"`
    - `date` = the session that reacts: same day for BMO, next session for AMC
  - `build_events(start: date, end: date, fred_api_key: str | None, earnings_fetch=None, http=None) -> tuple[pd.DataFrame, dict]`
  - `write_events(df: pd.DataFrame, notes: dict, root: Path | None = None) -> Path`, which writes
    `calendar/events.parquet` and `calendar/events_notes.json`
  - `load_events(root: Path | None = None) -> pd.DataFrame`

- [ ] **Step 1: Write the failing test**

`tests/options_research/test_events_sources.py`:

```python
import json
from datetime import date

import httpx
import pandas as pd

from src.options_research.events_sources import (
    FRED_RELEASES,
    build_events,
    earnings_events,
    fred_release_events,
    load_events,
    write_events,
)


def fred_handler(dates_by_release):
    def handler(request):
        rid = int(request.url.params["release_id"])
        assert request.url.params["file_type"] == "json"
        assert request.url.params["api_key"] == "k"
        return httpx.Response(200, json={"release_dates": [{"release_id": rid, "date": d} for d in dates_by_release.get(rid, [])]})
    return handler


def test_fred_release_ids_and_times():
    assert FRED_RELEASES == {
        10: ("cpi", "1", "08:30"),
        50: ("employment_situation", "1", "08:30"),
        46: ("ppi", "2", "08:30"),
        54: ("personal_income_outlays", "2", "08:30"),
        53: ("gdp", "2", "08:30"),
        9: ("retail_sales", "2", "08:30"),
        192: ("jolts", "2", "10:00"),
    }


def test_fred_events_filter_range_and_non_sessions():
    http = httpx.Client(transport=httpx.MockTransport(fred_handler({
        10: ["2025-06-11", "2025-06-14", "2019-01-11"],  # in range; Saturday; out of range
        192: ["2025-06-03"],
    })))
    events = fred_release_events("k", date(2025, 1, 1), date(2025, 12, 31), http=http)
    assert sorted((e["date"], e["type"], e["time_et"], e["tier"], e["source"]) for e in events) == [
        (date(2025, 6, 3), "jolts", "10:00", "2", "fred"),
        (date(2025, 6, 11), "cpi", "08:30", "1", "fred"),
    ]


def _earnings_frame(timestamps):
    index = pd.DatetimeIndex(pd.to_datetime(timestamps)).tz_localize("America/New_York")
    index.name = "Earnings Date"
    return pd.DataFrame({"EPS Estimate": [1.0] * len(timestamps)}, index=index)


def test_earnings_bmo_same_day_amc_next_session_and_etfs_skipped():
    frames = {
        "NVDA": _earnings_frame(["2025-02-26 16:00"]),
        "AAPL": _earnings_frame(["2025-05-01 07:00"]),
    }
    calls = []

    def fetch(ticker):
        calls.append(ticker)
        return frames.get(ticker, _earnings_frame([]))

    events = earnings_events(["SPY", "NVDA", "AAPL"], date(2025, 1, 1), date(2025, 12, 31), fetch=fetch)
    assert "SPY" not in calls
    assert sorted((e["ticker"], e["date"], e["type"], e["tier"]) for e in events) == [
        ("AAPL", date(2025, 5, 1), "earnings_bmo", "earnings"),
        ("NVDA", date(2025, 2, 27), "earnings_amc", "earnings"),
    ]


def test_build_events_without_fred_key_records_note_and_writes(tmp_path):
    df, notes = build_events(date(2025, 6, 1), date(2025, 6, 30), fred_api_key=None, earnings_fetch=lambda t: _earnings_frame([]))
    assert notes["fred"].startswith("skipped")
    assert {"opex", "fomc_decision", "vix_expiration"} <= set(df["type"])
    assert list(df.columns) == ["date", "time_et", "type", "tier", "source", "ticker"]
    assert df["date"].is_monotonic_increasing
    path = write_events(df, notes, root=tmp_path)
    assert path == tmp_path / "calendar" / "events.parquet"
    assert json.loads((tmp_path / "calendar" / "events_notes.json").read_text())["fred"].startswith("skipped")
    loaded = load_events(root=tmp_path)
    assert len(loaded) == len(df)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/options_research/test_events_sources.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.options_research.events_sources'`

- [ ] **Step 3: Write minimal implementation**

`src/options_research/events_sources.py`:

```python
"""FRED macro release dates, yfinance earnings dates, and the combined events table (spec §5.2)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

from src.options_research.config import ETFS, TZ_ET, UNIVERSE, lake_root
from src.options_research.events_rules import EVENT_COLUMNS, fomc_events, make_event, rule_events
from src.options_research.market_calendar import get_session, next_session_on_or_after

FRED_URL = "https://api.stlouisfed.org/fred/release/dates"
FRED_RELEASES: dict[int, tuple[str, str, str]] = {
    10: ("cpi", "1", "08:30"),
    50: ("employment_situation", "1", "08:30"),
    46: ("ppi", "2", "08:30"),
    54: ("personal_income_outlays", "2", "08:30"),
    53: ("gdp", "2", "08:30"),
    9: ("retail_sales", "2", "08:30"),
    192: ("jolts", "2", "10:00"),
}


def fred_release_events(api_key: str, start: date, end: date, http: httpx.Client | None = None) -> list[dict]:
    http = http or httpx.Client(timeout=30)
    events: list[dict] = []
    for release_id, (type_, tier, time_et) in FRED_RELEASES.items():
        response = http.get(FRED_URL, params={
            "release_id": release_id,
            "api_key": api_key,
            "file_type": "json",
            "include_release_dates_with_no_data": "false",
            "limit": 10000,
        })
        response.raise_for_status()
        for item in response.json()["release_dates"]:
            day = date.fromisoformat(item["date"])
            if start <= day <= end and get_session(day) is not None:
                events.append(make_event(day, time_et, type_, tier, "fred"))
    return events


def _yfinance_earnings(ticker: str) -> pd.DataFrame:
    import yfinance as yf

    return yf.Ticker(ticker).get_earnings_dates(limit=40)


def earnings_events(
    tickers: Iterable[str],
    start: date,
    end: date,
    fetch: Callable[[str], pd.DataFrame] | None = None,
) -> list[dict]:
    fetch = fetch or _yfinance_earnings
    events: list[dict] = []
    for ticker in tickers:
        if ticker in ETFS:
            continue
        frame = fetch(ticker)
        if frame is None or frame.empty:
            continue
        for stamp in frame.index:
            stamp = pd.Timestamp(stamp)
            stamp_et = stamp.tz_convert(TZ_ET) if stamp.tzinfo else stamp.tz_localize(TZ_ET)
            if stamp_et.hour < 12:
                impact, type_ = stamp_et.date(), "earnings_bmo"
            else:
                impact, type_ = next_session_on_or_after(stamp_et.date() + timedelta(days=1)), "earnings_amc"
            if start <= impact <= end and get_session(impact) is not None:
                events.append(make_event(impact, None, type_, "earnings", "yfinance", ticker=ticker))
    return events


def build_events(
    start: date,
    end: date,
    fred_api_key: str | None,
    earnings_fetch: Callable[[str], pd.DataFrame] | None = None,
    http: httpx.Client | None = None,
) -> tuple[pd.DataFrame, dict]:
    rows = rule_events(start, end) + fomc_events(start, end)
    notes: dict = {"start": start.isoformat(), "end": end.isoformat()}
    if fred_api_key:
        rows += fred_release_events(fred_api_key, start, end, http=http)
        notes["fred"] = "included"
    else:
        notes["fred"] = "skipped: FRED_API_KEY not set"
    rows += earnings_events(UNIVERSE, start, end, fetch=earnings_fetch)
    frame = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    frame = (
        frame.assign(_t=frame["time_et"].fillna(""), _k=frame["ticker"].fillna(""))
        .sort_values(["date", "_t", "type", "_k"], kind="stable")
        .drop(columns=["_t", "_k"])
        .reset_index(drop=True)
    )
    return frame, notes


def write_events(df: pd.DataFrame, notes: dict, root: Path | None = None) -> Path:
    folder = (root or lake_root()) / "calendar"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "events.parquet"
    df.to_parquet(path, index=False)
    (folder / "events_notes.json").write_text(json.dumps(notes, indent=2))
    return path


def load_events(root: Path | None = None) -> pd.DataFrame:
    return pd.read_parquet((root or lake_root()) / "calendar" / "events.parquet")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/options_research/test_events_sources.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/options_research/events_sources.py tests/options_research/test_events_sources.py
git commit -F- <<'EOF'
feat(options_research): FRED release dates, earnings timing and events table

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 6: Bad-print flags

**Files:**
- Create: `src/options_research/quality.py`
- Test: `tests/options_research/test_quality.py`

**Interfaces:**
- Produces: `flag_bad_prints(df: pd.DataFrame, window: int = 15, mad_mult: float = 8.0, min_pct: float = 0.03) -> pd.DataFrame`
  - Input: one symbol's bars sorted by `ts`, with columns `open, high, low, close`.
  - The reference is the median of the **previous** `window` closes, so the current bar and future
    bars are excluded.
  - Threshold = max(`mad_mult` × MAD, `min_pct` × reference).
  - Returns a copy with added `bad_high`, `bad_low`, `bad_close` (bool) and `high_clean`,
    `low_clean` (float).
    - Flagged extremes are replaced by the bar body clipped into [reference − threshold,
      reference + threshold].
    - `low_clean` ≤ `high_clean` always.

- [ ] **Step 1: Write the failing test**

`tests/options_research/test_quality.py`:

```python
import pandas as pd

from src.options_research.quality import flag_bad_prints


def bars(closes, highs=None, lows=None):
    closes = [float(c) for c in closes]
    highs = highs or [c + 0.05 for c in closes]
    lows = lows or [c - 0.05 for c in closes]
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes})


def test_normal_bars_are_not_flagged():
    out = flag_bad_prints(bars([100 + 0.01 * i for i in range(30)]))
    assert not out["bad_high"].any() and not out["bad_low"].any()
    assert (out["high_clean"] == out["high"]).all()


def test_spike_high_is_flagged_and_clipped_to_body():
    closes = [121.0 + 0.02 * i for i in range(30)]
    highs = [c + 0.05 for c in closes]
    highs[20] = 195.95
    out = flag_bad_prints(bars(closes, highs=highs))
    assert out.loc[20, "bad_high"]
    assert out["bad_high"].sum() == 1
    assert out.loc[20, "high_clean"] == max(out.loc[20, "open"], out.loc[20, "close"])


def test_spike_low_is_flagged_and_clipped():
    closes = [50.0] * 30
    lows = [49.95] * 30
    lows[10] = 30.0
    out = flag_bad_prints(bars(closes, lows=lows))
    assert out.loc[10, "bad_low"] and out.loc[10, "low_clean"] == 50.0


def test_single_print_outlier_bar_is_clipped_to_reference_band():
    closes = [121.0] * 30
    opens = closes.copy()
    highs = [121.05] * 30
    lows = [120.95] * 30
    closes[20] = opens[20] = highs[20] = lows[20] = 195.95
    out = flag_bad_prints(pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes}))
    assert out.loc[20, "bad_high"] and out.loc[20, "bad_close"] and out.loc[20, "bad_low"]
    assert out.loc[20, "high_clean"] < 125.0
    assert out.loc[20, "low_clean"] <= out.loc[20, "high_clean"]
    assert not out.loc[21, "bad_high"]


def test_flags_use_only_past_bars():
    closes = [100.0] * 30
    base = flag_bad_prints(bars(closes))
    changed = closes.copy()
    changed[25] = 150.0
    later = flag_bad_prints(bars(changed))
    pd.testing.assert_frame_equal(base.iloc[:25], later.iloc[:25])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/options_research/test_quality.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.options_research.quality'`

- [ ] **Step 3: Write minimal implementation**

`src/options_research/quality.py`:

```python
"""Trailing-window bad-print detection for 1-minute stock bars (spec §5.1)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def flag_bad_prints(df: pd.DataFrame, window: int = 15, mad_mult: float = 8.0, min_pct: float = 0.03) -> pd.DataFrame:
    out = df.copy()
    close = out["close"].astype(float)
    previous = close.shift(1)
    reference = previous.rolling(window, min_periods=1).median()
    mad = (previous - reference).abs().rolling(window, min_periods=1).median()
    threshold = np.maximum(mad_mult * mad, min_pct * reference)
    lower, upper = reference - threshold, reference + threshold

    def outside(values: pd.Series) -> pd.Series:
        return (values.astype(float) - reference).abs() > threshold  # NaN reference (first bar) -> False

    out["bad_high"] = outside(out["high"])
    out["bad_low"] = outside(out["low"])
    out["bad_close"] = outside(close)
    body_high = out[["open", "close"]].max(axis=1).astype(float).clip(lower=lower, upper=upper)
    body_low = out[["open", "close"]].min(axis=1).astype(float).clip(lower=lower, upper=upper)
    out["high_clean"] = out["high"].astype(float).where(~out["bad_high"], body_high)
    out["low_clean"] = out["low"].astype(float).where(~out["bad_low"], body_low)
    out["low_clean"] = np.minimum(out["low_clean"], out["high_clean"])
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/options_research/test_quality.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/options_research/quality.py tests/options_research/test_quality.py
git commit -F- <<'EOF'
feat(options_research): trailing-window bad-print flags for minute bars

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 7: Zip minute-bar ingest

**Files:**
- Create: `src/options_research/stocks.py`
- Test: `tests/options_research/test_stocks.py`

**Interfaces:**
- Consumes: `quality.flag_bad_prints`; `config.UNIVERSE`, `TZ_ET`, `lake_root`
- Produces:
  - `STOCK_COLUMNS = ["symbol", "ts", "open", "high", "low", "close", "volume", "transactions", "bad_high", "bad_low", "bad_close", "high_clean", "low_clean", "source"]`
  - `normalize_minutes(raw: pd.DataFrame, source: str) -> pd.DataFrame`
    - raw columns: `symbol, ts (UTC tz-aware), open, high, low, close, volume, transactions`
    - keeps 04:00 ≤ ET < 20:00 and flags per symbol
  - `zip_minute_members(zip_path: Path) -> dict[date, str]`
  - `read_zip_day(zip_path: Path, member: str, tickers: Iterable[str]) -> pd.DataFrame`
  - `day_path(root: Path, symbol: str, day: date) -> Path`, i.e. `root/stock_1m/<SYMBOL>/<YYYY>/<YYYY-MM-DD>.parquet`
  - `write_day(df: pd.DataFrame, day: date, root: Path) -> int`
  - `ingest_zip(zip_path: Path, start: date, end: date, tickers=UNIVERSE, root: Path | None = None, workers: int = 4, overwrite: bool = False) -> dict`,
    with keys `days_available`, `days_written`, `days_skipped`, `rows`

- [ ] **Step 1: Write the failing test**

`tests/options_research/test_stocks.py`:

```python
import gzip
import io
import zipfile
from datetime import date

import pandas as pd

from src.options_research.stocks import (
    STOCK_COLUMNS,
    day_path,
    ingest_zip,
    normalize_minutes,
    read_zip_day,
    zip_minute_members,
)

# 2025-06-11 is EDT (UTC-4): 04:00 ET = 08:00Z, 09:30 ET = 13:30Z, 20:00 ET = 00:00Z next day
NS = 1_000_000_000


def ns(iso):
    return int(pd.Timestamp(iso).value)


def make_zip(tmp_path):
    rows = [
        ("SPY", 100, 600.0, 600.1, 600.2, 599.9, ns("2025-06-11T07:59:00Z"), 3),   # 03:59 ET -> dropped
        ("SPY", 500, 600.0, 600.2, 600.3, 599.8, ns("2025-06-11T13:30:00Z"), 40),  # 09:30 ET -> kept
        ("SPY", 300, 600.2, 600.1, 600.4, 600.0, ns("2025-06-11T23:59:00Z"), 9),   # 19:59 ET -> kept
        ("SPY", 200, 600.1, 600.1, 600.1, 600.1, ns("2025-06-12T00:00:00Z"), 2),   # 20:00 ET -> dropped
        ("XYZ", 900, 10.0, 10.1, 10.2, 9.9, ns("2025-06-11T13:30:00Z"), 5),       # not in universe
    ]
    frame = pd.DataFrame(rows, columns=["ticker", "volume", "open", "close", "high", "low", "window_start", "transactions"])
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(frame.to_csv(index=False).encode())
    path = tmp_path / "eq.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("minute_aggs/2025/06/2025-06-11.csv.gz", buf.getvalue())
        zf.writestr("day_aggs/2025/06/2025-06-11.csv.gz", b"")
    return path


def test_zip_minute_members_maps_dates(tmp_path):
    members = zip_minute_members(make_zip(tmp_path))
    assert members == {date(2025, 6, 11): "minute_aggs/2025/06/2025-06-11.csv.gz"}


def test_read_zip_day_filters_hours_tickers_and_converts_ts(tmp_path):
    path = make_zip(tmp_path)
    df = read_zip_day(path, "minute_aggs/2025/06/2025-06-11.csv.gz", ["SPY", "QQQ"])
    assert list(df.columns) == STOCK_COLUMNS
    assert df["symbol"].unique().tolist() == ["SPY"]
    assert df["ts"].tolist() == [pd.Timestamp("2025-06-11T13:30:00Z"), pd.Timestamp("2025-06-11T23:59:00Z")]
    assert str(df["ts"].dt.tz) == "UTC"
    assert df["source"].unique().tolist() == ["zip"]
    assert df["volume"].dtype == "int64"


def test_ingest_zip_writes_day_files_and_skips_existing(tmp_path):
    path = make_zip(tmp_path)
    root = tmp_path / "lake"
    first = ingest_zip(path, date(2025, 6, 1), date(2025, 6, 30), tickers=("SPY",), root=root, workers=1)
    assert first == {"days_available": 1, "days_written": 1, "days_skipped": 0, "rows": 2}
    written = pd.read_parquet(day_path(root, "SPY", date(2025, 6, 11)))
    assert len(written) == 2
    second = ingest_zip(path, date(2025, 6, 1), date(2025, 6, 30), tickers=("SPY",), root=root, workers=1)
    assert second["days_written"] == 0 and second["days_skipped"] == 1


def test_normalize_minutes_empty_input_keeps_schema():
    empty = pd.DataFrame(columns=["symbol", "ts", "open", "high", "low", "close", "volume", "transactions"])
    empty["ts"] = pd.to_datetime(empty["ts"], utc=True)
    out = normalize_minutes(empty, source="zip")
    assert list(out.columns) == STOCK_COLUMNS and out.empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/options_research/test_stocks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.options_research.stocks'`

- [ ] **Step 3: Write minimal implementation**

`src/options_research/stocks.py`:

```python
"""Ingest 1-minute stock bars from the Polygon/Massive flat-file zip into the lake (spec §5.1)."""

from __future__ import annotations

import gzip
import zipfile
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd

from src.options_research.config import TZ_ET, UNIVERSE, lake_root
from src.options_research.quality import flag_bad_prints

MINUTE_COLUMNS = ["ticker", "volume", "open", "close", "high", "low", "window_start", "transactions"]
RAW_COLUMNS = ["symbol", "ts", "open", "high", "low", "close", "volume", "transactions"]
STOCK_COLUMNS = RAW_COLUMNS + ["bad_high", "bad_low", "bad_close", "high_clean", "low_clean", "source"]
_FIRST_MINUTE = 4 * 60    # 04:00 ET
_END_MINUTE = 20 * 60     # 20:00 ET (exclusive)


def normalize_minutes(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=STOCK_COLUMNS)
    et = raw["ts"].dt.tz_convert(TZ_ET)
    minute_of_day = et.dt.hour * 60 + et.dt.minute
    kept = raw.loc[(minute_of_day >= _FIRST_MINUTE) & (minute_of_day < _END_MINUTE), RAW_COLUMNS]
    parts = [flag_bad_prints(group.reset_index(drop=True)) for _, group in kept.sort_values(["symbol", "ts"]).groupby("symbol", sort=True)]
    if not parts:
        return pd.DataFrame(columns=STOCK_COLUMNS)
    out = pd.concat(parts, ignore_index=True)
    out["volume"] = out["volume"].astype("int64")
    out["transactions"] = out["transactions"].fillna(0).astype("int64")
    out["source"] = source
    return out[STOCK_COLUMNS]


def zip_minute_members(zip_path: Path) -> dict[date, str]:
    with zipfile.ZipFile(zip_path) as zf:
        return {
            date.fromisoformat(name.rsplit("/", 1)[1][:10]): name
            for name in zf.namelist()
            if name.startswith("minute_aggs/") and name.endswith(".csv.gz")
        }


def read_zip_day(zip_path: Path, member: str, tickers: Iterable[str]) -> pd.DataFrame:
    wanted = set(tickers)
    with zipfile.ZipFile(zip_path) as zf, zf.open(member) as raw, gzip.GzipFile(fileobj=raw) as gz:
        frame = pd.read_csv(gz, usecols=MINUTE_COLUMNS, dtype={"ticker": "string"})
    frame = frame[frame["ticker"].isin(wanted)].rename(columns={"ticker": "symbol"})
    frame["symbol"] = frame["symbol"].astype(str)
    frame["ts"] = pd.to_datetime(frame["window_start"], unit="ns", utc=True)
    return normalize_minutes(frame.drop(columns=["window_start"]), source="zip")


def day_path(root: Path, symbol: str, day: date) -> Path:
    return root / "stock_1m" / symbol / f"{day.year}" / f"{day.isoformat()}.parquet"


def write_day(df: pd.DataFrame, day: date, root: Path) -> int:
    for symbol, group in df.groupby("symbol"):
        path = day_path(root, symbol, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        group.to_parquet(path, index=False)
    return len(df)


def _ingest_one(job: tuple[Path, str, date, tuple[str, ...], Path]) -> int:
    zip_path, member, day, tickers, root = job
    return write_day(read_zip_day(zip_path, member, tickers), day, root)


def ingest_zip(
    zip_path: Path,
    start: date,
    end: date,
    tickers: Iterable[str] = UNIVERSE,
    root: Path | None = None,
    workers: int = 4,
    overwrite: bool = False,
) -> dict:
    root = root or lake_root()
    tickers = tuple(tickers)
    members = zip_minute_members(zip_path)
    in_range = {d: m for d, m in sorted(members.items()) if start <= d <= end}
    jobs = [
        (zip_path, member, day, tickers, root)
        for day, member in in_range.items()
        if overwrite or not day_path(root, tickers[0], day).exists()
    ]
    if workers <= 1:
        row_counts = [_ingest_one(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            row_counts = list(pool.map(_ingest_one, jobs, chunksize=4))
    return {
        "days_available": len(in_range),
        "days_written": len(jobs),
        "days_skipped": len(in_range) - len(jobs),
        "rows": int(sum(row_counts)),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/options_research/test_stocks.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/options_research/stocks.py tests/options_research/test_stocks.py
git commit -F- <<'EOF'
feat(options_research): ingest 1-minute stock bars from the equity zip

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 8: Alpaca SIP tail ingest and zip-vs-Alpaca comparison

**Files:**
- Create: `src/options_research/stocks_alpaca.py`
- Test: `tests/options_research/test_stocks_alpaca.py`

**Interfaces:**
- Consumes:
  - `alpaca_data.AlpacaDataClient.paginate`
  - `stocks.normalize_minutes`, `write_day`, `day_path`, `STOCK_COLUMNS`
  - `market_calendar.sessions_between`, `ET`
  - `config.UNIVERSE`, `lake_root`
- Produces:
  - `STOCK_BARS_URL: str`
  - `fetch_alpaca_day(client, tickers: Iterable[str], day: date) -> pd.DataFrame` (`STOCK_COLUMNS`, `source="alpaca"`)
  - `ingest_alpaca_tail(client, start: date, end: date, tickers=UNIVERSE, root: Path | None = None, overwrite: bool = False) -> dict`
  - `compare_sources(zip_df: pd.DataFrame, alpaca_df: pd.DataFrame) -> dict`,
    with keys `compared`, `ohlc_mismatch`, `volume_mismatch`, `zip_only`, `alpaca_only`
  - `validate_zip_overlap(client, days: Iterable[date], tickers=UNIVERSE, root: Path | None = None) -> dict[str, dict]`

- [ ] **Step 1: Write the failing test**

`tests/options_research/test_stocks_alpaca.py`:

```python
from datetime import date

import httpx
import pandas as pd

from src.options_research.alpaca_data import AlpacaDataClient, RateLimiter
from src.options_research.stocks import day_path, write_day
from src.options_research.stocks_alpaca import (
    STOCK_BARS_URL,
    compare_sources,
    fetch_alpaca_day,
    ingest_alpaca_tail,
    validate_zip_overlap,
)


def bar(t, o=600.0, h=600.5, l=599.5, c=600.2, v=1000, n=10):
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "n": n, "vw": c}


def client_for(pages):
    def handler(request):
        assert request.method == "GET"
        assert str(request.url).startswith(STOCK_BARS_URL)
        assert request.url.params["timeframe"] == "1Min"
        assert request.url.params["feed"] == "sip"
        assert request.url.params["adjustment"] == "raw"
        token = request.url.params.get("page_token")
        return httpx.Response(200, json=pages[token])
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return AlpacaDataClient(key="k", secret="s", http=http, limiter=RateLimiter(1000), sleep=lambda s: None)


def test_fetch_alpaca_day_paginates_and_normalizes():
    pages = {
        None: {"bars": {"SPY": [bar("2025-06-11T13:30:00Z")]}, "next_page_token": "p2"},
        "p2": {"bars": {"SPY": [bar("2025-06-11T13:31:00Z")], "QQQ": [bar("2025-06-12T00:00:00Z")]}, "next_page_token": None},
    }
    df = fetch_alpaca_day(client_for(pages), ["SPY", "QQQ"], date(2025, 6, 11))
    assert df["source"].unique().tolist() == ["alpaca"]
    assert df[df["symbol"] == "SPY"]["ts"].tolist() == [pd.Timestamp("2025-06-11T13:30:00Z"), pd.Timestamp("2025-06-11T13:31:00Z")]
    assert df[df["symbol"] == "QQQ"].empty  # 20:00 ET excluded


def test_ingest_alpaca_tail_writes_sessions_only(tmp_path):
    pages = {None: {"bars": {"SPY": [bar("2025-12-24T14:30:00Z")]}, "next_page_token": None}}
    summary = ingest_alpaca_tail(client_for(pages), date(2025, 12, 24), date(2025, 12, 25), tickers=("SPY",), root=tmp_path)
    assert summary == {"sessions": 1, "days_written": 1, "days_skipped": 0, "rows": 1}
    assert day_path(tmp_path, "SPY", date(2025, 12, 24)).exists()


def frame(rows, source):
    df = pd.DataFrame(rows, columns=["symbol", "ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["source"] = source
    return df


def test_compare_sources_counts_mismatches():
    z = frame([("SPY", "2025-06-11T13:30:00Z", 1, 2, 0.5, 1.5, 100), ("SPY", "2025-06-11T13:31:00Z", 1, 2, 0.5, 1.5, 100),
               ("SPY", "2025-06-11T13:32:00Z", 1, 2, 0.5, 1.5, 100)], "zip")
    a = frame([("SPY", "2025-06-11T13:30:00Z", 1, 2, 0.5, 1.5, 100), ("SPY", "2025-06-11T13:31:00Z", 1, 2.1, 0.5, 1.5, 90),
               ("SPY", "2025-06-11T13:33:00Z", 1, 2, 0.5, 1.5, 100)], "alpaca")
    assert compare_sources(z, a) == {"compared": 2, "ohlc_mismatch": 1, "volume_mismatch": 1, "zip_only": 1, "alpaca_only": 1}


def test_validate_zip_overlap_reads_lake_and_compares(tmp_path):
    day = date(2025, 6, 11)
    lake_rows = pd.DataFrame({
        "symbol": ["SPY"], "ts": pd.to_datetime(["2025-06-11T13:30:00Z"], utc=True),
        "open": [600.0], "high": [600.5], "low": [599.5], "close": [600.2], "volume": [1000], "transactions": [10],
        "bad_high": [False], "bad_low": [False], "bad_close": [False], "high_clean": [600.5], "low_clean": [599.5], "source": ["zip"],
    })
    write_day(lake_rows, day, tmp_path)
    pages = {None: {"bars": {"SPY": [bar("2025-06-11T13:30:00Z")]}, "next_page_token": None}}
    result = validate_zip_overlap(client_for(pages), [day], tickers=("SPY",), root=tmp_path)
    assert result == {"2025-06-11": {"compared": 1, "ohlc_mismatch": 0, "volume_mismatch": 0, "zip_only": 0, "alpaca_only": 0}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/options_research/test_stocks_alpaca.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.options_research.stocks_alpaca'`

- [ ] **Step 3: Write minimal implementation**

`src/options_research/stocks_alpaca.py`:

```python
"""Alpaca SIP 1-minute stock bars for the post-zip tail, plus zip-vs-Alpaca validation (spec §5.1, §5.7)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timezone
from pathlib import Path

import pandas as pd

from src.options_research.alpaca_data import AlpacaDataClient
from src.options_research.config import UNIVERSE, lake_root
from src.options_research.market_calendar import ET, sessions_between
from src.options_research.stocks import day_path, normalize_minutes, write_day

STOCK_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"


def _utc_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_alpaca_day(client: AlpacaDataClient, tickers: Iterable[str], day: date) -> pd.DataFrame:
    params = {
        "symbols": ",".join(tickers),
        "timeframe": "1Min",
        "start": _utc_z(datetime.combine(day, time(4, 0), ET)),
        "end": _utc_z(datetime.combine(day, time(20, 0), ET)),
        "feed": "sip",
        "adjustment": "raw",
        "limit": 10000,
    }
    rows = []
    for page in client.paginate(STOCK_BARS_URL, params):
        for symbol, bars in (page.get("bars") or {}).items():
            for b in bars:
                rows.append({
                    "symbol": symbol, "ts": b["t"], "open": b["o"], "high": b["h"], "low": b["l"],
                    "close": b["c"], "volume": b["v"], "transactions": b.get("n", 0),
                })
    raw = pd.DataFrame(rows, columns=["symbol", "ts", "open", "high", "low", "close", "volume", "transactions"])
    raw["ts"] = pd.to_datetime(raw["ts"], utc=True)
    return normalize_minutes(raw, source="alpaca")


def ingest_alpaca_tail(
    client: AlpacaDataClient,
    start: date,
    end: date,
    tickers: Iterable[str] = UNIVERSE,
    root: Path | None = None,
    overwrite: bool = False,
) -> dict:
    root = root or lake_root()
    tickers = tuple(tickers)
    sessions = sessions_between(start, end)
    written = rows = 0
    for session in sessions:
        if not overwrite and day_path(root, tickers[0], session.day).exists():
            continue
        rows += write_day(fetch_alpaca_day(client, tickers, session.day), session.day, root)
        written += 1
    return {"sessions": len(sessions), "days_written": written, "days_skipped": len(sessions) - written, "rows": rows}


def compare_sources(zip_df: pd.DataFrame, alpaca_df: pd.DataFrame) -> dict:
    keys = ["symbol", "ts"]
    cols = ["open", "high", "low", "close", "volume"]
    merged = zip_df[keys + cols].merge(alpaca_df[keys + cols], on=keys, how="outer", suffixes=("_zip", "_alp"), indicator=True)
    both = merged[merged["_merge"] == "both"]
    ohlc_diff = pd.Series(False, index=both.index)
    for col in ("open", "high", "low", "close"):
        ohlc_diff |= both[f"{col}_zip"].astype(float).round(4) != both[f"{col}_alp"].astype(float).round(4)
    return {
        "compared": int(len(both)),
        "ohlc_mismatch": int(ohlc_diff.sum()),
        "volume_mismatch": int((both["volume_zip"].astype("int64") != both["volume_alp"].astype("int64")).sum()),
        "zip_only": int((merged["_merge"] == "left_only").sum()),
        "alpaca_only": int((merged["_merge"] == "right_only").sum()),
    }


def validate_zip_overlap(
    client: AlpacaDataClient,
    days: Iterable[date],
    tickers: Iterable[str] = UNIVERSE,
    root: Path | None = None,
) -> dict[str, dict]:
    # Data-validation exception to the holdout guard (spec §9.1): reads lake files directly, computes no strategy metrics.
    root = root or lake_root()
    tickers = tuple(tickers)
    results: dict[str, dict] = {}
    for day in days:
        files = [day_path(root, t, day) for t in tickers if day_path(root, t, day).exists()]
        zip_df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame(columns=["symbol", "ts", "open", "high", "low", "close", "volume"])
        results[day.isoformat()] = compare_sources(zip_df, fetch_alpaca_day(client, tickers, day))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/options_research/test_stocks_alpaca.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/options_research/stocks_alpaca.py tests/options_research/test_stocks_alpaca.py
git commit -F- <<'EOF'
feat(options_research): Alpaca SIP minute tail and zip-vs-Alpaca validation

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 9: Split detection and adjustment factors

**Files:**
- Create: `src/options_research/corporate_actions.py`
- Test: `tests/options_research/test_corporate_actions.py`

**Interfaces:**
- Consumes: `market_calendar.get_session`; `config.TZ_ET`, `lake_root`
- Produces:
  - `SPLIT_RATIOS = (2, 3, 4, 5, 10, 15, 20)`
  - `EXPECTED_SPLITS: frozenset[tuple[str, date, float]]`
  - `daily_rth_summary(minutes: pd.DataFrame) -> pd.DataFrame`
    - columns `symbol, day, rth_open, rth_close, rth_volume`
    - RTH runs 09:30 ET to the session close
  - `detect_splits(daily: pd.DataFrame, tol: float = 0.03) -> pd.DataFrame`
    - columns `symbol, day, ratio, factor`
    - `ratio` 10.0 means 10-for-1; `factor` is the multiplier for prices **before** `day`
  - `adjustment_factors(splits: pd.DataFrame, symbol: str, days: pd.Series) -> pd.Series`
    - adjusted price = raw × factor; adjusted volume = raw ÷ factor
  - `write_splits(df, root=None) -> Path`, i.e. `corporate_actions/splits.parquet`
  - `load_splits(root=None) -> pd.DataFrame`

- [ ] **Step 1: Write the failing test**

`tests/options_research/test_corporate_actions.py`:

```python
from datetime import date, timedelta

import pandas as pd

from src.options_research.corporate_actions import (
    EXPECTED_SPLITS,
    adjustment_factors,
    daily_rth_summary,
    detect_splits,
    load_splits,
    write_splits,
)


def daily_frame(symbol, closes, volumes, opens=None, start=date(2024, 5, 1)):
    days = [start + timedelta(days=i) for i in range(len(closes))]
    return pd.DataFrame({"symbol": symbol, "day": days, "rth_open": opens or closes, "rth_close": closes, "rth_volume": volumes})


def test_expected_splits_listed():
    assert EXPECTED_SPLITS == frozenset({
        ("NVDA", date(2021, 7, 20), 4.0), ("AMZN", date(2022, 6, 6), 20.0), ("GOOGL", date(2022, 7, 18), 20.0),
        ("TSLA", date(2022, 8, 25), 3.0), ("NVDA", date(2024, 6, 10), 10.0),
    })


def test_detects_forward_split_with_volume_confirmation():
    closes = [1200.0] * 25 + [121.0] * 5
    opens = [1200.0] * 25 + [120.4] + [121.0] * 4
    volumes = [40_000_000] * 25 + [314_000_000] * 5
    splits = detect_splits(daily_frame("NVDA", closes, volumes, opens=opens))
    assert splits.to_dict("records") == [{"symbol": "NVDA", "day": date(2024, 5, 26), "ratio": 10.0, "factor": 0.1}]


def test_price_halving_without_volume_jump_is_not_a_split():
    closes = [100.0] * 25 + [50.0] * 5
    volumes = [1_000_000] * 30
    assert detect_splits(daily_frame("XYZ", closes, volumes)).empty


def test_detects_reverse_split():
    closes = [2.0] * 25 + [10.0] * 5
    volumes = [5_000_000] * 25 + [1_000_000] * 5
    splits = detect_splits(daily_frame("REV", closes, volumes))
    assert splits.to_dict("records") == [{"symbol": "REV", "day": date(2024, 5, 26), "ratio": 0.2, "factor": 5.0}]


def test_adjustment_factor_applies_only_before_split_day():
    splits = pd.DataFrame([{"symbol": "NVDA", "day": date(2024, 6, 10), "ratio": 10.0, "factor": 0.1}])
    days = pd.Series([date(2024, 6, 7), date(2024, 6, 10), date(2024, 6, 11)])
    assert adjustment_factors(splits, "NVDA", days).tolist() == [0.1, 1.0, 1.0]
    assert adjustment_factors(splits, "AAPL", days).tolist() == [1.0, 1.0, 1.0]


def test_daily_rth_summary_uses_regular_session_only():
    ts = pd.to_datetime(["2025-11-28T13:00:00Z", "2025-11-28T14:30:00Z", "2025-11-28T17:59:00Z", "2025-11-28T18:30:00Z"], utc=True)
    minutes = pd.DataFrame({"symbol": "SPY", "ts": ts, "open": [1.0, 2.0, 3.0, 4.0], "close": [1.5, 2.5, 3.5, 4.5], "volume": [10, 20, 30, 40]})
    out = daily_rth_summary(minutes)
    assert out.to_dict("records") == [{"symbol": "SPY", "day": date(2025, 11, 28), "rth_open": 2.0, "rth_close": 3.5, "rth_volume": 50}]


def test_write_and_load_splits_roundtrip(tmp_path):
    splits = pd.DataFrame([{"symbol": "NVDA", "day": date(2024, 6, 10), "ratio": 10.0, "factor": 0.1}])
    path = write_splits(splits, root=tmp_path)
    assert path == tmp_path / "corporate_actions" / "splits.parquet"
    assert load_splits(root=tmp_path).to_dict("records") == splits.to_dict("records")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/options_research/test_corporate_actions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.options_research.corporate_actions'`

- [ ] **Step 3: Write minimal implementation**

`src/options_research/corporate_actions.py`:

```python
"""Split detection from raw (unadjusted) minute bars and price/volume adjustment factors (spec §5.1)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.options_research.config import TZ_ET, lake_root
from src.options_research.market_calendar import get_session

SPLIT_RATIOS = (2, 3, 4, 5, 10, 15, 20)
EXPECTED_SPLITS: frozenset[tuple[str, date, float]] = frozenset({
    ("NVDA", date(2021, 7, 20), 4.0),
    ("AMZN", date(2022, 6, 6), 20.0),
    ("GOOGL", date(2022, 7, 18), 20.0),
    ("TSLA", date(2022, 8, 25), 3.0),
    ("NVDA", date(2024, 6, 10), 10.0),
})
SPLIT_COLUMNS = ["symbol", "day", "ratio", "factor"]


def daily_rth_summary(minutes: pd.DataFrame) -> pd.DataFrame:
    frame = minutes.assign(ts_et=minutes["ts"].dt.tz_convert(TZ_ET))
    frame["day"] = frame["ts_et"].dt.date
    closes = {d: get_session(d) for d in frame["day"].unique()}
    in_rth = [
        closes[d] is not None and closes[d].open_et <= t < closes[d].close_et
        for d, t in zip(frame["day"], frame["ts_et"])
    ]
    rth = frame[np.array(in_rth, dtype=bool)].sort_values("ts")
    summary = rth.groupby(["symbol", "day"], sort=True).agg(
        rth_open=("open", "first"), rth_close=("close", "last"), rth_volume=("volume", "sum")
    ).reset_index()
    summary["rth_volume"] = summary["rth_volume"].astype("int64")
    return summary


def detect_splits(daily: pd.DataFrame, tol: float = 0.03) -> pd.DataFrame:
    found: list[dict] = []
    for symbol, group in daily.sort_values(["symbol", "day"]).groupby("symbol", sort=True):
        group = group.reset_index(drop=True)
        prior_close = group["rth_close"].shift(1)
        median_volume = group["rth_volume"].shift(1).rolling(20, min_periods=5).median()
        for i in range(1, len(group)):
            if not median_volume.iloc[i] or np.isnan(median_volume.iloc[i]):
                continue
            price_ratio = prior_close.iloc[i] / group.loc[i, "rth_open"]
            volume_ratio = group.loc[i, "rth_volume"] / median_volume.iloc[i]
            for r in SPLIT_RATIOS:
                if abs(price_ratio / r - 1) <= tol and volume_ratio >= max(1.5, 0.5 * r):
                    found.append({"symbol": symbol, "day": group.loc[i, "day"], "ratio": float(r), "factor": 1.0 / r})
                    break
                if abs(price_ratio * r - 1) <= tol and volume_ratio <= 2.0 / r:
                    found.append({"symbol": symbol, "day": group.loc[i, "day"], "ratio": 1.0 / r, "factor": float(r)})
                    break
    return pd.DataFrame(found, columns=SPLIT_COLUMNS)


def adjustment_factors(splits: pd.DataFrame, symbol: str, days: pd.Series) -> pd.Series:
    factors = pd.Series(1.0, index=days.index)
    for _, split in splits[splits["symbol"] == symbol].iterrows():
        factors[days < split["day"]] *= split["factor"]
    return factors


def write_splits(df: pd.DataFrame, root: Path | None = None) -> Path:
    path = (root or lake_root()) / "corporate_actions" / "splits.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def load_splits(root: Path | None = None) -> pd.DataFrame:
    frame = pd.read_parquet((root or lake_root()) / "corporate_actions" / "splits.parquet")
    frame["day"] = pd.to_datetime(frame["day"]).dt.date
    return frame[SPLIT_COLUMNS]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/options_research/test_corporate_actions.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/options_research/corporate_actions.py tests/options_research/test_corporate_actions.py
git commit -F- <<'EOF'
feat(options_research): split detection and adjustment factors

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 10: Lake store with holdout guard

**Files:**
- Create: `src/options_research/store.py`
- Test: `tests/options_research/test_store.py`

**Interfaces:**
- Consumes: `config.HOLDOUT`, `lake_root`; `stocks.day_path`, `STOCK_COLUMNS`
- Produces:
  - `HoldoutAccessError(RuntimeError)`
  - `guard_period(start: date, end: date, holdout: bool) -> None`
  - `stock_minute_files(symbols: Iterable[str], start: date, end: date, root: Path | None = None) -> list[Path]`
  - `load_stock_minutes(symbols: Iterable[str], start: date, end: date, holdout: bool = False, root: Path | None = None) -> pd.DataFrame`
    - `STOCK_COLUMNS`, sorted by `symbol, ts`, with `ts` in UTC

- [ ] **Step 1: Write the failing test**

`tests/options_research/test_store.py`:

```python
from datetime import date

import pandas as pd
import pytest

from src.options_research.stocks import STOCK_COLUMNS, write_day
from src.options_research.store import HoldoutAccessError, guard_period, load_stock_minutes, stock_minute_files


def lake_day(root, symbol, iso_ts, close):
    frame = pd.DataFrame({
        "symbol": [symbol], "ts": pd.to_datetime([iso_ts], utc=True), "open": [close], "high": [close], "low": [close],
        "close": [close], "volume": [100], "transactions": [1], "bad_high": [False], "bad_low": [False], "bad_close": [False],
        "high_clean": [close], "low_clean": [close], "source": ["zip"],
    })
    write_day(frame, pd.Timestamp(iso_ts).tz_convert("America/New_York").date(), root)


def test_guard_blocks_ranges_touching_holdout():
    guard_period(date(2025, 1, 2), date(2025, 12, 31), holdout=False)
    with pytest.raises(HoldoutAccessError):
        guard_period(date(2025, 12, 1), date(2026, 1, 2), holdout=False)
    guard_period(date(2026, 1, 2), date(2026, 9, 11), holdout=True)


def test_loader_refuses_holdout_without_flag(tmp_path):
    with pytest.raises(HoldoutAccessError):
        load_stock_minutes(["SPY"], date(2026, 1, 2), date(2026, 1, 5), root=tmp_path)


def test_loads_filtered_sorted_utc(tmp_path):
    lake_day(tmp_path, "SPY", "2025-06-11T13:31:00Z", 600.0)
    lake_day(tmp_path, "QQQ", "2025-06-11T13:30:00Z", 500.0)
    lake_day(tmp_path, "SPY", "2025-06-12T13:30:00Z", 601.0)
    lake_day(tmp_path, "SPY", "2025-07-01T13:30:00Z", 610.0)
    files = stock_minute_files(["SPY", "QQQ"], date(2025, 6, 11), date(2025, 6, 12), root=tmp_path)
    assert len(files) == 3
    df = load_stock_minutes(["SPY", "QQQ"], date(2025, 6, 11), date(2025, 6, 12), root=tmp_path)
    assert list(df.columns) == STOCK_COLUMNS
    assert df[["symbol", "close"]].values.tolist() == [["QQQ", 500.0], ["SPY", 600.0], ["SPY", 601.0]]
    assert str(df["ts"].dt.tz) == "UTC"
    assert df["ts"].iloc[1] == pd.Timestamp("2025-06-11T13:31:00Z")


def test_empty_range_returns_schema(tmp_path):
    df = load_stock_minutes(["SPY"], date(2025, 1, 2), date(2025, 1, 3), root=tmp_path)
    assert list(df.columns) == STOCK_COLUMNS and df.empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/options_research/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.options_research.store'`

- [ ] **Step 3: Write minimal implementation**

`src/options_research/store.py`:

```python
"""Lake loaders with the holdout guard (spec §9.1)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from src.options_research.config import HOLDOUT, lake_root
from src.options_research.stocks import STOCK_COLUMNS


class HoldoutAccessError(RuntimeError):
    """Raised when a range touching the holdout is requested without holdout=True."""


def guard_period(start: date, end: date, holdout: bool) -> None:
    if not holdout and end >= HOLDOUT[0]:
        raise HoldoutAccessError(
            f"{start}..{end} overlaps the holdout starting {HOLDOUT[0]}; pass holdout=True only for "
            "data validation, split detection, cost calibration, or the frozen holdout run"
        )


def stock_minute_files(symbols: Iterable[str], start: date, end: date, root: Path | None = None) -> list[Path]:
    base = (root or lake_root()) / "stock_1m"
    files: list[Path] = []
    for symbol in symbols:
        for year in range(start.year, end.year + 1):
            year_dir = base / symbol / str(year)
            if not year_dir.exists():
                continue
            files.extend(p for p in sorted(year_dir.glob("*.parquet")) if start <= date.fromisoformat(p.stem) <= end)
    return files


def load_stock_minutes(
    symbols: Iterable[str],
    start: date,
    end: date,
    holdout: bool = False,
    root: Path | None = None,
) -> pd.DataFrame:
    guard_period(start, end, holdout)
    files = stock_minute_files(symbols, start, end, root=root)
    if not files:
        return pd.DataFrame(columns=STOCK_COLUMNS)
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        frame = con.read_parquet([p.as_posix() for p in files]).order("symbol, ts").df()
    finally:
        con.close()
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame[STOCK_COLUMNS].reset_index(drop=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/options_research/test_store.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/options_research/store.py tests/options_research/test_store.py
git commit -F- <<'EOF'
feat(options_research): DuckDB lake loader with holdout guard

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 11: Cost model (M2)

**Files:**
- Create: `src/options_research/costs.py`
- Test: `tests/options_research/test_costs.py`

**Interfaces:**
- Consumes: `config.TZ_ET`, `lake_root`
- Produces:
  - `COST_KEYS = ["underlying", "dte_bucket", "moneyness", "premium", "tod_bucket"]`, `MIN_CELL_N = 30`
  - Bucket functions:
    - `dte_bucket(dte: int) -> str`: `'0' | '1-2' | '3-7' | '8+'`
    - `moneyness_bucket(otm_pct: float) -> str`: `'ITM' | 'ATM' | 'OTM1' | 'OTM2'`; otm_pct > 0 means OTM, in %
    - `otm_pct(strike: float, spot: float, option_type: str) -> float`
    - `premium_bucket(mid: float) -> str`: `'<1' | '1-3' | '3-10' | '10+'`
    - `tod_bucket(t: time) -> str`: `'open' | 'mid' | 'close'`
  - `SCHWAB_COST_SQL: str`
  - `build_cost_table(conn, underlyings, start: datetime, end: datetime) -> pd.DataFrame`
    - columns `COST_KEYS + ["n", "half_spread", "mid"]`; rolled-up levels have `None` in the trailing keys
  - `scale_half_spread(h: float, rv_prev: float | None, rv_cal: float | None, in_event_window: bool, floor: float = 0.005) -> float`
  - `CostModel(table: pd.DataFrame, fees_per_side: float = 0.05, min_half_spread: float = 0.005)`, with methods:
    - `.base_half_spread(underlying, dte, otm, premium, tod) -> tuple[float, int]`, returning `(h, level)`
    - `.half_spread(underlying, dte, otm, premium, tod, rv_prev=None, rv_cal=None, in_event_window=False) -> float`
  - `session_realized_vol(minutes: pd.DataFrame) -> pd.Series`: index is ET date, name `rv`
  - Persistence:
    - `save_cost_table(df, root=None) -> Path`, i.e. `costs/half_spread_table.parquet`
    - `save_calibration(payload: dict, root=None) -> Path`, i.e. `costs/calibration.json`
    - `load_cost_model(root=None, fees_per_side=0.05) -> CostModel`

- [ ] **Step 1: Write the failing test**

`tests/options_research/test_costs.py`:

```python
from datetime import time

import pandas as pd
import pytest

from src.options_research.costs import (
    COST_KEYS,
    CostModel,
    dte_bucket,
    load_cost_model,
    moneyness_bucket,
    otm_pct,
    premium_bucket,
    save_cost_table,
    scale_half_spread,
    session_realized_vol,
    tod_bucket,
)


@pytest.mark.parametrize("dte,expected", [(0, "0"), (1, "1-2"), (2, "1-2"), (3, "3-7"), (7, "3-7"), (8, "8+")])
def test_dte_bucket(dte, expected):
    assert dte_bucket(dte) == expected


@pytest.mark.parametrize("pct,expected", [(-0.51, "ITM"), (-0.5, "ATM"), (0.5, "ATM"), (0.51, "OTM1"), (2.0, "OTM1"), (2.01, "OTM2")])
def test_moneyness_bucket(pct, expected):
    assert moneyness_bucket(pct) == expected


def test_otm_pct_sign_convention():
    assert otm_pct(606.0, 600.0, "call") == pytest.approx(1.0)
    assert otm_pct(594.0, 600.0, "put") == pytest.approx(1.0)
    assert otm_pct(594.0, 600.0, "CALL") == pytest.approx(-1.0)


@pytest.mark.parametrize("mid,expected", [(0.99, "<1"), (1.0, "1-3"), (2.99, "1-3"), (3.0, "3-10"), (10.0, "10+")])
def test_premium_bucket(mid, expected):
    assert premium_bucket(mid) == expected


@pytest.mark.parametrize("t,expected", [(time(9, 30), "open"), (time(9, 59), "open"), (time(10, 0), "mid"), (time(14, 59), "mid"), (time(15, 0), "close")])
def test_tod_bucket(t, expected):
    assert tod_bucket(t) == expected


def table(rows):
    return pd.DataFrame(rows, columns=COST_KEYS + ["n", "half_spread", "mid"])


SAMPLE = table([
    ("SPY", "1-2", "ATM", "1-3", "mid", 120, 0.010, 2.6),
    ("SPY", "1-2", "ATM", "1-3", "open", 10, 0.050, 2.6),
    ("SPY", "1-2", "ATM", "1-3", None, 200, 0.012, 2.6),
    ("SPY", "1-2", "ATM", None, None, 400, 0.015, 2.0),
    ("SPY", "1-2", None, None, None, 900, 0.020, 3.0),
    ("SPY", None, None, None, None, 5000, 0.030, 4.0),
])


def test_exact_cell_used_when_populated():
    model = CostModel(SAMPLE)
    assert model.base_half_spread("SPY", 2, 0.1, 2.5, time(11, 0)) == (0.010, 5)


def test_sparse_cell_backs_off_to_coarser_level():
    model = CostModel(SAMPLE)
    assert model.base_half_spread("SPY", 1, 0.2, 2.0, time(9, 45)) == (0.012, 4)
    assert model.base_half_spread("SPY", 1, 1.5, 2.0, time(11, 0)) == (0.020, 2)
    assert model.base_half_spread("SPY", 5, 0.0, 2.0, time(11, 0)) == (0.030, 1)


def test_unknown_underlying_raises():
    with pytest.raises(KeyError):
        CostModel(SAMPLE).base_half_spread("ZZZ", 1, 0.0, 2.0, time(11, 0))


def test_floor_applies():
    model = CostModel(table([("SPY", None, None, None, None, 100, 0.001, 0.2)]))
    assert model.half_spread("SPY", 0, 0.0, 0.2, time(11, 0)) == 0.005


@pytest.mark.parametrize("rv_prev,rv_cal,event,expected", [
    (None, None, False, 0.02), (0.5, 1.0, False, 0.02), (2.0, 1.0, False, 0.04), (9.0, 1.0, False, 0.06), (2.0, 1.0, True, 0.08),
])
def test_scale_half_spread(rv_prev, rv_cal, event, expected):
    assert scale_half_spread(0.02, rv_prev, rv_cal, event) == pytest.approx(expected)


def test_save_and_load_cost_model(tmp_path):
    path = save_cost_table(SAMPLE, root=tmp_path)
    assert path == tmp_path / "costs" / "half_spread_table.parquet"
    model = load_cost_model(root=tmp_path)
    assert model.fees_per_side == 0.05
    assert model.base_half_spread("SPY", 2, 0.1, 2.5, time(11, 0)) == (0.010, 5)


def test_session_realized_vol_uses_rth_log_returns():
    ts = pd.to_datetime(["2025-06-11T13:29:00Z", "2025-06-11T13:30:00Z", "2025-06-11T13:31:00Z", "2025-06-11T13:32:00Z"], utc=True)
    minutes = pd.DataFrame({"symbol": "SPY", "ts": ts, "close": [50.0, 100.0, 101.0, 100.0]})
    rv = session_realized_vol(minutes)
    import numpy as np
    expected = pd.Series([np.log(101 / 100), np.log(100 / 101)]).std() * np.sqrt(390)
    assert rv.name == "rv"
    assert rv.loc[pd.Timestamp("2025-06-11").date()] == pytest.approx(expected)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/options_research/test_costs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.options_research.costs'`

- [ ] **Step 3: Write minimal implementation**

`src/options_research/costs.py`:

```python
"""Option half-spread cost model calibrated from Schwab quotes in the sibling DB (spec §5.6)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

import numpy as np
import pandas as pd

from src.options_research.config import TZ_ET, lake_root

COST_KEYS = ["underlying", "dte_bucket", "moneyness", "premium", "tod_bucket"]
MIN_CELL_N = 30


def dte_bucket(dte: int) -> str:
    if dte <= 0:
        return "0"
    if dte <= 2:
        return "1-2"
    if dte <= 7:
        return "3-7"
    return "8+"


def otm_pct(strike: float, spot: float, option_type: str) -> float:
    if option_type.lower().startswith("c"):
        return (strike / spot - 1.0) * 100.0
    return (1.0 - strike / spot) * 100.0


def moneyness_bucket(otm: float) -> str:
    if otm < -0.5:
        return "ITM"
    if otm <= 0.5:
        return "ATM"
    if otm <= 2.0:
        return "OTM1"
    return "OTM2"


def premium_bucket(mid: float) -> str:
    if mid < 1.0:
        return "<1"
    if mid < 3.0:
        return "1-3"
    if mid < 10.0:
        return "3-10"
    return "10+"


def tod_bucket(t: time) -> str:
    if t < time(10, 0):
        return "open"
    if t < time(15, 0):
        return "mid"
    return "close"


SCHWAB_COST_SQL = """
WITH x AS (
    SELECT underlying,
           dte,
           CASE WHEN lower(option_type) LIKE 'c%%' THEN (strike / underlying_spot - 1) * 100
                ELSE (1 - strike / underlying_spot) * 100 END AS otm,
           (bid + ask) / 2 AS mid,
           (ask - bid) / 2 AS half_spread,
           (bucket_time AT TIME ZONE 'America/New_York')::time AS tod
    FROM contract_greeks
    WHERE underlying = ANY(%(underlyings)s)
      AND snapshot_time >= %(start)s AND snapshot_time < %(end)s
      AND bid > 0 AND ask > bid AND underlying_spot > 0
      AND dte BETWEEN 0 AND 45
      AND extract(minute FROM bucket_time)::int %% 15 = 0
), q AS (
    SELECT underlying,
           CASE WHEN dte = 0 THEN '0' WHEN dte <= 2 THEN '1-2' WHEN dte <= 7 THEN '3-7' ELSE '8+' END AS dte_bucket,
           CASE WHEN otm < -0.5 THEN 'ITM' WHEN otm <= 0.5 THEN 'ATM' WHEN otm <= 2 THEN 'OTM1' ELSE 'OTM2' END AS moneyness,
           CASE WHEN mid < 1 THEN '<1' WHEN mid < 3 THEN '1-3' WHEN mid < 10 THEN '3-10' ELSE '10+' END AS premium,
           CASE WHEN tod < time '10:00' THEN 'open' WHEN tod < time '15:00' THEN 'mid' ELSE 'close' END AS tod_bucket,
           half_spread, mid
    FROM x
    WHERE tod >= time '09:30' AND tod < time '16:00'
)
SELECT underlying, dte_bucket, moneyness, premium, tod_bucket,
       count(*) AS n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY half_spread) AS half_spread,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY mid) AS mid
FROM q
GROUP BY GROUPING SETS (
    (underlying, dte_bucket, moneyness, premium, tod_bucket),
    (underlying, dte_bucket, moneyness, premium),
    (underlying, dte_bucket, moneyness),
    (underlying, dte_bucket),
    (underlying)
)
"""


def build_cost_table(conn, underlyings, start: datetime, end: datetime) -> pd.DataFrame:
    rows = conn.execute(SCHWAB_COST_SQL, {"underlyings": list(underlyings), "start": start, "end": end}).fetchall()
    frame = pd.DataFrame(rows, columns=COST_KEYS + ["n", "half_spread", "mid"])
    frame["n"] = frame["n"].astype("int64")
    frame["half_spread"] = frame["half_spread"].astype(float)
    frame["mid"] = frame["mid"].astype(float)
    return frame


def scale_half_spread(h: float, rv_prev: float | None, rv_cal: float | None, in_event_window: bool, floor: float = 0.005) -> float:
    ratio = 1.0 if not rv_prev or not rv_cal else min(3.0, max(1.0, rv_prev / rv_cal))
    return max(floor, h * ratio * (2.0 if in_event_window else 1.0))


@dataclass
class CostModel:
    table: pd.DataFrame
    fees_per_side: float = 0.05
    min_half_spread: float = 0.005
    _lookup: dict = field(init=False, repr=False)

    def __post_init__(self) -> None:
        keys = self.table[COST_KEYS].astype(object).where(self.table[COST_KEYS].notna(), None)
        self._lookup = {
            tuple(key): (int(n), float(h))
            for key, n, h in zip(keys.itertuples(index=False, name=None), self.table["n"], self.table["half_spread"])
        }

    def base_half_spread(self, underlying: str, dte: int, otm: float, premium: float, tod: time) -> tuple[float, int]:
        full = (underlying, dte_bucket(dte), moneyness_bucket(otm), premium_bucket(premium), tod_bucket(tod))
        for level in (5, 4, 3, 2, 1):
            hit = self._lookup.get(full[:level] + (None,) * (5 - level))
            if hit and hit[0] >= MIN_CELL_N:
                return max(hit[1], self.min_half_spread), level
        raise KeyError(f"no cost cell for {underlying}")

    def half_spread(
        self,
        underlying: str,
        dte: int,
        otm: float,
        premium: float,
        tod: time,
        rv_prev: float | None = None,
        rv_cal: float | None = None,
        in_event_window: bool = False,
    ) -> float:
        h, _ = self.base_half_spread(underlying, dte, otm, premium, tod)
        return scale_half_spread(h, rv_prev, rv_cal, in_event_window, floor=self.min_half_spread)


def session_realized_vol(minutes: pd.DataFrame) -> pd.Series:
    et = minutes["ts"].dt.tz_convert(TZ_ET)
    minute_of_day = et.dt.hour * 60 + et.dt.minute
    mask = (minute_of_day >= 570) & (minute_of_day < 960)
    rth = minutes.loc[mask].assign(day=et[mask].dt.date).sort_values("ts")
    log_returns = rth.groupby("day")["close"].transform(lambda s: np.log(s.astype(float)).diff())
    return log_returns.groupby(rth["day"]).std().mul(np.sqrt(390)).rename("rv")


def save_cost_table(df: pd.DataFrame, root: Path | None = None) -> Path:
    path = (root or lake_root()) / "costs" / "half_spread_table.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def save_calibration(payload: dict, root: Path | None = None) -> Path:
    path = (root or lake_root()) / "costs" / "calibration.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def load_cost_model(root: Path | None = None, fees_per_side: float = 0.05) -> CostModel:
    table = pd.read_parquet((root or lake_root()) / "costs" / "half_spread_table.parquet")
    return CostModel(table, fees_per_side=fees_per_side)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/options_research/test_costs.py -v`
Expected: 34 passed (the parametrized cases count individually)

- [ ] **Step 5: Commit**

```bash
git add src/options_research/costs.py tests/options_research/test_costs.py
git commit -F- <<'EOF'
feat(options_research): Schwab-calibrated half-spread cost model with backoff and scaling

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 12: Reports and CLI

**Files:**
- Create: `src/options_research/reports.py`
- Create: `src/options_research/cli.py`
- Create: `src/options_research/__main__.py`
- Test: `tests/options_research/test_reports_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `m1_report(root: Path | None = None) -> str`
  - `m2_report(root: Path | None = None) -> str`
  - `write_report(name: str, text: str, directory: Path | None = None) -> Path`
  - `cli.main(argv: list[str] | None = None) -> int`
- CLI commands:
  - `ingest-stocks`, `ingest-tail`, `detect-splits`, `build-events`, `build-costs`
  - `report-m1`, `report-m2`
- Lake artifacts read by the reports:
  - `validation/zip_vs_alpaca.json`
  - `corporate_actions/splits.parquet`
  - `calendar/events.parquet`, `calendar/events_notes.json`
  - `costs/half_spread_table.parquet`, `costs/calibration.json`

- [ ] **Step 1: Write the failing test**

`tests/options_research/test_reports_cli.py`:

```python
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
        "volume": [100, 200], "transactions": [1, 2], "bad_high": [True, False], "bad_low": [False, False], "bad_close": [False, False],
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


def test_m1_report_sections(tmp_path):
    seed_lake(tmp_path)
    text = m1_report(root=tmp_path)
    for heading in ("# M1 Data Foundation Report", "## Stock minute coverage", "## Bad prints", "## Splits", "## Zip vs Alpaca overlap", "## Events", "## Earnings spot-check"):
        assert heading in text
    assert "NVDA" in text and "2024-06-10" in text
    assert "missing expected" in text  # the seeded lake lacks 4 of the 5 expected splits
    assert "skipped: FRED_API_KEY not set" in text


def test_m2_report_sections(tmp_path):
    seed_lake(tmp_path)
    text = m2_report(root=tmp_path)
    assert "# M2 Cost Model Report" in text
    assert "rv_cal" in text and "0.12" in text
    assert "SPY" in text and "1-2" in text


def test_write_report(tmp_path):
    path = write_report("m1_data_foundation", "# hi\n", directory=tmp_path)
    assert path == tmp_path / "m1_data_foundation.md" and path.read_text() == "# hi\n"


def test_cli_report_commands_write_files(tmp_path, monkeypatch):
    seed_lake(tmp_path / "lake")
    monkeypatch.setenv("OPTIONS_LAKE_ROOT", str(tmp_path / "lake"))
    monkeypatch.setenv("OPTIONS_REPORTS_DIR", str(tmp_path / "reports"))
    assert cli.main(["report-m1"]) == 0
    assert cli.main(["report-m2"]) == 0
    assert (tmp_path / "reports" / "m1_data_foundation.md").exists()
    assert (tmp_path / "reports" / "m2_cost_model.md").exists()


def test_cli_requires_a_command():
    import pytest
    with pytest.raises(SystemExit):
        cli.main([])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/options_research/test_reports_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.options_research.reports'`

- [ ] **Step 3: Write minimal implementation**

`src/options_research/reports.py`:

```python
"""M1 (data foundation) and M2 (cost model) Markdown reports — aggregates only, safe to commit."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from src.options_research.config import lake_root, reports_dir
from src.options_research.corporate_actions import EXPECTED_SPLITS, load_splits
from src.options_research.events_sources import load_events


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _stock_aggregates(root: Path) -> pd.DataFrame:
    pattern = (root / "stock_1m" / "*" / "*" / "*.parquet").as_posix()
    if not list((root / "stock_1m").glob("*/*/*.parquet")):
        return pd.DataFrame(columns=["symbol", "year", "days", "rows", "bad_high", "bad_low"])
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        return con.execute(
            f"""
            SELECT symbol, year(ts) AS year, count(DISTINCT CAST(ts AS DATE)) AS days, count(*) AS rows,
                   sum(CAST(bad_high AS INTEGER)) AS bad_high, sum(CAST(bad_low AS INTEGER)) AS bad_low
            FROM read_parquet('{pattern}')
            GROUP BY 1, 2 ORDER BY 1, 2
            """
        ).df()
    finally:
        con.close()


def m1_report(root: Path | None = None) -> str:
    root = root or lake_root()
    stocks = _stock_aggregates(root)
    lines = ["# M1 Data Foundation Report", ""]

    lines += ["## Stock minute coverage", ""]
    if stocks.empty:
        lines.append("No stock minute files found.")
    else:
        lines.append(stocks.pivot(index="symbol", columns="year", values="days").fillna(0).astype(int).to_markdown())
    lines.append("")

    lines += ["## Bad prints", ""]
    if not stocks.empty:
        lines.append(stocks.assign(flagged=stocks["bad_high"] + stocks["bad_low"]).pivot(index="symbol", columns="year", values="flagged").fillna(0).astype(int).to_markdown())
    lines.append("")

    lines += ["## Splits", ""]
    splits_path = root / "corporate_actions" / "splits.parquet"
    detected = load_splits(root) if splits_path.exists() else pd.DataFrame(columns=["symbol", "day", "ratio", "factor"])
    lines.append(detected.to_markdown(index=False) if not detected.empty else "No splits detected.")
    found = {(r.symbol, r.day, float(r.ratio)) for r in detected.itertuples()}
    missing = sorted(EXPECTED_SPLITS - found)
    extra = sorted(found - EXPECTED_SPLITS)
    lines += ["", f"- missing expected: {missing if missing else 'none'}", f"- additional detections to confirm manually: {extra if extra else 'none'}", ""]

    lines += ["## Zip vs Alpaca overlap", ""]
    overlap = _read_json(root / "validation" / "zip_vs_alpaca.json")
    lines.append(pd.DataFrame(overlap).T.to_markdown() if overlap else "Not run.")
    lines.append("")

    lines += ["## Events", ""]
    notes = _read_json(root / "calendar" / "events_notes.json")
    lines.append(f"- FRED: {notes.get('fred', 'unknown')}")
    events_path = root / "calendar" / "events.parquet"
    events = load_events(root) if events_path.exists() else pd.DataFrame(columns=["date", "type", "ticker"])
    if not events.empty:
        years = pd.to_datetime(events["date"]).dt.year
        lines += ["", events.groupby(["type", years]).size().unstack(fill_value=0).to_markdown()]
    lines.append("")

    lines += ["## Earnings spot-check", "", "Verify each row against the issuer's investor-relations page and tick the box.", ""]
    earnings = events[events["type"].astype(str).str.startswith("earnings")] if not events.empty else events
    if not earnings.empty:
        sample = earnings.sample(n=min(10, len(earnings)), random_state=7).sort_values("date")
        lines.append(sample.assign(verified="[ ]")[["ticker", "date", "type", "verified"]].to_markdown(index=False))
    lines.append("")
    return "\n".join(lines)


def m2_report(root: Path | None = None) -> str:
    root = root or lake_root()
    table = pd.read_parquet(root / "costs" / "half_spread_table.parquet")
    calibration = _read_json(root / "costs" / "calibration.json")
    level = table[["dte_bucket", "moneyness", "premium", "tod_bucket"]].notna().sum(axis=1) + 1
    lines = ["# M2 Cost Model Report", "", "## Calibration", ""]
    lines += [f"- {k}: {v}" for k, v in calibration.items()]
    lines += ["", "## Cells by level (n >= 30 usable)", ""]
    lines.append(table.assign(level=level, usable=table["n"] >= 30).groupby("level")["usable"].agg(["count", "sum"]).rename(columns={"count": "cells", "sum": "usable"}).to_markdown())
    atm = table[(level == 3) & (table["moneyness"] == "ATM")].copy()
    lines += ["", "## ATM full spread as % of median mid (level 3: underlying x DTE x moneyness)", ""]
    if atm.empty:
        lines.append("No level-3 ATM cells.")
    else:
        atm["spread_pct"] = (200.0 * atm["half_spread"] / atm["mid"]).round(2)
        lines.append(atm.pivot(index="underlying", columns="dte_bucket", values="spread_pct").to_markdown())
    lines += ["", "Stress multipliers applied in stage 2: h x 1.5 and h x 2.0 (spec §5.6).", ""]
    return "\n".join(lines)


def write_report(name: str, text: str, directory: Path | None = None) -> Path:
    directory = directory or reports_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(text)
    return path
```

`src/options_research/cli.py`:

```python
"""Command line for the options research data foundation: `uv run python -m src.options_research <command>`."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

from src.options_research.config import DATA_FREEZE, REPO_ROOT, UNIVERSE, ZIP_END, ZIP_START, equity_zip_path, lake_root


def _cmd_ingest_stocks(args: argparse.Namespace) -> int:
    from src.options_research.stocks import ingest_zip

    print(json.dumps(ingest_zip(equity_zip_path(), args.start, args.end, workers=args.workers, overwrite=args.overwrite)))
    return 0


def _cmd_ingest_tail(args: argparse.Namespace) -> int:
    from src.options_research.alpaca_data import AlpacaDataClient
    from src.options_research.stocks_alpaca import ingest_alpaca_tail, validate_zip_overlap

    client = AlpacaDataClient()
    print(json.dumps(ingest_alpaca_tail(client, args.start, args.end, overwrite=args.overwrite)))
    sample_days = [date(2022, 1, 11), date(2024, 3, 15), date(2025, 6, 11), date(2026, 6, 1), ZIP_END]
    overlap = validate_zip_overlap(client, sample_days)
    path = lake_root() / "validation" / "zip_vs_alpaca.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overlap, indent=2))
    print(json.dumps(overlap))
    return 0


def _cmd_detect_splits(args: argparse.Namespace) -> int:
    import pandas as pd

    from src.options_research.corporate_actions import daily_rth_summary, detect_splits, write_splits
    from src.options_research.store import load_stock_minutes

    summaries = []
    for symbol in UNIVERSE:
        # Split-detection exception to the holdout guard (spec §9.1): corporate actions only, no strategy metrics.
        minutes = load_stock_minutes([symbol], ZIP_START, DATA_FREEZE, holdout=True)
        summaries.append(daily_rth_summary(minutes))
    splits = detect_splits(pd.concat(summaries, ignore_index=True))
    print(write_splits(splits))
    print(splits.to_string(index=False))
    return 0


def _cmd_build_events(args: argparse.Namespace) -> int:
    from src.options_research.events_sources import build_events, write_events

    events, notes = build_events(ZIP_START, DATA_FREEZE, os.environ.get("FRED_API_KEY"))
    print(write_events(events, notes))
    print(json.dumps(notes))
    return 0


def _cmd_build_costs(args: argparse.Namespace) -> int:
    import psycopg

    from src.options_research.costs import build_cost_table, save_calibration, save_cost_table, session_realized_vol
    from src.options_research.store import load_stock_minutes

    start = datetime.combine(args.start, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(args.end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    with psycopg.connect(os.environ["OPTIONS_DB_URL"]) as conn:
        table = build_cost_table(conn, UNIVERSE, start, end)
    print(save_cost_table(table))
    # Cost-calibration exception to the holdout guard (spec §9.1): SPY realized vol for spread scaling only.
    spy = load_stock_minutes(["SPY"], args.start, args.end, holdout=True)
    rv = session_realized_vol(spy)
    payload = {"rv_cal": float(rv.median()) if len(rv) else None, "sessions": int(len(rv)), "window": f"{args.start}..{args.end}", "cells": int(len(table))}
    print(save_calibration(payload))
    print(json.dumps(payload))
    return 0


def _cmd_report_m1(args: argparse.Namespace) -> int:
    from src.options_research.reports import m1_report, write_report

    print(write_report("m1_data_foundation", m1_report()))
    return 0


def _cmd_report_m2(args: argparse.Namespace) -> int:
    from src.options_research.reports import m2_report, write_report

    print(write_report("m2_cost_model", m2_report()))
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(prog="python -m src.options_research")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest-stocks", help="zip minute bars -> lake")
    p.add_argument("--start", type=date.fromisoformat, default=ZIP_START)
    p.add_argument("--end", type=date.fromisoformat, default=ZIP_END)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=_cmd_ingest_stocks)

    p = sub.add_parser("ingest-tail", help="Alpaca SIP minute bars after the zip + overlap validation")
    p.add_argument("--start", type=date.fromisoformat, default=ZIP_END + timedelta(days=1))
    p.add_argument("--end", type=date.fromisoformat, default=DATA_FREEZE)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=_cmd_ingest_tail)

    sub.add_parser("detect-splits", help="detect splits from lake minutes").set_defaults(func=_cmd_detect_splits)
    sub.add_parser("build-events", help="events table (FRED needs FRED_API_KEY)").set_defaults(func=_cmd_build_events)

    p = sub.add_parser("build-costs", help="half-spread table from Schwab quotes + RV calibration")
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 8, 21))
    p.add_argument("--end", type=date.fromisoformat, default=DATA_FREEZE)
    p.set_defaults(func=_cmd_build_costs)

    sub.add_parser("report-m1").set_defaults(func=_cmd_report_m1)
    sub.add_parser("report-m2").set_defaults(func=_cmd_report_m2)

    args = parser.parse_args(argv)
    return args.func(args)
```

`src/options_research/__main__.py`:

```python
from src.options_research.cli import main

if __name__ == "__main__":  # required on Windows: ingest-stocks uses a process pool
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/options_research/test_reports_cli.py -v`
Expected: 5 passed

Run: `uv run pytest -q`
Expected: all tests pass (97 pre-existing + all `tests/options_research` unit tests)

- [ ] **Step 5: Commit**

```bash
git add src/options_research/reports.py src/options_research/cli.py src/options_research/__main__.py tests/options_research/test_reports_cli.py
git commit -F- <<'EOF'
feat(options_research): M1/M2 reports and data-foundation CLI

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

---

### Task 13: Run the real pipeline, integration checks, reports, docs

**Files:**
- Create: `tests/options_research/test_integration_data.py`
- Create (generated): `reports/options_research/m1_data_foundation.md`, `reports/options_research/m2_cost_model.md`
- Modify: `CLAUDE.md` (add an "Options research" subsection under "Commands")

**Interfaces:**
- Consumes: CLI commands from Task 12; `store.load_stock_minutes`, `corporate_actions.EXPECTED_SPLITS` / `load_splits`, `costs.load_cost_model`
- Produces: a populated lake, committed reports, integration tests that pass locally

**Preconditions:**
- `.env` has `ALPACA_DATA_API_KEY`, `ALPACA_DATA_SECRET_KEY` and `OPTIONS_DB_URL` (present).
- `FRED_API_KEY` is optional; without it the events notes say "skipped". **Ask the user for it
  before this task if it's not in `.env`.**

- [ ] **Step 1: Write the integration tests**

`tests/options_research/test_integration_data.py`:

```python
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
```

- [ ] **Step 2: Ingest the zip** (one-time, roughly 30–90 minutes; resumable because re-runs skip existing days)

Run: `PYTHONIOENCODING=utf-8 uv run python -m src.options_research ingest-stocks --workers 4`
Expected: one JSON line with `"days_available": 1256` and `"rows"` in the tens of millions. A re-run shows `"days_written": 0`.

- [ ] **Step 3: Ingest the Alpaca tail and validate the overlap**

Run: `PYTHONIOENCODING=utf-8 uv run python -m src.options_research ingest-tail`
Expected:
- a JSON summary with `sessions` ≈ 60
- an overlap JSON for 5 sample days, each with `compared` > 1000 and `ohlc_mismatch` 0 or near 0

If mismatches are material (≥ 0.1%), stop and report them to the user with examples before
continuing.

- [ ] **Step 4: Detect splits**

Run: `PYTHONIOENCODING=utf-8 uv run python -m src.options_research detect-splits`
Expected: the table includes all five `EXPECTED_SPLITS`. List any additional rows in the M1
report for user confirmation.

- [ ] **Step 5: Build events**

Run: `PYTHONIOENCODING=utf-8 uv run python -m src.options_research build-events`
Expected: `calendar/events.parquet` is written, and notes show `"fred": "included"` (or `skipped`
if no key).

- [ ] **Step 6: Build the cost model**

Run: `PYTHONIOENCODING=utf-8 uv run python -m src.options_research build-costs`
Expected: the table is saved, and calibration JSON shows `rv_cal` > 0, `sessions` ≈ 15, and
`cells` in the thousands. The SQL takes minutes because it scans `contract_greeks`.

- [ ] **Step 7: Run the integration tests**

Run: `uv run pytest -m integration tests/options_research/test_integration_data.py -v`
Expected: 5 passed. If `test_expected_splits_detected` fails, do not loosen the test. Inspect
`daily_rth_summary` for that symbol around the date and report the finding.

- [ ] **Step 8: Generate the reports**

Run: `PYTHONIOENCODING=utf-8 uv run python -m src.options_research report-m1 && PYTHONIOENCODING=utf-8 uv run python -m src.options_research report-m2`
Expected: `reports/options_research/m1_data_foundation.md` and `m2_cost_model.md` are written.
Open both and check that coverage has ~250 days per full year per ticker, splits match, the
overlap is clean, and ATM spread % looks like `docs/DATA_WAREHOUSE.md` (SPY/QQQ ~1–2%,
MSFT/GOOGL ~6–8%).

- [ ] **Step 9: Update CLAUDE.md**

In `CLAUDE.md`, directly after the paragraph that begins with ``docker/Dockerfile` installs from
`uv.lock``, insert:

````markdown
**Options research** (`src/options_research/`, spec in `docs/superpowers/specs/2026-09-12-options-edge-research-design.md`):

```bash
uv run python -m src.options_research ingest-stocks   # equity zip -> data/options_lake/stock_1m (resumable)
uv run python -m src.options_research ingest-tail     # Alpaca SIP minutes after 2026-06-18 + zip-vs-Alpaca check
uv run python -m src.options_research detect-splits
uv run python -m src.options_research build-events    # needs FRED_API_KEY for macro release dates
uv run python -m src.options_research build-costs     # Schwab quotes from the sibling DB (read-only)
uv run python -m src.options_research report-m1 && uv run python -m src.options_research report-m2
uv run pytest -m integration tests/options_research   # real-data checks (zip, lake, DB)
```

Loaders in `store.py` refuse holdout dates (>= 2026-01-02) unless `holdout=True`, which is
reserved for validation, split detection and cost calibration.
````

- [ ] **Step 10: Commit**

```bash
git add tests/options_research/test_integration_data.py reports/options_research/m1_data_foundation.md reports/options_research/m2_cost_model.md CLAUDE.md
git commit -F- <<'EOF'
feat(options_research): run M1/M2 pipeline, integration checks and reports

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012xibJDzZ1yhGr5MdZe4GEx
EOF
```

- [ ] **Step 11: Hand back to the user**

Summarize the M1/M2 reports for the user:
- coverage gaps
- split detections, including extras
- overlap mismatches
- FRED included or skipped
- ATM spread table
- the earnings spot-check rows still to verify

Then propose writing the M3 plan (features, setups, stage-1 evaluation).
