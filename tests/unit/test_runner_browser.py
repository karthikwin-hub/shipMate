from unittest.mock import MagicMock, patch

import pytest

from runner import open_browser


@pytest.mark.parametrize(
    "system,cmd",
    [
        ("Windows", ["cmd", "/c", "start", "", "http://localhost:8000"]),
        ("Darwin", ["open", "http://localhost:8000"]),
        ("Linux", ["xdg-open", "http://localhost:8000"]),
    ],
)
def test_open_browser_platform(system, cmd):
    with patch("runner.platform.system", return_value=system), patch(
        "runner.subprocess.Popen"
    ) as mock_popen:
        open_browser("http://localhost:8000")
        mock_popen.assert_called_once_with(cmd, close_fds=True)


def test_open_browser_fallback_on_oserror():
    with patch("runner.platform.system", return_value="Linux"), patch(
        "runner.subprocess.Popen", side_effect=OSError("fail")
    ), patch("runner.webbrowser.open") as mock_wb:
        open_browser("http://example.com")
        mock_wb.assert_called_once_with("http://example.com")
