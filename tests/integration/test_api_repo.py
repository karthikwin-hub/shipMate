from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_discover_no_match(client, monkeypatch):
    monkeypatch.setattr("repo_resolver.get_registered_paths", lambda: [])
    res = client.post(
        "/api/repo/discover",
        json={"repo": "https://github.com/example/demo"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "no_match"


def test_discover_needs_choice(client, tmp_git_repo, monkeypatch):
    monkeypatch.setattr(
        "repo_resolver.get_registered_paths",
        lambda: [{"path": tmp_git_repo, "remote": "github.com/example/demo"}],
    )
    monkeypatch.setattr(
        "git_manager.GitManager.get_origin_url",
        lambda self: "https://github.com/example/demo.git",
    )
    res = client.post(
        "/api/repo/discover",
        json={"repo": "https://github.com/example/demo"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "needs_choice"
    assert len(data["matches"]) == 1


def test_sync_local_path(client, tmp_git_repo):
    res = client.post("/api/repo/sync", json={"repo": tmp_git_repo})
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is True
    assert data["repo"] == tmp_git_repo
    assert "working_tree" in data


def test_sync_needs_choice(client, monkeypatch):
    monkeypatch.setattr(
        "repo_resolver.discover_local_match",
        lambda url: {
            "status": "needs_choice",
            "remote": "https://github.com/example/demo.git",
            "branch": None,
            "matches": [{"path": "/tmp/demo", "working_tree": {"clean": True}}],
        },
    )
    res = client.post(
        "/api/repo/sync",
        json={"repo": "https://github.com/example/demo", "mode": "auto"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "needs_choice"
    assert data["valid"] is False


def test_repo_status(client, tmp_git_repo):
    res = client.get(f"/api/repo/status?repo={tmp_git_repo}")
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is True
    assert data["repo_mode"] == "local"
    assert "working_tree" in data


def test_discard_cache_rejects_local(client, tmp_git_repo):
    res = client.post(
        "/api/repo/discard-cache",
        json={"repo": tmp_git_repo, "confirm": True},
    )
    assert res.status_code == 400


def test_discard_cache_requires_confirm(client, tmp_path, monkeypatch):
    cache = tmp_path / "repos" / "owner" / "repo"
    cache.mkdir(parents=True)
    import subprocess as sp

    sp.run(["git", "init"], cwd=cache, capture_output=True, check=True)
    sp.run(["git", "config", "user.email", "t@e.com"], cwd=cache, check=True)
    sp.run(["git", "config", "user.name", "T"], cwd=cache, check=True)
    (cache / "f.txt").write_text("x", encoding="utf-8")
    sp.run(["git", "add", "."], cwd=cache, check=True)
    sp.run(["git", "commit", "-m", "init"], cwd=cache, check=True)
    (cache / "dirty.txt").write_text("y", encoding="utf-8")

    monkeypatch.setattr("repo_resolver.REPOS_CACHE", tmp_path / "repos")

    res = client.post(
        "/api/repo/discard-cache",
        json={"repo": str(cache), "confirm": False},
    )
    assert res.status_code == 400

    res2 = client.post(
        "/api/repo/discard-cache",
        json={"repo": str(cache), "confirm": True},
    )
    assert res2.status_code == 200
    assert res2.json()["valid"] is True


def test_branches_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        "git_manager.GitManager.list_remote_branches_for_url",
        lambda url: (True, ["main", "dev"], ""),
    )
    res = client.post(
        "/api/repo/branches",
        json={"repo": "https://github.com/example/demo"},
    )
    assert res.status_code == 200
    assert res.json()["branches"] == ["main", "dev"]


def test_context_does_not_sync(client, tmp_git_repo, monkeypatch):
    called = {"sync": False}

    def fail_sync(*args, **kwargs):
        called["sync"] = True
        raise AssertionError("sync_repo should not run on context load")

    monkeypatch.setattr("repo_resolver.sync_repo", fail_sync)
    res = client.get(
        f"/api/context?repo={tmp_git_repo}",
        headers={"X-Session-Id": "no-sync-test"},
    )
    assert res.status_code == 200
    assert called["sync"] is False
    assert "working_tree" in res.json()
