"""Security regressions for app/backend: API key disclosure and Host header check."""

import pytest

SECRET = "sk-test-SUPERSECRET-0123456789abcd"


def _store_key(client, provider="OPENAI_API_KEY", value=SECRET):
    return client.post("/api-keys/", json={"provider": provider, "key_value": value, "is_active": True})


# ---------------------------------------------------------------------------
# API keys are never returned in plaintext
# ---------------------------------------------------------------------------

def test_create_response_does_not_echo_key(client):
    resp = _store_key(client)
    assert resp.status_code == 200
    body = resp.json()
    assert "key_value" not in body
    assert SECRET not in resp.text
    assert body["has_key"] is True
    assert body["key_preview"].endswith("abcd")


def test_get_single_key_is_masked(client):
    _store_key(client)
    resp = client.get("/api-keys/OPENAI_API_KEY")
    assert resp.status_code == 200
    body = resp.json()
    assert "key_value" not in body
    assert SECRET not in resp.text
    assert body["has_key"] is True
    assert body["key_preview"].endswith("abcd")


def test_list_keys_is_masked_but_reports_presence(client):
    _store_key(client)
    resp = client.get("/api-keys/")
    assert resp.status_code == 200
    assert SECRET not in resp.text
    [item] = resp.json()
    assert "key_value" not in item
    assert item["provider"] == "OPENAI_API_KEY"
    assert item["has_key"] is True
    assert item["key_preview"].endswith("abcd")


def test_update_and_bulk_responses_are_masked(client):
    _store_key(client)
    put = client.put("/api-keys/OPENAI_API_KEY", json={"key_value": SECRET + "X"})
    assert put.status_code == 200
    assert "key_value" not in put.json()
    assert SECRET not in put.text

    bulk = client.post("/api-keys/bulk", json={"api_keys": [{"provider": "GROQ_API_KEY", "key_value": SECRET, "is_active": True}]})
    assert bulk.status_code == 200
    assert SECRET not in bulk.text
    assert all("key_value" not in item for item in bulk.json())


def test_short_keys_are_fully_masked(client):
    _store_key(client, value="abc123")
    resp = client.get("/api-keys/OPENAI_API_KEY")
    assert "abc123" not in resp.text
    assert "123" not in resp.json()["key_preview"]


def test_backend_services_still_read_full_key(client, backend_app):
    """Internal consumers read from the DB, not from the HTTP response."""
    from app.backend.database import get_db
    from app.backend.services.api_key_service import ApiKeyService

    _store_key(client)
    db = next(backend_app.dependency_overrides[get_db]())
    try:
        assert ApiKeyService(db).get_api_keys_dict()["OPENAI_API_KEY"] == SECRET
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Host header check (DNS rebinding)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "localhost:8000", "127.0.0.1:8000"])
def test_localhost_hosts_are_allowed(client, host):
    resp = client.get("/", headers={"host": host})
    assert resp.status_code == 200


@pytest.mark.parametrize("host", ["evil.example.com", "testserver", "192.168.1.10:8000"])
def test_foreign_hosts_are_rejected(client, host):
    resp = client.get("/", headers={"host": host})
    assert resp.status_code == 400
