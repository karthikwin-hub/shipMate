import os
import platform
import signal
import subprocess
import webbrowser

PROTECTED_BRANCHES = {"main", "master"}
QA_PID_FILENAME = ".qa_server.pid"


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                check=False,
            )
            return str(pid) in result.stdout
        except OSError:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_pid(pid: int) -> None:
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(50):
        if not _is_process_alive(pid):
            return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


class CommandRunner:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self._qa_process = None
        self._restore_qa_from_pid_file()

    def detect_stack(self) -> str:
        files = os.listdir(self.repo_path)
        if "package.json" in files:
            return "Node.js (npm)"
        if "manage.py" in files:
            return "Python (Django)"
        if "pyproject.toml" in files or "pytest.ini" in files or "requirements.txt" in files:
            return "Python"
        if "go.mod" in files:
            return "Go"
        if "Cargo.toml" in files:
            return "Rust"
        if "docker-compose.yml" in files or "docker-compose.yaml" in files:
            return "Docker Compose"
        return "Generic Script"

    def get_lint_command(self) -> str:
        stack = self.detect_stack()
        if "Node.js" in stack:
            return "npm run lint --if-present || npx eslint . --max-warnings 0 2>/dev/null || echo 'No linter configured'"
        if "Python" in stack:
            if os.path.exists(os.path.join(self.repo_path, "pyproject.toml")):
                return "ruff check . 2>/dev/null || python -m py_compile $(git ls-files '*.py') 2>/dev/null || echo 'No linter configured'"
            return "python -m py_compile $(git ls-files '*.py') 2>/dev/null || echo 'No linter configured'"
        if "Go" in stack:
            return "go vet ./..."
        if "Rust" in stack:
            return "cargo clippy -- -D warnings 2>/dev/null || echo 'No linter configured'"
        return "echo 'No linter configured'"

    def get_test_command(self) -> str:
        stack = self.detect_stack()
        if "Node.js" in stack:
            return "npm test --if-present"
        if "Django" in stack:
            return "python manage.py test"
        if "Python" in stack:
            return "pytest"
        if "Go" in stack:
            return "go test ./..."
        if "Rust" in stack:
            return "cargo test"
        return "echo 'No automated test suite detected.'"

    def get_install_command(self) -> str:
        stack = self.detect_stack()
        if "Node.js" in stack:
            return "npm install"
        if "Python" in stack:
            if os.path.exists(os.path.join(self.repo_path, "requirements.txt")):
                return "pip install -r requirements.txt"
            return "pip install -e . 2>/dev/null || echo 'No requirements.txt found'"
        if "Go" in stack:
            return "go mod download"
        if "Rust" in stack:
            return "cargo build"
        return "echo 'No package dependencies to install.'"

    def get_launch_command(self) -> tuple[str, int]:
        stack = self.detect_stack()
        if "Node.js" in stack:
            return "npm start", 3000
        if "Django" in stack:
            return "python manage.py runserver 8000", 8000
        if "Python" in stack:
            return "uvicorn main:app --host 0.0.0.0 --port 8000 2>/dev/null || python -m uvicorn app:app --host 0.0.0.0 --port 8000 2>/dev/null || python manage.py runserver 8000", 8000
        if "Docker Compose" in stack:
            return "docker compose up", 8080
        return "echo 'No launch command detected'", 8000

    def run_stream(self, command: str):
        process = subprocess.Popen(
            command,
            cwd=self.repo_path,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in iter(process.stdout.readline, ""):
            yield line
        process.stdout.close()
        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, command)

    def run_preflight(self) -> list[str]:
        """Fail-fast: lint then tests. Returns log lines."""
        lines = []
        for cmd, label in [(self.get_lint_command(), "Lint"), (self.get_test_command(), "Tests")]:
            lines.append(f"--- {label}: {cmd} ---")
            for line in self.run_stream(cmd):
                lines.append(line.rstrip())
        return lines

    def _pid_file_path(self) -> str:
        return os.path.join(self.repo_path, QA_PID_FILENAME)

    def _write_pid_file(self, pid: int) -> None:
        with open(self._pid_file_path(), "w", encoding="utf-8") as f:
            f.write(str(pid))

    def _clear_pid_file(self) -> None:
        path = self._pid_file_path()
        if os.path.exists(path):
            os.remove(path)

    def _is_process_alive(self, pid: int) -> bool:
        return _is_process_alive(pid)

    def _restore_qa_from_pid_file(self) -> None:
        path = self._pid_file_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                pid = int(f.read().strip())
        except (OSError, ValueError):
            self._clear_pid_file()
            return
        if self._is_process_alive(pid):
            self._qa_process = _PidProcess(pid)
        else:
            self._clear_pid_file()

    def launch_app(self) -> tuple[bool, str, int]:
        if self._qa_process and self._qa_process.poll() is None:
            return True, "QA app already running", self._get_qa_port()

        cmd, port = self.get_launch_command()
        self._qa_process = subprocess.Popen(
            cmd,
            cwd=self.repo_path,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._write_pid_file(self._qa_process.pid)
        url = f"http://localhost:{port}"
        open_browser(url)
        return True, f"Launched QA app at {url}", port

    def stop_app(self) -> tuple[bool, str]:
        pid = None
        if self._qa_process and self._qa_process.poll() is None:
            pid = self._qa_process.pid
        elif os.path.exists(self._pid_file_path()):
            try:
                with open(self._pid_file_path(), encoding="utf-8") as f:
                    pid = int(f.read().strip())
            except (OSError, ValueError):
                pass

        if pid and self._is_process_alive(pid):
            self._terminate_pid(pid)
            self._qa_process = None
            self._clear_pid_file()
            return True, "QA app stopped"

        self._qa_process = None
        self._clear_pid_file()
        stack = self.detect_stack()
        if "Docker Compose" in stack:
            subprocess.run("docker compose down", cwd=self.repo_path, shell=True)
            return True, "Docker Compose stopped"
        return True, "No QA app process running"

    def _terminate_pid(self, pid: int) -> None:
        _terminate_pid(pid)

    def _get_qa_port(self) -> int:
        _, port = self.get_launch_command()
        return port

    @property
    def qa_running(self) -> bool:
        if self._qa_process is not None and self._qa_process.poll() is None:
            return True
        path = self._pid_file_path()
        if not os.path.exists(path):
            return False
        try:
            with open(path, encoding="utf-8") as f:
                pid = int(f.read().strip())
        except (OSError, ValueError):
            self._clear_pid_file()
            return False
        if self._is_process_alive(pid):
            self._qa_process = _PidProcess(pid)
            return True
        self._clear_pid_file()
        return False


def open_browser(url: str) -> None:
    """Open URL in the default browser without blocking the caller."""
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(["cmd", "/c", "start", "", url], close_fds=True)
        elif system == "Darwin":
            subprocess.Popen(["open", url], close_fds=True)
        elif system == "Linux":
            subprocess.Popen(["xdg-open", url], close_fds=True)
        else:
            webbrowser.open(url)
    except OSError:
        webbrowser.open(url)


class _PidProcess:
    """Lightweight handle for a process restored from PID file."""

    def __init__(self, pid: int):
        self.pid = pid

    def poll(self):
        return None if _is_process_alive(self.pid) else 1

    def terminate(self):
        _terminate_pid(self.pid)

    def wait(self, timeout=None):
        return None

    def kill(self):
        _terminate_pid(self.pid)
