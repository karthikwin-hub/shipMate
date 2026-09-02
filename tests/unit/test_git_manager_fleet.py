
def test_get_head_commit(tmp_git_repo):
    from git_manager import GitManager

    head = GitManager(tmp_git_repo).get_head_commit()
    assert head["hash"]
    assert head["short"]
    assert head["message"] == "init"


def test_get_remote_default_branch(monkeypatch):
    import subprocess
    from git_manager import GitManager

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, "ref: refs/heads/main\tHEAD\nabc123\tHEAD\n", ""
        )

    monkeypatch.setattr("git_manager.subprocess.run", fake_run)
    branch, h = GitManager.get_remote_default_branch("https://github.com/o/r.git")
    assert branch == "main"
    assert h == "abc123"
