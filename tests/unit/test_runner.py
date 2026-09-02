from pathlib import Path

import subprocess

import pytest

from runner import CommandRunner


def test_detect_stack_python(tmp_git_repo):
    Path(tmp_git_repo, "requirements.txt").write_text("pytest\n", encoding="utf-8")
    assert "Python" in CommandRunner(tmp_git_repo).detect_stack()


def test_detect_stack_node(tmp_git_repo):
    Path(tmp_git_repo, "package.json").write_text("{}", encoding="utf-8")
    assert "Node.js" in CommandRunner(tmp_git_repo).detect_stack()


def test_get_test_command_python(tmp_git_repo):
    Path(tmp_git_repo, "requirements.txt").write_text("x", encoding="utf-8")
    assert CommandRunner(tmp_git_repo).get_test_command() == "pytest"


def test_get_install_command_node(tmp_git_repo):
    Path(tmp_git_repo, "package.json").write_text("{}", encoding="utf-8")
    assert CommandRunner(tmp_git_repo).get_install_command() == "npm install"


def test_run_stream(tmp_git_repo):
    runner = CommandRunner(tmp_git_repo)
    lines = list(runner.run_stream("echo shipmate"))
    assert any("shipmate" in line for line in lines)


def test_run_stream_failure(tmp_git_repo):
    runner = CommandRunner(tmp_git_repo)
    with pytest.raises(subprocess.CalledProcessError):
        list(runner.run_stream("exit 1"))
