"""Shared fixtures for safety tests. All real network access is blocked."""

import os

# Some root scripts resolve Alpaca headers at import time. Provide dummy keys so they import;
# they are never sent anywhere because all HTTP is blocked below.
for _key, _value in (
    ("ALPACA_API_KEY", "test-key"),
    ("ALPACA_API_SECRET", "test-secret"),
    ("ALPACA_DAY_API_KEY", "test-day-key"),
    ("ALPACA_DAY_API_SECRET", "test-day-secret"),
):
    if not os.environ.get(_key):
        os.environ[_key] = _value

import httpx
import pytest
import requests


class NetworkBlocked(RuntimeError):
    pass


def _blocked(*args, **kwargs):
    raise NetworkBlocked(f"Real network call attempted in safety test: args={args!r}")


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Fail loudly on any real HTTP call. Tests install their own fakes on top."""
    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
    monkeypatch.setattr(requests, "request", _blocked)
    monkeypatch.setattr(requests.Session, "request", _blocked)
    monkeypatch.setattr(httpx.Client, "send", _blocked)
    monkeypatch.setattr(httpx.AsyncClient, "send", _blocked)


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")
