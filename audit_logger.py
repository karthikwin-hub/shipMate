import json
import os
from datetime import datetime, timezone

from config_loader import get_audit_file


def _audit_path() -> str:
    return get_audit_file()


def _load_entries() -> list:
    path = _audit_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def log_action(
    project: str,
    git_user: str,
    stage: str,
    branch: str,
    action: str,
    status: str,
    checklist_items=None,
    next_step: str = None,
    host_override: bool = False,
    details: str = None,
) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "git_user": git_user,
        "stage": stage,
        "branch": branch,
        "action": action,
        "status": status,
        "checklist_items": checklist_items or [],
        "next_step": next_step,
        "host_override": host_override,
        "details": details,
    }
    entries = _load_entries()
    entries.append(entry)
    path = _audit_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def get_entries() -> list:
    return _load_entries()
