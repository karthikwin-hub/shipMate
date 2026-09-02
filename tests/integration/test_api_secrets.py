import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_secrets_crud(client, tmp_vault_dir, monkeypatch):
    monkeypatch.setattr(
        "secrets_vault.get_secrets_config",
        lambda: {"backend": "local", "local": {"vault_dir": tmp_vault_dir}},
    )
    monkeypatch.setattr(
        "config_loader.get_secrets_config",
        lambda: {"backend": "local", "local": {"vault_dir": tmp_vault_dir}},
    )

    res = client.post(
        "/api/secrets",
        json={"scope": "global", "repo": None, "name": "TEST_KEY", "value": "secret123"},
    )
    assert res.status_code == 200

    res = client.get("/api/secrets?scope=global")
    assert res.status_code == 200
    names = [s["name"] for s in res.json()["secrets"]]
    assert "TEST_KEY" in names

    res = client.post(
        "/api/secrets/delete",
        json={"scope": "global", "repo": None, "name": "TEST_KEY"},
    )
    assert res.status_code == 200

    res = client.get("/api/secrets?scope=global")
    names = [s["name"] for s in res.json()["secrets"]]
    assert "TEST_KEY" not in names


def test_secrets_import(client, tmp_vault_dir, monkeypatch):
    monkeypatch.setattr(
        "secrets_vault.get_secrets_config",
        lambda: {"backend": "local", "local": {"vault_dir": tmp_vault_dir}},
    )
    monkeypatch.setattr(
        "config_loader.get_secrets_config",
        lambda: {"backend": "local", "local": {"vault_dir": tmp_vault_dir}},
    )

    res = client.post(
        "/api/secrets/import",
        json={
            "scope": "global",
            "repo": None,
            "env_content": "IMPORTED_KEY=hello\n# comment\nOTHER=world",
        },
    )
    assert res.status_code == 200
    assert res.json()["count"] >= 2
