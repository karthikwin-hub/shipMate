from datetime import datetime, timedelta, timezone

import audit_logger


def _parse_ts(entry: dict) -> datetime | None:
    ts = entry.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_distinct_projects() -> list[str]:
    projects = {e.get("project", "") for e in audit_logger.get_entries() if e.get("project")}
    return sorted(projects)


def get_project_timeline(project_path: str, limit: int = 50) -> list[dict]:
    entries = [
        e for e in audit_logger.get_entries()
        if e.get("project") == project_path
    ]
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return entries[:limit]


def get_project_summary(project_path: str) -> dict:
    entries = [e for e in audit_logger.get_entries() if e.get("project") == project_path]
    if not entries:
        return {
            "project": project_path,
            "last_activity": None,
            "last_stage": None,
            "last_status": None,
            "last_action": None,
            "total_runs": 0,
            "failures": 0,
            "stage_counts": {},
        }
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    latest = entries[0]
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent = [e for e in entries if _parse_ts(e) and _parse_ts(e) >= cutoff]
    stage_counts = {}
    failures = 0
    for e in entries:
        stage = e.get("stage", "unknown")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        if e.get("status") == "failure":
            failures += 1
    return {
        "project": project_path,
        "last_activity": latest.get("timestamp"),
        "last_stage": latest.get("stage"),
        "last_status": latest.get("status"),
        "last_action": latest.get("action"),
        "last_branch": latest.get("branch"),
        "last_git_user": latest.get("git_user"),
        "total_runs": len(entries),
        "runs_7d": len(recent),
        "failures": failures,
        "failures_7d": sum(1 for e in recent if e.get("status") == "failure"),
        "stage_counts": stage_counts,
    }


def get_all_projects_overview() -> list[dict]:
    summaries = [get_project_summary(p) for p in get_distinct_projects()]
    summaries.sort(key=lambda s: s.get("last_activity") or "", reverse=True)
    return summaries


def suggest_current_stage(project_path: str) -> str:
    entries = get_project_timeline(project_path, limit=20)
    stage_order = {"dev": 1, "qa": 2, "prod": 3}
    best = "dev"
    for e in reversed(entries):
        if e.get("status") == "success":
            stage = e.get("stage", "dev")
            if stage_order.get(stage, 0) >= stage_order.get(best, 0):
                best = stage
                if stage == "prod" and e.get("action") == "deploy":
                    return "prod"
    if best == "dev" and any(e.get("stage") == "qa" for e in entries):
        return "qa"
    return best
