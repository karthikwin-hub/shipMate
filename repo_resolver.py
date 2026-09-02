"""Resolve local repo paths or clone remote Git URLs with data-safe sync."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from git_manager import GitManager
from shipmate_user_config import (
    get_registered_paths,
    normalize_remote_url,
    register_local_path,
    set_last_mode,
)

REPOS_CACHE = Path.home() / ".shipmate" / "repos"


@dataclass
class SyncResult:
    ok: bool
    path: str = ""
    message: str = ""
    status: str = "ok"  # ok | needs_choice | error
    repo_mode: str = "local"  # local | cache
    stash_label: str | None = None
    remote: str | None = None
    branch: str | None = None
    matches: list[dict] = field(default_factory=list)
    working_tree: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "valid": self.ok,
            "repo": self.path,
            "message": self.message,
            "status": self.status,
            "repo_mode": self.repo_mode,
            "stash_label": self.stash_label,
            "remote": self.remote,
            "branch": self.branch,
            "matches": self.matches,
            "working_tree": self.working_tree,
        }


def is_remote_url(value: str) -> bool:
    v = value.strip()
    if not v:
        return False
    if v.startswith(("https://", "http://", "git@", "ssh://")):
        return True
    return bool(re.match(r"^[\w.-]+@[\w.-]+:", v))


def _sanitize_path_segment(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(". ") or "repository"


def parse_remote_url(url: str) -> tuple[str, str, str, str | None]:
    """
    Parse remote URL with optional branch suffix.
    Returns (clone_url, owner, repo_name, branch).
    """
    raw = url.strip()
    branch: str | None = None

    if "#" in raw and "@" in raw.split("#")[0]:
        raise ValueError("Use either #branch or @branch, not both")

    if "#" in raw:
        base, branch = raw.split("#", 1)
        raw = base.strip()
        branch = branch.strip() or None
    elif "@" in raw and not raw.startswith("git@"):
        # https://github.com/o/r@dev — last @ after domain
        match = re.match(r"^(https?://[^@]+@[^/]+/.+?)@([^/@]+)$", raw)
        if not match:
            match = re.match(r"^(https?://[^/]+/[^@]+)@(.+)$", raw)
        if match:
            raw = match.group(1)
            branch = match.group(2).strip() or None

    clone_url = raw.rstrip("/")
    if clone_url.endswith(".git"):
        clone_url_base = clone_url[:-4]
    else:
        clone_url_base = clone_url
        if clone_url.startswith("git@"):
            pass
        elif "github.com" in clone_url or "gitlab.com" in clone_url:
            clone_url = clone_url + ".git"

    if clone_url.startswith("git@"):
        # git@github.com:owner/repo
        parts = clone_url.replace(":", "/").split("/")
        owner = _sanitize_path_segment(parts[-2] if len(parts) >= 2 else "unknown")
        repo_name = _sanitize_path_segment(parts[-1].replace(".git", ""))
    else:
        path_part = clone_url_base.replace("https://", "").replace("http://", "")
        segments = [s for s in path_part.split("/") if s and s != "git"]
        owner = _sanitize_path_segment(segments[-2] if len(segments) >= 2 else "unknown")
        repo_name = _sanitize_path_segment(segments[-1] if segments else "repository")

    return clone_url, owner, repo_name, branch


def cache_path_for_remote(owner: str, repo_name: str) -> Path:
    return REPOS_CACHE / owner / repo_name


def validate_local_repo(repo_dir: str) -> tuple[bool, str]:
    if not os.path.exists(repo_dir):
        return False, f"Local path does not exist: {repo_dir}"
    if not os.path.exists(os.path.join(repo_dir, ".git")):
        return False, "Not a Git repository (missing .git directory)"
    return True, "OK"


def _attach_working_tree(path: str) -> dict:
    return GitManager(path).get_working_tree_summary()


def is_cache_path(path: str) -> bool:
    try:
        resolved = Path(path).resolve()
        cache_root = REPOS_CACHE.resolve()
        return cache_root in resolved.parents or resolved == cache_root
    except OSError:
        return False


def discover_local_match(remote_input: str) -> dict:
    clone_url, owner, repo_name, branch = parse_remote_url(remote_input)
    norm = normalize_remote_url(clone_url)
    matches = []

    for entry in get_registered_paths():
        local_path = entry.get("path", "")
        if not local_path or not os.path.isdir(local_path):
            continue
        if not os.path.exists(os.path.join(local_path, ".git")):
            continue
        git = GitManager(local_path)
        origin = git.get_origin_url()
        if GitManager.urls_match(origin, clone_url) or entry.get("remote") == norm:
            summary = git.get_working_tree_summary()
            matches.append({
                "path": local_path,
                "working_tree": summary,
                "origin": origin,
            })

    if matches:
        return {
            "status": "needs_choice",
            "remote": clone_url,
            "branch": branch,
            "owner": owner,
            "repo_name": repo_name,
            "matches": matches,
        }
    return {
        "status": "no_match",
        "remote": clone_url,
        "branch": branch,
        "owner": owner,
        "repo_name": repo_name,
        "matches": [],
    }


def safe_cache_sync(
    dest: Path,
    clone_url: str,
    branch: str | None,
) -> SyncResult:
    dest.parent.mkdir(parents=True, exist_ok=True)
    stash_label: str | None = None

    if not dest.exists() or not (dest / ".git").exists():
        cmd = ["git", "clone", clone_url, str(dest)]
        if branch:
            cmd = ["git", "clone", "-b", branch, clone_url, str(dest)]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            err = (e.stderr or e.stdout or str(e)).strip()
            return SyncResult(False, "", f"Clone failed: {err}", status="error", repo_mode="cache")
        git = GitManager(str(dest))
        wt = git.get_working_tree_summary()
        msg = f"Cloned to {dest}"
        if branch:
            msg += f" (branch {branch})"
        return SyncResult(True, str(dest.resolve()), msg, repo_mode="cache", branch=branch, working_tree=wt)

    git = GitManager(str(dest))
    summary = git.get_working_tree_summary()
    if not summary.get("clean"):
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stash_label = f"shipmate-auto-backup-{ts}"
        ok, err = git.create_backup_stash(stash_label)
        if not ok:
            return SyncResult(
                False,
                str(dest.resolve()),
                f"Could not stash local changes: {err}",
                status="error",
                repo_mode="cache",
                working_tree=summary,
            )

    try:
        subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=dest,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or str(e)).strip()
        return SyncResult(
            False,
            str(dest.resolve()),
            f"Pull failed: {err}",
            status="error",
            repo_mode="cache",
            stash_label=stash_label,
            working_tree=git.get_working_tree_summary(),
        )

    if branch:
        ok, msg = git.checkout_branch(branch)
        if not ok:
            return SyncResult(
                False,
                str(dest.resolve()),
                f"Branch checkout failed: {msg}",
                status="error",
                repo_mode="cache",
                stash_label=stash_label,
                branch=branch,
                working_tree=git.get_working_tree_summary(),
            )

    if stash_label:
        ok, err = git.apply_backup_stash()
        if not ok:
            git.abort_stash_apply()
            return SyncResult(
                False,
                str(dest.resolve()),
                f"Cache has uncommitted modifications that conflict with upstream. "
                f"Stash preserved as `{stash_label}`.",
                status="error",
                repo_mode="cache",
                stash_label=stash_label,
                branch=branch,
                working_tree=git.get_working_tree_summary(),
            )

    wt = git.get_working_tree_summary()
    msg = f"Pulled latest into {dest}"
    if stash_label:
        msg += f" (restored stash `{stash_label}`)"
    return SyncResult(
        True,
        str(dest.resolve()),
        msg,
        repo_mode="cache",
        stash_label=stash_label,
        branch=branch,
        working_tree=wt,
    )


def sync_repo(
    repo_input: str,
    *,
    mode: Literal["local", "cache", "auto"] = "auto",
    local_path: str | None = None,
    branch: str | None = None,
) -> SyncResult:
    raw = repo_input.strip()
    if not raw:
        return SyncResult(False, "", "Enter a local path or remote Git URL", status="error")

    if is_remote_url(raw) or ("github.com" in raw and raw.startswith("http")):
        try:
            clone_url, owner, repo_name, parsed_branch = parse_remote_url(raw)
        except ValueError as e:
            return SyncResult(False, "", str(e), status="error")
        use_branch = branch or parsed_branch

        if mode == "auto":
            discovery = discover_local_match(raw)
            if discovery["status"] == "needs_choice":
                return SyncResult(
                    False,
                    "",
                    "Found registered local clone(s) for this remote",
                    status="needs_choice",
                    remote=clone_url,
                    branch=use_branch,
                    matches=discovery["matches"],
                )
            mode = "cache"

        if mode == "local":
            if not local_path:
                return SyncResult(
                    False,
                    "",
                    "local_path required for local mode",
                    status="error",
                )
            ok, msg = validate_local_repo(local_path)
            if not ok:
                return SyncResult(False, "", msg, status="error")
            abs_path = os.path.abspath(local_path)
            register_local_path(abs_path, clone_url)
            set_last_mode(clone_url, "local", abs_path)
            wt = _attach_working_tree(abs_path)
            return SyncResult(
                True,
                abs_path,
                "Using local workspace",
                repo_mode="local",
                remote=clone_url,
                branch=use_branch,
                working_tree=wt,
            )

        dest = cache_path_for_remote(owner, repo_name)
        result = safe_cache_sync(dest, clone_url, use_branch)
        result.remote = clone_url
        if result.ok:
            set_last_mode(clone_url, "cache", result.path)
        return result

    # Local path input
    if not os.path.exists(raw):
        if "github.com" in raw or "gitlab.com" in raw:
            return SyncResult(
                False,
                "",
                "That looks like a web URL without a protocol. "
                "Use https://github.com/user/repo or a local clone path.",
                status="error",
            )
        return SyncResult(
            False,
            "",
            f"Local path does not exist: {raw}. "
            "Clone the repo first, or paste an https:// Git remote URL to auto-clone.",
            status="error",
        )

    ok, msg = validate_local_repo(raw)
    if not ok:
        return SyncResult(False, "", msg, status="error")
    abs_path = os.path.abspath(raw)
    wt = _attach_working_tree(abs_path)
    repo_mode = "cache" if is_cache_path(abs_path) else "local"
    return SyncResult(
        True,
        abs_path,
        "OK",
        repo_mode=repo_mode,
        working_tree=wt,
    )


def discard_cache_changes(repo_path: str) -> SyncResult:
    if not is_cache_path(repo_path):
        return SyncResult(
            False,
            repo_path,
            "Discard is only allowed for ShipMate managed cache paths",
            status="error",
        )
    ok, msg = validate_local_repo(repo_path)
    if not ok:
        return SyncResult(False, "", msg, status="error")
    git = GitManager(repo_path)
    ok, err = git.discard_all_changes()
    wt = git.get_working_tree_summary()
    if not ok:
        return SyncResult(False, repo_path, err, status="error", repo_mode="cache", working_tree=wt)
    return SyncResult(True, repo_path, err, repo_mode="cache", working_tree=wt)


def get_repo_status(repo_path: str) -> dict:
    ok, msg = validate_local_repo(repo_path)
    if not ok:
        return {"valid": False, "error": msg}
    wt = _attach_working_tree(repo_path)
    mode = "cache" if is_cache_path(repo_path) else "local"
    return {
        "valid": True,
        "repo_mode": mode,
        "working_tree": wt,
        "path": repo_path,
        "path_display": _display_path(repo_path),
    }


def _display_path(path: str) -> str:
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home):].replace("\\", "/")
    return path
