"""CRUD for ShipMate fleet project registry (~/.shipmate/projects.json)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from git_manager import GitManager
from project_config import get_effective_oracle_config, get_provider_name, load_deploy_config
from repo_resolver import cache_path_for_remote, parse_remote_url, validate_local_repo
from runner import CommandRunner
from shipmate_user_config import get_registered_paths, normalize_remote_url, register_local_path

PROJECTS_PATH = Path.home() / ".shipmate" / "projects.json"

DEFAULT_STORE = {"projects": []}

PROJECT_FIELDS = (
    "project_id",
    "name",
    "stack",
    "remote_url",
    "dev_path",
    "qa_path",
    "prod_ssh_host",
    "prod_remote_path",
    "health_url",
    "provider",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def load_store() -> dict:
    if not PROJECTS_PATH.exists():
        return dict(DEFAULT_STORE)
    try:
        with open(PROJECTS_PATH, encoding="utf-8") as f:
            data = json.load(f) or {}
        if "projects" not in data or not isinstance(data["projects"], list):
            data["projects"] = []
        return data
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_STORE)


def save_store(store: dict) -> None:
    PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROJECTS_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def list_projects() -> list[dict]:
    projects = list(load_store().get("projects", []))
    return sorted(
        projects,
        key=lambda p: (p.get("last_used_at") or p.get("updated_at") or p.get("created_at") or ""),
        reverse=True,
    )


def touch_project(project_id: str) -> dict:
    store = load_store()
    for i, p in enumerate(store["projects"]):
        if p.get("project_id") == project_id:
            p["last_used_at"] = _now_iso()
            store["projects"][i] = p
            save_store(store)
            return dict(p)
    raise ValueError(f"Project not found: {project_id}")


def get_project(project_id: str) -> dict | None:
    for p in list_projects():
        if p.get("project_id") == project_id:
            return dict(p)
    return None


def _ensure_unique_id(project_id: str, exclude_id: str | None = None) -> None:
    for p in list_projects():
        if p.get("project_id") == project_id and project_id != exclude_id:
            raise ValueError(f"Project id already exists: {project_id}")


def _derive_project_id(data: dict) -> str:
    if data.get("project_id"):
        return _slugify(data["project_id"])
    remote = data.get("remote_url", "")
    if remote:
        try:
            _, _, repo_name, _ = parse_remote_url(remote)
            return _slugify(repo_name)
        except ValueError:
            pass
    return _slugify(data.get("name", "project"))


def _normalize_project(data: dict, *, existing: dict | None = None) -> dict:
    base = dict(existing or {})
    base.update({k: v for k, v in data.items() if k in PROJECT_FIELDS and v is not None})
    if not base.get("name") and base.get("project_id"):
        base["name"] = base["project_id"].replace("-", " ").title()
    return base


def create_project(data: dict) -> dict:
    project = _normalize_project(data)
    project_id = _derive_project_id(project)
    _ensure_unique_id(project_id)
    project["project_id"] = project_id
    project.setdefault("stack", "Generic")
    project.setdefault("provider", "oracle_vm")
    project["created_at"] = _now_iso()
    project["updated_at"] = project["created_at"]

    store = load_store()
    store["projects"].append(project)
    save_store(store)
    _sync_registered_path(project)
    return dict(project)


def update_project(project_id: str, data: dict) -> dict:
    store = load_store()
    for i, p in enumerate(store["projects"]):
        if p.get("project_id") == project_id:
            updated = _normalize_project(data, existing=p)
            updated["project_id"] = project_id
            updated["updated_at"] = _now_iso()
            store["projects"][i] = updated
            save_store(store)
            _sync_registered_path(updated)
            return dict(updated)
    raise ValueError(f"Project not found: {project_id}")


def delete_project(project_id: str) -> bool:
    store = load_store()
    before = len(store["projects"])
    store["projects"] = [p for p in store["projects"] if p.get("project_id") != project_id]
    if len(store["projects"]) == before:
        raise ValueError(f"Project not found: {project_id}")
    save_store(store)
    return True


def _sync_registered_path(project: dict) -> None:
    dev_path = project.get("dev_path", "")
    remote_url = project.get("remote_url", "")
    if dev_path and remote_url and os.path.isdir(dev_path):
        ok, _ = validate_local_repo(dev_path)
        if ok:
            register_local_path(dev_path, remote_url)


def auto_populate_from_path(path: str) -> dict:
    abs_path = os.path.abspath(path)
    ok, msg = validate_local_repo(abs_path)
    if not ok:
        raise ValueError(msg)

    git = GitManager(abs_path)
    origin = git.get_origin_url()
    if not origin:
        raise ValueError("No Git origin configured for this path")

    runner = CommandRunner(abs_path)
    stack = runner.detect_stack()
    provider = get_provider_name(abs_path)
    deploy = load_deploy_config(abs_path).get("deploy") or {}
    oracle = get_effective_oracle_config(abs_path)

    qa_path = abs_path
    try:
        _, owner, repo_name, _ = parse_remote_url(origin)
        qa_path = str(cache_path_for_remote(owner, repo_name))
    except ValueError:
        pass

    name = Path(abs_path).name.replace("-", " ").replace("_", " ").title()
    draft = {
        "name": name,
        "stack": stack,
        "remote_url": origin,
        "dev_path": abs_path,
        "qa_path": qa_path,
        "prod_ssh_host": oracle.get("host", ""),
        "prod_remote_path": oracle.get("remote_path", ""),
        "health_url": deploy.get("health_url", oracle.get("health_url", "")),
        "provider": provider,
    }
    draft["project_id"] = _derive_project_id(draft)
    return draft


def import_from_registered_paths() -> int:
    imported = 0
    existing_remotes = {
        normalize_remote_url(p.get("remote_url", ""))
        for p in list_projects()
        if p.get("remote_url")
    }
    for entry in get_registered_paths():
        path = entry.get("path", "")
        remote = entry.get("remote", "")
        if not path or not os.path.isdir(path):
            continue
        ok, _ = validate_local_repo(path)
        if not ok:
            continue
        git = GitManager(path)
        origin = git.get_origin_url() or remote
        norm = normalize_remote_url(origin)
        if norm in existing_remotes:
            continue
        try:
            create_project(auto_populate_from_path(path))
            existing_remotes.add(norm)
            imported += 1
        except ValueError:
            continue
    return imported
