"""Async cross-environment inspection and workflow suggestions for Fleet Matrix."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from audit_analytics import suggest_current_stage
from checklist_engine import ChecklistEngine
from git_manager import GitManager
from project_config import get_provider_name
from remote_deployer import RemoteDeployer
from repo_resolver import cache_path_for_remote, parse_remote_url, validate_local_repo
from shipmate_user_config import normalize_remote_url

CACHE_TTL_SECONDS = 60
_inspection_cache: dict[str, tuple[float, dict]] = {}


@dataclass
class TierSnapshot:
    reachable: bool = False
    status: str = "unreachable"
    branch: str | None = None
    commit: str | None = None
    commit_short: str | None = None
    message: str | None = None
    path: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProjectInspection:
    project_id: str
    name: str = ""
    stack: str = ""
    remote_url: str = ""
    tiers: dict = field(default_factory=dict)
    divergence: dict = field(default_factory=dict)
    inspected_at: str = ""
    suggestion: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "stack": self.stack,
            "remote_url": self.remote_url,
            "tiers": self.tiers,
            "divergence": self.divergence,
            "inspected_at": self.inspected_at,
            "suggestion": self.suggestion,
        }


def _display_path(path: str) -> str:
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home):].replace("\\", "/")
    return path


def _resolve_qa_path(project: dict) -> str:
    qa_path = project.get("qa_path", "")
    if qa_path and os.path.isdir(qa_path):
        return qa_path
    remote = project.get("remote_url", "")
    if remote:
        try:
            _, owner, repo_name, _ = parse_remote_url(remote)
            cache = cache_path_for_remote(owner, repo_name)
            if cache.exists():
                return str(cache)
            return str(cache)
        except ValueError:
            pass
    dev = project.get("dev_path", "")
    return dev or qa_path


def _inspect_dev(project: dict) -> TierSnapshot:
    path = project.get("dev_path", "")
    if not path or not os.path.isdir(path):
        return TierSnapshot(reachable=False, status="unreachable", path=path or None)
    ok, msg = validate_local_repo(path)
    if not ok:
        return TierSnapshot(reachable=False, status="unreachable", path=path, extra={"error": msg})

    git = GitManager(path)
    identity = git.get_git_identity()
    head = git.get_head_commit()
    wt = git.get_working_tree_summary()
    ahead_behind = git.get_ahead_behind_origin()
    status = "clean" if wt.get("clean") else "dirty"
    if ahead_behind.get("ahead", 0) > 0:
        status = "ahead"

    return TierSnapshot(
        reachable=True,
        status=status,
        branch=identity.get("branch"),
        commit=head.get("hash"),
        commit_short=head.get("short"),
        message=head.get("message"),
        path=_display_path(path),
        extra={
            "sync": git.get_sync_status(),
            "ahead": ahead_behind.get("ahead", 0),
            "behind": ahead_behind.get("behind", 0),
            "working_tree": wt,
        },
    )


def _inspect_remote(project: dict, dev_tier: TierSnapshot) -> TierSnapshot:
    remote_url = project.get("remote_url", "")
    if not remote_url:
        return TierSnapshot(reachable=False, status="unconfigured")

    branch = "main"
    pr = {"state": "NONE", "number": None, "title": "", "reviewDecision": ""}
    dev_path = project.get("dev_path", "")
    if dev_path and os.path.isdir(dev_path):
        ok, _ = validate_local_repo(dev_path)
        if ok:
            pr = GitManager(dev_path).get_pr_status()
            if pr.get("state") != "NONE":
                branch = GitManager(dev_path).get_git_identity().get("branch", branch)

    default_branch, default_hash = GitManager.get_remote_default_branch(remote_url)
    if pr.get("state") == "NONE":
        branch = default_branch
        head_hash = default_hash
    else:
        head_hash = GitManager.get_remote_head(remote_url, branch) or default_hash

    short = head_hash[:7] if head_hash else ""
    pr_state = pr.get("state", "NONE")
    status = "synced"
    if pr_state == "OPEN":
        status = "pr_open"
    elif pr_state == "MERGED":
        status = "merged"

    return TierSnapshot(
        reachable=True,
        status=status,
        branch=branch,
        commit=head_hash,
        commit_short=short,
        message=pr.get("title") or f"Remote {branch}",
        extra={
            "pr": {
                "number": pr.get("number"),
                "state": pr_state,
                "title": pr.get("title", ""),
                "reviewDecision": pr.get("reviewDecision", ""),
                "url": pr.get("url", ""),
            },
            "default_branch": default_branch,
            "ci": "unknown",
            "remote_display": normalize_remote_url(remote_url),
        },
    )


def _inspect_qa(project: dict, remote_tier: TierSnapshot) -> TierSnapshot:
    path = _resolve_qa_path(project)
    if not path or not os.path.isdir(path):
        return TierSnapshot(
            reachable=False,
            status="unreachable",
            path=_display_path(path) if path else None,
            extra={"delta": "Path not available on this machine"},
        )
    ok, msg = validate_local_repo(path)
    if not ok:
        return TierSnapshot(
            reachable=False,
            status="unreachable",
            path=_display_path(path),
            extra={"error": msg},
        )

    git = GitManager(path)
    identity = git.get_git_identity()
    head = git.get_head_commit()
    wt = git.get_working_tree_summary()

    remote_branch = remote_tier.branch or "main"
    delta_label = "Up to date"
    behind = 0
    try:
        git._run_git(["fetch", "origin", "--quiet"])
        ab = git.count_commits_ahead_behind(f"origin/{remote_branch}")
        behind = ab.get("behind", 0)
        if behind > 0:
            delta_label = f"{behind} commit(s) behind"
        elif ab.get("ahead", 0) > 0:
            delta_label = f"{ab.get('ahead')} commit(s) ahead"
    except Exception:
        delta_label = "Unknown"

    status = "synced" if behind == 0 and wt.get("clean") else "behind" if behind > 0 else "dirty"
    if not wt.get("clean"):
        status = "manual_test"

    return TierSnapshot(
        reachable=True,
        status=status,
        branch=identity.get("branch"),
        commit=head.get("hash"),
        commit_short=head.get("short"),
        message=head.get("message"),
        path=_display_path(path),
        extra={"delta": delta_label, "behind": behind, "working_tree": wt},
    )


def _probe_health(health_url: str) -> dict:
    if not health_url:
        return {"ok": False, "status_code": None, "label": "No health URL"}
    try:
        start = time.time()
        res = requests.get(health_url, timeout=10)
        latency = int((time.time() - start) * 1000)
        ok = res.status_code == 200
        return {
            "ok": ok,
            "status_code": res.status_code,
            "latency_ms": latency,
            "label": f"{res.status_code} OK" if ok else f"HTTP {res.status_code}",
        }
    except Exception as e:
        return {"ok": False, "status_code": None, "label": f"Timeout: {e}"}


def _inspect_prod(project: dict, remote_tier: TierSnapshot) -> TierSnapshot:
    provider = project.get("provider") or get_provider_name(project.get("dev_path", "") or "")
    health_url = project.get("health_url", "")
    health = _probe_health(health_url)

    host = project.get("prod_ssh_host", "")
    remote_path = project.get("prod_remote_path", "")
    commit_hash = ""
    tag = ""
    ssh_ok = False

    if provider == "oracle_vm" and host:
        cfg = {
            "host": host,
            "user": "ubuntu",
            "key_path": "~/.ssh/id_rsa",
            "remote_path": remote_path or "/var/www/myapp",
            "health_url": health_url,
        }
        deployer = RemoteDeployer(cfg)
        try:
            code, out = deployer.execute_ssh_cmd("git rev-parse HEAD")
            if code == 0:
                commit_hash = out.strip()
                ssh_ok = True
            code2, tag_out = deployer.execute_ssh_cmd("git describe --tags --always 2>/dev/null || git rev-parse --short HEAD")
            if code2 == 0:
                tag = tag_out.strip()
        except Exception as e:
            return TierSnapshot(
                reachable=False,
                status="unreachable",
                path=host,
                extra={"provider": provider, "health": health, "error": str(e)},
            )
    else:
        ssh_ok = bool(health.get("ok"))

    short = commit_hash[:7] if commit_hash else ""
    status = "ok" if health.get("ok") else "timeout"
    if provider != "oracle_vm":
        status = "ok" if health.get("ok") else "timeout"

    behind_main = 0
    main_hash = remote_tier.commit or ""
    if commit_hash and main_hash and commit_hash != main_hash:
        status = "behind"

    return TierSnapshot(
        reachable=ssh_ok or bool(health.get("ok")) or provider != "oracle_vm",
        status=status,
        branch="main",
        commit=commit_hash or None,
        commit_short=short or None,
        message=tag or health.get("label", ""),
        path=host or provider,
        extra={
            "provider": provider,
            "health": health,
            "tag": tag,
            "remote_path": remote_path,
            "ssh_available": provider == "oracle_vm" and bool(host),
            "behind_main": behind_main,
        },
    )


def _compute_divergence(
    dev: TierSnapshot,
    remote: TierSnapshot,
    qa: TierSnapshot,
    prod: TierSnapshot,
) -> dict:
    div: dict[str, str] = {}
    if dev.reachable and remote.reachable:
        if dev.extra.get("ahead", 0) > 0:
            div["dev_vs_remote"] = f"{dev.extra['ahead']} commit(s) ahead"
        elif dev.commit and remote.commit and dev.commit == remote.commit:
            div["dev_vs_remote"] = "In sync"
        else:
            div["dev_vs_remote"] = dev.extra.get("sync", "Unknown")
    if qa.reachable:
        div["qa_vs_remote"] = qa.extra.get("delta", "Unknown")
    if prod.reachable and remote.reachable and prod.commit and remote.commit:
        if prod.commit == remote.commit:
            div["prod_vs_main"] = "Deployed"
        else:
            div["prod_vs_main"] = "Production differs from remote main"
    return div


def _checklist_progress(repo_path: str) -> dict:
    if not repo_path or not os.path.isdir(repo_path):
        return {"total": 0, "done": 0, "all_passed": False}
    try:
        engine = ChecklistEngine(repo_path)
        items = engine.get_stage_items("qa")
        manual_ids = [i["id"] for i in items if i.get("type") == "manual"]
        return {
            "total": len(items),
            "done": 0,
            "all_passed": False,
            "manual_total": len(manual_ids),
            "manual_done": 0,
        }
    except Exception:
        return {"total": 0, "done": 0, "all_passed": False}


def suggest_next_step(
    project: dict,
    inspection: ProjectInspection,
) -> dict:
    dev = inspection.tiers.get("dev", {})
    remote = inspection.tiers.get("remote", {})
    qa = inspection.tiers.get("qa", {})
    prod = inspection.tiers.get("prod", {})
    target_repo = project.get("dev_path") or project.get("qa_path") or ""

    dev_ahead = (dev.get("extra") or {}).get("ahead", 0)
    dev_dirty = dev.get("status") == "dirty"
    pr_state = (remote.get("extra") or {}).get("pr", {}).get("state", "NONE")
    qa_behind = (qa.get("extra") or {}).get("behind", 0)
    checklist = _checklist_progress(project.get("qa_path") or project.get("dev_path", ""))

    if dev_dirty or dev_ahead > 0:
        return {
            "title": "Push changes and open PR",
            "detail": "Dev has unpushed or uncommitted changes.",
            "action": "dev_ship",
            "cta_label": "Open Dev Stage",
            "priority": "high",
            "target_repo": target_repo,
        }

    if pr_state == "OPEN" and qa_behind > 0:
        return {
            "title": "Pull latest PR branch into QA",
            "detail": f"QA is {qa_behind} commit(s) behind the remote PR branch.",
            "action": "qa_pull",
            "cta_label": "Pull & Setup QA",
            "priority": "high",
            "target_repo": project.get("qa_path") or target_repo,
        }

    prod_commit = prod.get("commit")
    remote_commit = remote.get("commit")
    if prod_commit and remote_commit and prod_commit != remote_commit:
        return {
            "title": "Production is behind remote main — Ready for Deploy",
            "detail": "Prod commit differs from remote default branch.",
            "action": "prod_deploy",
            "cta_label": "Deploy to Live",
            "priority": "high",
            "target_repo": target_repo,
        }

    if checklist.get("total") and not checklist.get("all_passed"):
        done = checklist.get("done", 0)
        total = checklist.get("total", 0)
        return {
            "title": f"QA checklist is {done}/{total} complete",
            "detail": "Finish smoke testing to unlock Approve & Merge.",
            "action": "qa_checklist",
            "cta_label": "Open QA Stage",
            "priority": "medium",
            "target_repo": target_repo,
        }

    if pr_state == "MERGED" or (qa.get("status") == "synced" and checklist.get("all_passed")):
        provider = project.get("provider", "oracle_vm")
        label = "Oracle VM" if provider == "oracle_vm" else provider.title()
        return {
            "title": f"Deploy main to {label}",
            "detail": "QA checks passed and branch is synced.",
            "action": "prod_deploy",
            "cta_label": "Deploy to Live",
            "priority": "medium",
            "target_repo": target_repo,
        }

    stage = suggest_current_stage(target_repo) if target_repo else "dev"
    return {
        "title": f"Continue at {stage.upper()} stage",
        "detail": "No blocking divergence detected.",
        "action": f"stage_{stage}",
        "cta_label": "Open Pipeline",
        "priority": "low",
        "target_repo": target_repo,
    }


def inspect_project_sync(project: dict) -> ProjectInspection:
    dev = _inspect_dev(project)
    remote = _inspect_remote(project, dev)
    qa = _inspect_qa(project, remote)
    prod = _inspect_prod(project, remote)

    tiers = {
        "dev": dev.to_dict(),
        "remote": remote.to_dict(),
        "qa": qa.to_dict(),
        "prod": prod.to_dict(),
    }
    divergence = _compute_divergence(dev, remote, qa, prod)
    inspection = ProjectInspection(
        project_id=project.get("project_id", ""),
        name=project.get("name", ""),
        stack=project.get("stack", ""),
        remote_url=normalize_remote_url(project.get("remote_url", "")),
        tiers=tiers,
        divergence=divergence,
        inspected_at=datetime.now(timezone.utc).isoformat(),
    )
    inspection.suggestion = suggest_next_step(project, inspection)
    return inspection


async def inspect_project(project: dict) -> ProjectInspection:
    return await asyncio.to_thread(inspect_project_sync, project)


async def inspect_fleet(
    projects: list[dict],
    *,
    use_cache: bool = True,
    bypass_cache: bool = False,
) -> list[dict]:
    now = time.time()

    async def _inspect_one(p: dict) -> dict:
        pid = p.get("project_id", "")
        if use_cache and not bypass_cache and pid in _inspection_cache:
            ts, cached = _inspection_cache[pid]
            if now - ts < CACHE_TTL_SECONDS:
                return cached
        result = await inspect_project(p)
        payload = result.to_dict()
        _inspection_cache[pid] = (time.time(), payload)
        return payload

    results = await asyncio.gather(*[_inspect_one(p) for p in projects])
    return list(results)


def get_cached_suggestion(project_id: str) -> dict | None:
    entry = _inspection_cache.get(project_id)
    if not entry:
        return None
    return entry[1].get("suggestion")


def clear_inspection_cache() -> None:
    _inspection_cache.clear()
