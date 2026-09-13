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
        ("data.alpaca.markets", "/v2/stocks/trades"),
        ("api.alpaca.markets", "/v2/options/contracts"),
    })


@pytest.mark.parametrize("url", [
    "https://api.alpaca.markets/v2/orders",
    "https://paper-api.alpaca.markets/v2/options/contracts",
    "http://data.alpaca.markets/v1beta1/options/bars",
    "https://data.alpaca.markets/v2/stocks/quotes",
    "https://data.alpaca.markets:9999/v1beta1/options/bars",
    "https://user@data.alpaca.markets/v1beta1/options/bars",
])
def test_rejects_non_allowlisted_urls_without_calling_http(url):
    calls = []
    client, _ = make_client(lambda request: calls.append(request) or httpx.Response(200, json={}))
    with pytest.raises(DisallowedEndpointError):
        client.get(url, {})
    assert calls == []
    with pytest.raises(DisallowedEndpointError):
        check_allowed(url)


def test_allows_explicit_default_https_port():
    check_allowed("https://data.alpaca.markets:443/v1beta1/options/bars")


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


def test_transport_error_retried_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"ok": True})

    client, clock = make_client(handler)
    assert client.get(BARS, {}) == {"ok": True}
    assert clock.sleeps == [1.0]
    assert calls["n"] == 2


def test_transport_error_gives_up_after_max_retries():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=request)

    client, _ = make_client(handler, max_retries=2)
    with pytest.raises(httpx.ConnectError):
        client.get(BARS, {})
    assert calls["n"] == 3


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
