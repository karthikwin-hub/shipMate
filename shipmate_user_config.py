"""User-level ShipMate config: registered local project paths."""

from __future__ import annotations

import json
import re
from pathlib import Path

CONFIG_PATH = Path.home() / ".shipmate" / "config.json"

DEFAULT_CONFIG = {
    "registered_paths": [],
    "last_mode_by_remote": {},
}


def load_user_config() -> dict:
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f) or {}
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        if "registered_paths" not in merged or not isinstance(merged["registered_paths"], list):
            merged["registered_paths"] = []
        return merged
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


def save_user_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def normalize_remote_url(url: str) -> str:
    """Canonical form for remote URL comparison."""
    u = url.strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    # git@github.com:owner/repo -> github.com/owner/repo
    ssh_match = re.match(r"^[\w.-]+@([^:]+):(.+)$", u)
    if ssh_match:
        host, path = ssh_match.groups()
        u = f"{host.lower()}/{path.lower()}"
    else:
        u = re.sub(r"^https?://", "", u, flags=re.I)
        u = u.lower()
    return u


def get_registered_paths() -> list[dict]:
    return load_user_config().get("registered_paths", [])


def register_local_path(path: str, remote_url: str) -> None:
    config = load_user_config()
    abs_path = str(Path(path).resolve())
    norm_remote = normalize_remote_url(remote_url)
    entries = [
        e for e in config["registered_paths"]
        if e.get("path") != abs_path
    ]
    entries.append({"path": abs_path, "remote": norm_remote})
    config["registered_paths"] = entries
    config.setdefault("last_mode_by_remote", {})[norm_remote] = {
        "mode": "local",
        "path": abs_path,
    }
    save_user_config(config)


def set_last_mode(remote_url: str, mode: str, path: str) -> None:
    config = load_user_config()
    norm = normalize_remote_url(remote_url)
    config.setdefault("last_mode_by_remote", {})[norm] = {"mode": mode, "path": path}
    save_user_config(config)


def get_last_mode(remote_url: str) -> dict | None:
    norm = normalize_remote_url(remote_url)
    return load_user_config().get("last_mode_by_remote", {}).get(norm)
