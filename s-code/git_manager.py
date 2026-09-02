import subprocess
import os
import re

class GitManager:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def _run_git(self, args: list) -> tuple[int, str]:
        try:
            res = subprocess.run(
                ["git"] + args,
                cwd=self.repo_path,
                capture_output=True,
                text=True
            )
            return res.returncode, res.stdout.strip() if res.returncode == 0 else res.stderr.strip()
        except Exception as e:
            return 1, str(e)

    def get_git_identity(self) -> dict:
        _, name = self._run_git(["config", "user.name"])
        _, email = self._run_git(["config", "user.email"])
        _, branch = self._run_git(["branch", "--show-current"])
        _, remote = self._run_git(["remote", "get-url", "origin"])
        return {
            "name": name or "Unknown",
            "email": email or "Unknown",
            "branch": branch or "HEAD",
            "remote": remote or "No remote configured"
        }

    def set_local_identity(self, name: str, email: str) -> tuple[bool, str]:
        c1, out1 = self._run_git(["config", "--local", "user.name", name])
        if c1 != 0: return False, out1
        c2, out2 = self._run_git(["config", "--local", "user.email", email])
        if c2 != 0: return False, out2
        return True, "Local Git identity updated successfully."

    def scan_for_secrets(self) -> list[str]:
        """Scan staged & unstaged changes for exposed keys/tokens."""
        secret_patterns = [
            (r'(?i)api[_-]?key\s*=\s*[\'"][A-Za-z0-9_\-]{16,}[\'"]', "Exposed API Key"),
            (r'(?i)secret\s*=\s*[\'"][A-Za-z0-9_\-]{16,}[\'"]', "Exposed Secret"),
            (r'ghp_[A-Za-z0-9]{36}', "GitHub Personal Access Token"),
            (r'sk_live_[0-9a-zA-Z]{24}', "Stripe Live Key"),
            (r'-----BEGIN PRIVATE KEY-----', "Private Key Material")
        ]
        issues = []
        _, diff = self._run_git(["diff", "HEAD"])
        for pattern, desc in secret_patterns:
            if re.search(pattern, diff):
                issues.append(desc)
        return issues

    def get_pr_status(self) -> str:
        try:
            res = subprocess.run(
                ["gh", "pr", "view", "--json", "number,title,state,url"],
                cwd=self.repo_path,
                capture_output=True,
                text=True
            )
            if res.returncode == 0:
                return res.stdout.strip()
            return "No active PR found on GitHub."
        except FileNotFoundError:
            return "GitHub CLI (`gh`) not installed."