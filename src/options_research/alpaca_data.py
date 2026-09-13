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
    if (
        parts.scheme != "https"
        or (parts.hostname, parts.path) not in ALLOWED_ENDPOINTS
        or parts.port not in (None, 443)
        or parts.username is not None
        or parts.password is not None
    ):
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
            try:
                response = self._http.request("GET", url, params=params, headers=self._headers)
            except httpx.TransportError:
                if attempt < self._max_retries:
                    self._sleep(min(60.0, 2.0 ** attempt))
                    continue
                raise
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
