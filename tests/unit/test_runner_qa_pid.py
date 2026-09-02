import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from runner import QA_PID_FILENAME, CommandRunner


def test_launch_writes_pid_file(tmp_git_repo):
    runner = CommandRunner(tmp_git_repo)
    pid_path = Path(tmp_git_repo) / QA_PID_FILENAME

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None

    with patch("runner.subprocess.Popen", return_value=mock_proc), patch(
        "runner.open_browser"
    ):
        ok, msg, port = runner.launch_app()

    assert ok
    assert pid_path.exists()
    assert pid_path.read_text(encoding="utf-8") == "12345"


def test_stop_clears_pid_file(tmp_git_repo):
    runner = CommandRunner(tmp_git_repo)
    pid_path = Path(tmp_git_repo) / QA_PID_FILENAME
    pid_path.write_text("99999", encoding="utf-8")

    with patch.object(runner, "_is_process_alive", return_value=True), patch.object(
        runner, "_terminate_pid"
    ):
        ok, msg = runner.stop_app()

    assert ok
    assert not pid_path.exists()


def test_stale_pid_file_removed_on_init(tmp_git_repo):
    pid_path = Path(tmp_git_repo) / QA_PID_FILENAME
    pid_path.write_text("88888", encoding="utf-8")

    with patch("runner._is_process_alive", return_value=False):
        runner = CommandRunner(tmp_git_repo)

    assert not pid_path.exists()
    assert runner._qa_process is None


def test_restore_qa_from_pid_file(tmp_git_repo):
    pid_path = Path(tmp_git_repo) / QA_PID_FILENAME
    pid_path.write_text("77777", encoding="utf-8")

    with patch("runner._is_process_alive", return_value=True):
        runner = CommandRunner(tmp_git_repo)
        assert runner.qa_running
        assert runner._qa_process is not None
        assert runner._qa_process.pid == 77777
