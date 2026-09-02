import subprocess

from git_manager import GitManager


def test_get_working_tree_summary_clean(tmp_git_repo):
    summary = GitManager(tmp_git_repo).get_working_tree_summary()
    assert summary["clean"] is True
    assert summary["modified"] == 0


def test_get_working_tree_summary_dirty(tmp_git_repo):
    repo = tmp_git_repo
    with open(f"{repo}/dirty.txt", "w", encoding="utf-8") as f:
        f.write("change\n")
    summary = GitManager(repo).get_working_tree_summary()
    assert summary["clean"] is False
    assert summary["untracked"] >= 1


def test_urls_match():
    assert GitManager.urls_match(
        "https://github.com/user/repo.git",
        "git@github.com:user/repo",
    )
    assert not GitManager.urls_match(
        "https://github.com/user/repo.git",
        "https://github.com/other/repo.git",
    )


def test_create_and_apply_stash(tmp_git_repo):
    repo = tmp_git_repo
    with open(f"{repo}/stash-me.txt", "w", encoding="utf-8") as f:
        f.write("stash\n")
    git = GitManager(repo)
    ok, label = git.create_backup_stash("shipmate-test-stash")
    assert ok
    assert git.get_working_tree_summary()["clean"]
    ok, _ = git.apply_backup_stash()
    assert ok
    assert not git.get_working_tree_summary()["clean"]


def test_discard_all_changes(tmp_git_repo):
    repo = tmp_git_repo
    with open(f"{repo}/discard-me.txt", "w", encoding="utf-8") as f:
        f.write("discard\n")
    git = GitManager(repo)
    assert not git.get_working_tree_summary()["clean"]
    ok, msg = git.discard_all_changes()
    assert ok
    assert git.get_working_tree_summary()["clean"]


def test_list_remote_branches_for_url(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd[:3] == ["git", "ls-remote", "--heads"]
        return subprocess.CompletedProcess(
            cmd,
            0,
            "abc123\trefs/heads/main\nabc456\trefs/heads/dev\n",
            "",
        )

    monkeypatch.setattr("git_manager.subprocess.run", fake_run)
    ok, branches, err = GitManager.list_remote_branches_for_url("https://github.com/o/r.git")
    assert ok
    assert branches == ["dev", "main"]
    assert err == ""
