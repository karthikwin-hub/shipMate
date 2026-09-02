import subprocess
from pathlib import Path

from git_manager import GitManager


def test_get_git_identity(tmp_git_repo):
    git = GitManager(tmp_git_repo)
    identity = git.get_git_identity()
    assert identity["name"] == "Test User"
    assert identity["email"] == "test@example.com"
    assert identity["branch"] == "feature/test"


def test_is_protected_branch_false_on_feature(tmp_git_repo):
    git = GitManager(tmp_git_repo)
    assert not git.is_protected_branch()


def test_is_protected_branch_true_on_main(tmp_git_repo):
    subprocess.run(["git", "checkout", "main"], cwd=tmp_git_repo, check=True)
    git = GitManager(tmp_git_repo)
    assert git.is_protected_branch()


def test_is_working_tree_clean(tmp_git_repo):
    git = GitManager(tmp_git_repo)
    clean, msg = git.is_working_tree_clean()
    assert clean
    assert "clean" in msg.lower()


def test_is_working_tree_dirty(tmp_git_repo):
    Path(tmp_git_repo, "dirty.txt").write_text("x", encoding="utf-8")
    git = GitManager(tmp_git_repo)
    clean, _ = git.is_working_tree_clean()
    assert not clean


def test_scan_for_secrets_clean(tmp_git_repo):
    git = GitManager(tmp_git_repo)
    assert git.scan_for_secrets() == []


def test_scan_for_secrets_detects_api_key(tmp_git_repo):
    bad = Path(tmp_git_repo) / "secrets.py"
    bad.write_text('api_key = "ABCDEFGHIJKLMNOPQRSTUV"\n', encoding="utf-8")
    subprocess.run(["git", "add", "secrets.py"], cwd=tmp_git_repo, check=True)
    git = GitManager(tmp_git_repo)
    issues = git.scan_for_secrets()
    assert "Exposed API Key" in issues


def test_set_local_identity(tmp_git_repo):
    git = GitManager(tmp_git_repo)
    ok, msg = git.set_local_identity("New Name", "new@test.com")
    assert ok
    identity = git.get_git_identity()
    assert identity["name"] == "New Name"
    assert identity["email"] == "new@test.com"
