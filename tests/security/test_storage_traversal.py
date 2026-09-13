"""Security regressions for POST /storage/save-json (path traversal)."""

import pytest


@pytest.fixture
def outputs_dir(tmp_path, monkeypatch):
    from app.backend.routes import storage

    out = tmp_path / "repo" / "outputs"
    monkeypatch.setattr(storage, "OUTPUTS_DIR", out)
    return out


def test_save_json_writes_inside_outputs(client, outputs_dir):
    resp = client.post("/storage/save-json", json={"filename": "result.json", "data": {"a": 1}})
    assert resp.status_code == 200
    assert (outputs_dir / "result.json").is_file()


@pytest.mark.parametrize(
    "filename",
    [
        "../../trading_mode.json",
        "../trading_mode.json",
        "..",
        ".",
        "sub/../../escape.json",
        "sub/file.json",
        "sub\\file.json",
        "..\\..\\trading_mode.json",
        "/etc/passwd",
        "C:\\Windows\\Temp\\evil.json",
        "C:evil.json",
        "",
    ],
)
def test_save_json_rejects_traversal(client, outputs_dir, tmp_path, filename):
    resp = client.post("/storage/save-json", json={"filename": filename, "data": {"pwned": True}})
    assert resp.status_code == 400
    assert list(tmp_path.rglob("*.json")) == []


def test_save_json_rejects_absolute_path_outside_outputs(client, outputs_dir, tmp_path):
    target = tmp_path / "absolute.json"
    resp = client.post("/storage/save-json", json={"filename": str(target), "data": {"pwned": True}})
    assert resp.status_code == 400
    assert not target.exists()
