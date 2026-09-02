import json
import os
import re
import subprocess


PROTECTED_BRANCHES = {"main", "master"}


class GitManager:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def _run_git(self, args: list) -> tuple[int, str]:
        try:
            res = subprocess.run(
                ["git"] + args,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
            out = res.stdout.strip() if res.returncode == 0 else res.stderr.strip()
            return res.returncode, out
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
            "remote": remote or "No remote configured",
        }

    def set_local_identity(self, name: str, email: str) -> tuple[bool, str]:
        c1, out1 = self._run_git(["config", "--local", "user.name", name])
        if c1 != 0:
            return False, out1
        c2, out2 = self._run_git(["config", "--local", "user.email", email])
        if c2 != 0:
            return False, out2
        return True, "Local Git identity updated successfully."

    def is_working_tree_clean(self) -> tuple[bool, str]:
        code, out = self._run_git(["status", "--porcelain"])
        if code != 0:
            return False, out
        if out.strip():
            return False, f"Working tree has uncommitted changes:\n{out}"
        return True, "Working tree is clean"

    def is_protected_branch(self) -> bool:
        identity = self.get_git_identity()
        return identity["branch"].lower() in PROTECTED_BRANCHES

    def scan_for_secrets(self) -> list[str]:
        secret_patterns = [
            (r"(?i)api[_-]?key\s*=\s*['\"][A-Za-z0-9_\-]{16,}['\"]", "Exposed API Key"),
            (r"(?i)secret\s*=\s*['\"][A-Za-z0-9_\-]{16,}['\"]", "Exposed Secret"),
            (r"ghp_[A-Za-z0-9]{36}", "GitHub Personal Access Token"),
            (r"sk_live_[0-9a-zA-Z]{24}", "Stripe Live Key"),
            (r"-----BEGIN PRIVATE KEY-----", "Private Key Material"),
            (r"(?i)(^|\s)\.env(\s|$|/|\\)", ".env file reference in diff"),
        ]
        issues = []
        _, diff = self._run_git(["diff", "HEAD"])
        _, staged = self._run_git(["diff", "--cached"])
        combined = diff + "\n" + staged
        for pattern, desc in secret_patterns:
            if re.search(pattern, combined):
                issues.append(desc)
        return issues

    def get_pr_status(self) -> dict:
        try:
            res = subprocess.run(
                ["gh", "pr", "view", "--json", "number,title,state,url,reviewDecision"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and res.stdout.strip():
                return json.loads(res.stdout.strip())
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return {"state": "NONE", "title": "No active PR found", "url": "", "number": None}

    def format_pr_status(self) -> str:
        pr = self.get_pr_status()
        if pr.get("state") == "NONE":
            return "No active PR found on GitHub."
        num = pr.get("number", "?")
        title = pr.get("title", "")
        state = pr.get("state", "")
        url = pr.get("url", "")
        return f"PR #{num}: {title} [{state}] {url}"

    def create_pull_request(self) -> tuple[bool, str]:
        try:
            res = subprocess.run(
                ["gh", "pr", "create", "--fill"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                return True, res.stdout.strip() or "PR created successfully"
            return False, res.stderr.strip() or res.stdout.strip()
        except FileNotFoundError:
            return False, "GitHub CLI (`gh`) not installed."

    def merge_pull_request(self) -> tuple[bool, str]:
        try:
            res = subprocess.run(
                ["gh", "pr", "merge", "--auto", "--merge"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                return True, res.stdout.strip() or "PR merged successfully"
            res2 = subprocess.run(
                ["gh", "pr", "merge", "--merge"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
            if res2.returncode == 0:
                return True, res2.stdout.strip() or "PR merged successfully"
            return False, res.stderr.strip() or res2.stderr.strip()
        except FileNotFoundError:
            return False, "GitHub CLI (`gh`) not installed."

    def get_sync_status(self) -> str:
        code, out = self._run_git(["status", "-sb"])
        if code != 0:
            return "Unknown"
        if "[ahead" in out:
            return "Ahead of remote"
        if "[behind" in out:
            return "Behind remote"
        if "..." in out:
            return "Diverged"
        return "In sync"

    def get_origin_url(self) -> str:
        _, remote = self._run_git(["remote", "get-url", "origin"])
        return remote or ""

    @staticmethod
    def urls_match(remote_a: str, remote_b: str) -> bool:
        from shipmate_user_config import normalize_remote_url

        if not remote_a or not remote_b:
            return False
        return normalize_remote_url(remote_a) == normalize_remote_url(remote_b)

    def get_working_tree_summary(self) -> dict:
        code, out = self._run_git(["status", "--porcelain"])
        if code != 0:
            return {
                "clean": False,
                "modified": 0,
                "untracked": 0,
                "staged": 0,
                "lines": [],
                "error": out,
            }
        lines = [ln for ln in out.splitlines() if ln.strip()]
        modified = untracked = staged = 0
        for ln in lines:
            if len(ln) < 2:
                continue
            x, y = ln[0], ln[1]
            if x != " " and x != "?":
                staged += 1
            if y != " " and y != "?":
                modified += 1
            if x == "?" and y == "?":
                untracked += 1
        return {
            "clean": len(lines) == 0,
            "modified": modified,
            "untracked": untracked,
            "staged": staged,
            "lines": lines,
        }

    @staticmethod
    def list_remote_branches_for_url(clone_url: str) -> tuple[bool, list[str], str]:
        try:
            res = subprocess.run(
                ["git", "ls-remote", "--heads", clone_url],
                capture_output=True,
                text=True,
                check=True,
            )
            branches = []
            for line in res.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) == 2 and parts[1].startswith("refs/heads/"):
                    branches.append(parts[1].replace("refs/heads/", ""))
            return True, sorted(branches), ""
        except subprocess.CalledProcessError as e:
            err = (e.stderr or e.stdout or str(e)).strip()
            return False, [], err

    def list_remote_branches(self) -> tuple[bool, list[str], str]:
        _, remote = self._run_git(["remote", "get-url", "origin"])
        if not remote:
            return False, [], "No origin remote configured"
        return self.list_remote_branches_for_url(remote)

    def checkout_branch(self, branch: str) -> tuple[bool, str]:
        self._run_git(["fetch", "origin", branch])
        code, out = self._run_git(["checkout", "-B", branch, f"origin/{branch}"])
        if code != 0:
            code2, out2 = self._run_git(["checkout", branch])
            if code2 != 0:
                return False, out2 or out
        return True, f"Checked out {branch}"

    def create_backup_stash(self, label: str) -> tuple[bool, str]:
        code, out = self._run_git(["stash", "push", "-u", "-m", label])
        if code != 0:
            if "No local changes" in out:
                return True, ""
            return False, out
        return True, label

    def apply_backup_stash(self) -> tuple[bool, str]:
        code, out = self._run_git(["stash", "apply"])
        if code != 0:
            return False, out
        return True, out

    def abort_stash_apply(self) -> tuple[bool, str]:
        code, out = self._run_git(["reset", "--hard", "HEAD"])
        if code != 0:
            return False, out
        return True, "Stash apply aborted; working tree reset to HEAD"

    def discard_all_changes(self) -> tuple[bool, str]:
        code, out = self._run_git(["reset", "--hard", "HEAD"])
        if code != 0:
            return False, out
        code2, out2 = self._run_git(["clean", "-fd"])
        if code2 != 0:
            return False, out2
        return True, "All uncommitted changes discarded"

    def get_head_commit(self) -> dict:
        code, full = self._run_git(["rev-parse", "HEAD"])
        if code != 0:
            return {"hash": "", "short": "", "message": full or "Unknown"}
        _, short = self._run_git(["rev-parse", "--short", "HEAD"])
        _, message = self._run_git(["log", "-1", "--pretty=%s"])
        return {
            "hash": full,
            "short": short or full[:7],
            "message": message or "",
        }

    @staticmethod
    def get_remote_default_branch(clone_url: str) -> tuple[str, str]:
        """Return (branch_name, head_hash) for remote default branch."""
        try:
            res = subprocess.run(
                ["git", "ls-remote", "--symref", clone_url, "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            branch = "main"
            head_hash = ""
            for line in res.stdout.splitlines():
                if line.startswith("ref:"):
                    parts = line.split("\t")
                    if parts:
                        ref = parts[0].replace("ref: refs/heads/", "").strip()
                        branch = ref or branch
                elif line and not line.startswith("ref:"):
                    head_hash = line.split("\t")[0].strip()
            if not head_hash:
                res2 = subprocess.run(
                    ["git", "ls-remote", clone_url, f"refs/heads/{branch}"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                for line in res2.stdout.splitlines():
                    if line.strip():
                        head_hash = line.split("\t")[0].strip()
                        break
            return branch, head_hash
        except subprocess.CalledProcessError:
            return "main", ""

    @staticmethod
    def get_remote_head(clone_url: str, branch: str) -> str:
        try:
            res = subprocess.run(
                ["git", "ls-remote", clone_url, f"refs/heads/{branch}"],
                capture_output=True,
                text=True,
                check=True,
            )
            for line in res.stdout.splitlines():
                if line.strip():
                    return line.split("\t")[0].strip()
        except subprocess.CalledProcessError:
            pass
        return ""

    def count_commits_ahead_behind(self, remote_ref: str) -> dict:
        """Compare HEAD to remote_ref (e.g. origin/main)."""
        self._run_git(["fetch", "origin", "--quiet"])
        code, out = self._run_git(
            ["rev-list", "--left-right", "--count", f"HEAD...{remote_ref}"]
        )
        if code != 0:
            return {"ahead": 0, "behind": 0, "error": out}
        parts = out.split()
        if len(parts) == 2:
            return {"ahead": int(parts[0]), "behind": int(parts[1])}
        return {"ahead": 0, "behind": 0}

    def get_ahead_behind_origin(self) -> dict:
        branch = self.get_git_identity().get("branch", "")
        if not branch:
            return {"ahead": 0, "behind": 0}
        return self.count_commits_ahead_behind(f"origin/{branch}")
