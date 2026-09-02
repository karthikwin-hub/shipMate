import pytest

import projects_store as ps


@pytest.fixture
def projects_file(tmp_path, monkeypatch):
    path = tmp_path / "projects.json"
    path.write_text('{"projects": []}', encoding="utf-8")
    monkeypatch.setattr(ps, "PROJECTS_PATH", path)
    return path


def test_create_and_list_projects(projects_file):
    project = ps.create_project({
        "name": "AppForge",
        "remote_url": "https://github.com/user/appforge.git",
        "dev_path": "/tmp/appforge",
        "stack": "Python",
    })
    assert project["project_id"] == "appforge"
    assert len(ps.list_projects()) == 1


def test_update_project(projects_file):
    ps.create_project({"name": "Demo", "remote_url": "https://github.com/o/demo.git"})
    updated = ps.update_project("demo", {"stack": "Node.js"})
    assert updated["stack"] == "Node.js"


def test_delete_project(projects_file):
    ps.create_project({"name": "Demo", "remote_url": "https://github.com/o/demo.git"})
    ps.delete_project("demo")
    assert ps.list_projects() == []


def test_auto_populate_from_path(projects_file, tmp_git_repo, monkeypatch):
    monkeypatch.setattr(
        "projects_store.get_effective_oracle_config",
        lambda p: {"host": "10.0.0.1", "remote_path": "/var/www/app", "health_url": ""},
    )
    draft = ps.auto_populate_from_path(tmp_git_repo)
    assert draft["dev_path"] == tmp_git_repo
    assert draft["remote_url"]
    assert draft["project_id"]


def test_duplicate_project_id_raises(projects_file):
    ps.create_project({"name": "One", "remote_url": "https://github.com/o/repo.git"})
    with pytest.raises(ValueError, match="already exists"):
        ps.create_project({"name": "Two", "remote_url": "https://github.com/o/repo2.git", "project_id": "repo"})


def test_touch_project_updates_last_used_and_sort_order(projects_file, monkeypatch):
    counter = {"n": 0}

    def fake_now():
        counter["n"] += 1
        return f"2026-01-{counter['n']:02d}T00:00:00+00:00"

    monkeypatch.setattr(ps, "_now_iso", fake_now)
    ps.create_project({"name": "Alpha", "remote_url": "https://github.com/o/a.git", "project_id": "alpha"})
    ps.create_project({"name": "Beta", "remote_url": "https://github.com/o/b.git", "project_id": "beta"})
    ps.touch_project("alpha")
    ordered = [p["project_id"] for p in ps.list_projects()]
    assert ordered[0] == "alpha"
    ps.touch_project("beta")
    ordered = [p["project_id"] for p in ps.list_projects()]
    assert ordered[0] == "beta"
