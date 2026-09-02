import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    projects_path = tmp_path / "projects.json"
    projects_path.write_text('{"projects": []}', encoding="utf-8")
    monkeypatch.setattr("projects_store.PROJECTS_PATH", projects_path)
    monkeypatch.setattr("server.pstore.PROJECTS_PATH", projects_path)
    monkeypatch.setattr("environment_inspector._inspection_cache", {})
    with TestClient(app) as c:
        yield c


def test_list_projects_empty(client):
    res = client.get("/api/projects")
    assert res.status_code == 200
    assert res.json()["projects"] == []


def test_create_and_list_project(client):
    res = client.post("/api/projects", json={
        "name": "Demo",
        "remote_url": "https://github.com/example/demo.git",
        "dev_path": "/tmp/demo",
    })
    assert res.status_code == 200
    assert res.json()["project"]["project_id"] == "demo"

    res2 = client.get("/api/projects")
    assert len(res2.json()["projects"]) == 1


def test_auto_populate(client, tmp_git_repo):
    res = client.post("/api/projects/auto-populate", json={"path": tmp_git_repo})
    assert res.status_code == 200
    assert res.json()["draft"]["dev_path"] == tmp_git_repo


def test_inspect_projects(client, tmp_git_repo, monkeypatch):
    client.post("/api/projects", json={
        "name": "Demo",
        "remote_url": "https://github.com/example/demo.git",
        "dev_path": tmp_git_repo,
    })

    async def fake_fleet(projects, **kw):
        return [{"project_id": "demo", "tiers": {}, "suggestion": {}}]

    monkeypatch.setattr("environment_inspector.inspect_fleet", fake_fleet)
    res = client.post("/api/projects/inspect", json={})
    assert res.status_code == 200
    assert len(res.json()["inspections"]) == 1


def test_suggest_endpoint(client, tmp_git_repo):
    client.post("/api/projects", json={
        "name": "Demo",
        "remote_url": "https://github.com/example/demo.git",
        "dev_path": tmp_git_repo,
    })
    res = client.get("/api/projects/suggest?project_id=demo&refresh=true")
    assert res.status_code == 200
    assert "suggestion" in res.json()


def test_delete_project(client):
    client.post("/api/projects", json={
        "name": "Demo",
        "remote_url": "https://github.com/example/demo.git",
    })
    res = client.delete("/api/projects/demo")
    assert res.status_code == 200
    assert client.get("/api/projects").json()["projects"] == []


def test_touch_project(client):
    client.post("/api/projects", json={
        "name": "Demo",
        "remote_url": "https://github.com/example/demo.git",
    })
    res = client.post("/api/projects/demo/touch")
    assert res.status_code == 200
    assert res.json()["project"]["last_used_at"]
    assert client.get("/api/projects").json()["projects"][0]["project_id"] == "demo"
