from pathlib import Path

import pytest

from repo_resolver import (
    _sanitize_path_segment,
    cache_path_for_remote,
    discover_local_match,
    is_remote_url,
    parse_remote_url,
    sync_repo,
    validate_local_repo,
)


def test_is_remote_url_https():
    assert is_remote_url("https://github.com/karthikwin-hub/appforge")
    assert is_remote_url("https://github.com/user/repo.git")


def test_is_remote_url_local():
    assert not is_remote_url("/home/user/project")
    assert not is_remote_url("C:\\repos\\my-app")


def test_parse_remote_url_basic():
    clone_url, owner, repo_name, branch = parse_remote_url(
        "https://github.com/karthikwin-hub/appforge"
    )
    assert clone_url == "https://github.com/karthikwin-hub/appforge.git"
    assert owner == "karthikwin-hub"
    assert repo_name == "appforge"
    assert branch is None


def test_parse_remote_url_hash_branch():
    _, _, _, branch = parse_remote_url("https://github.com/o/r#feature/x")
    assert branch == "feature/x"


def test_parse_remote_url_at_branch():
    _, _, _, branch = parse_remote_url("https://github.com/o/r@dev")
    assert branch == "dev"


def test_parse_remote_url_rejects_both_branch_suffixes():
    with pytest.raises(ValueError, match="not both"):
        parse_remote_url("https://github.com/o/r@dev#feature")


def test_sanitize_path_segment():
    assert _sanitize_path_segment("app/forge") == "app_forge"
    assert _sanitize_path_segment("valid-name") == "valid-name"


def test_cache_path_for_remote():
    path = cache_path_for_remote("owner", "repo")
    assert path.name == "repo"
    assert path.parent.name == "owner"


def test_sync_repo_local(tmp_git_repo):
    result = sync_repo(tmp_git_repo)
    assert result.ok
    assert result.path == tmp_git_repo
    assert result.repo_mode == "local"


def test_sync_repo_missing_local():
    result = sync_repo("/nonexistent/local/path")
    assert not result.ok
    assert "does not exist" in result.message.lower() or "clone" in result.message.lower()


def test_sync_repo_clone_namespaced(tmp_path, monkeypatch):
    import subprocess as sp

    cache = tmp_path / "repos"
    monkeypatch.setattr("repo_resolver.REPOS_CACHE", cache)

    real_run = sp.run

    def fake_run(cmd, **kwargs):
        if len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "clone":
            dest = Path(cmd[-1])
            dest.mkdir(parents=True, exist_ok=True)
            real_run(["git", "init"], cwd=dest, capture_output=True, check=True)
            return sp.CompletedProcess(cmd, 0, "", "")
        if len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "pull":
            return sp.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr("repo_resolver.subprocess.run", fake_run)

    result = sync_repo("https://github.com/example/demo", mode="cache")
    assert result.ok
    assert Path(result.path).name == "demo"
    assert (cache / "example" / "demo" / ".git").exists()


def test_discover_local_match_registered(tmp_git_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "repo_resolver.get_registered_paths",
        lambda: [{"path": tmp_git_repo, "remote": "github.com/example/demo"}],
    )
    monkeypatch.setattr(
        "git_manager.GitManager.get_origin_url",
        lambda self: "https://github.com/example/demo.git",
    )

    discovery = discover_local_match("https://github.com/example/demo")
    assert discovery["status"] == "needs_choice"
    assert len(discovery["matches"]) == 1
    assert discovery["matches"][0]["path"] == tmp_git_repo


def test_discover_local_match_no_match(monkeypatch):
    monkeypatch.setattr("repo_resolver.get_registered_paths", lambda: [])
    discovery = discover_local_match("https://github.com/example/demo")
    assert discovery["status"] == "no_match"


def test_validate_local_repo(tmp_git_repo):
    ok, msg = validate_local_repo(tmp_git_repo)
    assert ok
    assert msg == "OK"
