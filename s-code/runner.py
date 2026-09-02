import os
import subprocess

class CommandRunner:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def detect_stack(self) -> str:
        files = os.listdir(self.repo_path)
        if "package.json" in files: return "Node.js (npm)"
        if "pytest.ini" in files or "requirements.txt" in files: return "Python"
        if "go.mod" in files: return "Go"
        if "Cargo.toml" in files: return "Rust"
        if "docker-compose.yml" in files: return "Docker Compose"
        return "Generic Script"

    def get_test_command(self) -> str:
        stack = self.detect_stack()
        if "Node.js" in stack: return "npm test --if-present"
        if "Python" in stack: return "pytest"
        if "Go" in stack: return "go test ./..."
        if "Rust" in stack: return "cargo test"
        return "echo 'No automated test suite detected.'"

    def get_install_command(self) -> str:
        stack = self.detect_stack()
        if "Node.js" in stack: return "npm install"
        if "Python" in stack: return "pip install -r requirements.txt"
        if "Go" in stack: return "go mod download"
        return "echo 'No package dependencies to install.'"

    def run_stream(self, command: str):
        """Generator that yields output lines in real-time."""
        process = subprocess.Popen(
            command,
            cwd=self.repo_path,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        for line in iter(process.stdout.readline, ""):
            yield line
        process.stdout.close()
        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, command)