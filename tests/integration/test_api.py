import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_index(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "ShipMate" in res.text


def test_validate_repo(client, tmp_git_repo):
    res = client.post("/api/repo/validate", json={"repo": tmp_git_repo})
    assert res.status_code == 200
    assert res.json()["valid"] is True


def test_validate_repo_invalid(client):
    res = client.post("/api/repo/validate", json={"repo": "/bad/path"})
    assert res.status_code == 200
    assert res.json()["valid"] is False


def test_context(client, tmp_git_repo):
    res = client.get(
        f"/api/context?repo={tmp_git_repo}",
        headers={"X-Session-Id": "api-test"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["valid"]
    assert data["identity"]["branch"] == "feature/test"
    assert "working_tree" in data
    assert "repo_mode" in data


def test_context_invalid(client):
    res = client.get("/api/context?repo=/bad/path")
    assert res.status_code == 400


def test_checklist(client, tmp_git_repo):
    res = client.get(
        f"/api/checklist?repo={tmp_git_repo}&stage=dev",
        headers={"X-Session-Id": "api-test"},
    )
    assert res.status_code == 200
    assert "items" in res.json()


def test_activity_overview(client):
    res = client.get("/api/activity/overview")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_settings(client, tmp_git_repo):
    res = client.get(f"/api/settings/deploy?repo={tmp_git_repo}")
    assert res.status_code == 200
    assert "provider_name" in res.json()


def test_live_status(client, tmp_git_repo):
    res = client.get(f"/api/live-status?repo={tmp_git_repo}")
    assert res.status_code == 200
    assert "label" in res.json()
