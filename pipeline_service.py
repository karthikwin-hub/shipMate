"""Pipeline orchestration — extracted from Streamlit app.py, no UI dependencies."""

from __future__ import annotations

import os
import platform
from collections.abc import Generator
from typing import Any

import audit_analytics
import audit_logger
from checklist_engine import ChecklistEngine
from config_loader import get_secrets_config
from deploy_providers.factory import get_deploy_provider
from git_manager import GitManager
from notifications import NotificationManager
from project_config import (
    get_provider_name,
    get_required_secrets,
    load_deploy_config,
    validate_deploy_config,
)
from runner import CommandRunner
from secrets_vault import LocalVaultBackend, get_secrets_backend
from session_manager import RepoSessionState, session_manager

HOST_OS = platform.system()
PRIMARY_STAGE = {"Windows": "dev", "Linux": "qa"}.get(HOST_OS, "dev")
STAGE_LABELS = {"dev": "Stage 1: Dev", "qa": "Stage 2: QA", "prod": "Stage 3: Prod"}


from repo_resolver import (
    discover_local_match,
    discard_cache_changes,
    get_repo_status,
    is_remote_url,
    parse_remote_url,
    sync_repo,
    validate_local_repo,
)


def validate_repo(repo_dir: str) -> tuple[bool, str]:
    ok, msg = validate_local_repo(repo_dir)
    return ok, msg


def stage_enabled(state: RepoSessionState, stage: str) -> bool:
    if stage == PRIMARY_STAGE:
        return True
    return state.host_overrides.get(stage, False)


def _log_audit(
    git: GitManager,
    repo_dir: str,
    stage: str,
    action: str,
    status: str,
    host_override: bool = False,
    details: str | None = None,
) -> None:
    identity = git.get_git_identity()
    git_user = f"{identity['name']} <{identity['email']}>"
    audit_logger.log_action(
        project=repo_dir,
        git_user=git_user,
        stage=stage,
        branch=identity["branch"],
        action=action,
        status=status,
        host_override=host_override,
        details=details,
    )


def _append_log(state: RepoSessionState, stage: str, text: str) -> None:
    state.stage_logs.setdefault(stage, []).append(text)


def _line(text: str) -> dict[str, Any]:
    return {"type": "line", "text": text}


def _done(success: bool, message: str = "") -> dict[str, Any]:
    return {"type": "done", "success": success, "message": message}


def _services(repo_dir: str):
    git = GitManager(repo_dir)
    runner = CommandRunner(repo_dir)
    deploy_provider = get_deploy_provider(repo_dir)
    checklist = ChecklistEngine(repo_dir, prod_builtin=deploy_provider.get_builtin_checks())
    notifier = NotificationManager()
    return git, runner, deploy_provider, checklist, notifier


def get_context(session_id: str, repo_dir: str) -> dict[str, Any]:
    ok, msg = validate_local_repo(repo_dir)
    if not ok:
        return {"valid": False, "error": msg}

    git, runner, deploy_provider, checklist, _ = _services(repo_dir)
    identity = git.get_git_identity()
    state = session_manager.get(session_id, repo_dir)
    deploy_cfg = load_deploy_config(repo_dir)
    required_secrets = get_required_secrets(repo_dir)
    suggested = audit_analytics.suggest_current_stage(repo_dir)
    repo_status = get_repo_status(repo_dir)

    return {
        "valid": True,
        "repo": repo_dir,
        "identity": identity,
        "pr_status": git.format_pr_status(),
        "stack": runner.detect_stack(),
        "provider_name": get_provider_name(repo_dir),
        "provider_label": deploy_provider.label,
        "suggested_stage": suggested,
        "host_os": HOST_OS,
        "primary_stage": PRIMARY_STAGE,
        "stage_labels": STAGE_LABELS,
        "stage_statuses": state.stage_statuses,
        "host_overrides": state.host_overrides,
        "qa_running": runner.qa_running,
        "required_secrets": required_secrets,
        "has_deploy_config": bool(deploy_cfg),
        "session": session_manager.snapshot(session_id, repo_dir),
        "repo_mode": repo_status.get("repo_mode", "local"),
        "working_tree": repo_status.get("working_tree", {}),
        "path_display": repo_status.get("path_display", repo_dir),
    }


def get_checklist_view(session_id: str, repo_dir: str, stage: str) -> dict[str, Any]:
    _, _, deploy_provider, checklist, _ = _services(repo_dir)
    state = session_manager.get(session_id, repo_dir)
    items = []
    for item in checklist.get_stage_items(stage):
        item_id = item["id"]
        item_type = item.get("type", "manual")
        if item_type == "builtin":
            checked = state.checklist_builtin.get(item_id, False)
        elif item_type == "automated_command":
            checked = state.checklist_automated.get(item_id, False)
        else:
            checked = state.checklist_manual.get(item_id, False)
        items.append({**item, "checked": checked})

    all_passed = checklist.all_passed(
        stage,
        state.checklist_manual,
        state.checklist_builtin,
        state.checklist_automated,
    )
    vault = get_secrets_backend()
    secrets_ok, missing = vault.check_required(repo_dir, get_required_secrets(repo_dir))
    if stage == "prod":
        all_passed = all_passed and secrets_ok

    return {
        "items": items,
        "all_passed": all_passed,
        "secrets_ok": secrets_ok,
        "missing_secrets": missing,
        "stage_enabled": stage_enabled(state, stage),
        "builtin_checks": deploy_provider.get_builtin_checks() if stage == "prod" else [],
    }


def update_checklist_manual(
    session_id: str, repo_dir: str, item_id: str, checked: bool
) -> None:
    state = session_manager.get(session_id, repo_dir)
    state.checklist_manual[item_id] = checked


def set_host_override(session_id: str, repo_dir: str, stage: str, enabled: bool) -> None:
    state = session_manager.get(session_id, repo_dir)
    state.host_overrides[stage] = enabled


def override_identity(repo_dir: str, name: str, email: str) -> tuple[bool, str]:
    git = GitManager(repo_dir)
    ok, msg = git.set_local_identity(name, email)
    if ok:
        _log_audit(git, repo_dir, "dev", "identity_override", "success")
    return ok, msg


def get_live_status(repo_dir: str) -> dict[str, Any]:
    _, _, deploy_provider, _, _ = _services(repo_dir)
    label = deploy_provider.label
    if deploy_provider.name == "oracle_vm":
        try:
            health = deploy_provider.get_health_monitor()
            if health.get("health_status") == 200:
                return {
                    "label": label,
                    "reachable": True,
                    "latency_ms": health.get("latency_ms"),
                    "status": "live",
                }
            if health.get("reachable"):
                return {
                    "label": label,
                    "reachable": True,
                    "latency_ms": health.get("latency_ms"),
                    "status": "reachable",
                }
            return {"label": label, "reachable": False, "latency_ms": None, "status": "offline"}
        except Exception:
            return {"label": label, "reachable": False, "latency_ms": None, "status": "unknown"}
    return {"label": label, "reachable": True, "latency_ms": None, "status": "configured"}


def get_activity_overview() -> list[dict]:
    return audit_analytics.get_all_projects_overview()


def get_activity_project(repo_dir: str) -> dict[str, Any]:
    return {
        "summary": audit_analytics.get_project_summary(repo_dir),
        "timeline": audit_analytics.get_project_timeline(repo_dir, limit=30),
        "suggested_stage": audit_analytics.suggest_current_stage(repo_dir),
    }


def get_audit_entries(filter_text: str = "") -> list[dict]:
    entries = audit_logger.get_entries()
    if filter_text:
        ft = filter_text.lower()
        entries = [
            e
            for e in entries
            if ft in e.get("project", "").lower()
            or ft in e.get("stage", "").lower()
            or ft in e.get("status", "").lower()
        ]
    return entries


def get_settings(repo_dir: str) -> dict[str, Any]:
    deploy_cfg = load_deploy_config(repo_dir)
    deploy_path = os.path.join(repo_dir, ".shipmate", "deploy.yaml")
    vault = get_secrets_backend()
    required = get_required_secrets(repo_dir)
    ok, missing = vault.check_required(repo_dir, required)
    secret_status = {
        key: vault.get_secret("project", key, repo_dir) is not None for key in required
    }
    return {
        "deploy_path": deploy_path,
        "deploy_config": deploy_cfg,
        "validation_errors": validate_deploy_config(deploy_cfg) if deploy_cfg else [],
        "provider_name": get_provider_name(repo_dir),
        "provider_label": get_deploy_provider(repo_dir).label,
        "required_secrets": required,
        "secret_status": secret_status,
        "secrets_ok": ok,
        "missing_secrets": missing,
    }


def list_secrets(scope: str, repo_dir: str | None) -> dict[str, Any]:
    vault = get_secrets_backend()
    backend = get_secrets_config().get("backend", "local")
    secrets = vault.list_secrets(scope, repo_dir)
    return {"backend": backend, "scope": scope, "secrets": [{"name": k, "masked": v} for k, v in secrets.items()]}


def set_secret(scope: str, repo_dir: str | None, name: str, value: str) -> None:
    vault = get_secrets_backend()
    vault.set_secret(scope, name, value, repo_dir)
    audit_logger.log_action(
        project=repo_dir or "global",
        git_user="shipmate-ui",
        stage="secrets",
        branch="-",
        action=f"set_{name}",
        status="success",
        details=f"scope={scope}",
    )


def delete_secret(scope: str, repo_dir: str | None, name: str) -> None:
    get_secrets_backend().delete_secret(scope, name, repo_dir)


def import_secrets(scope: str, repo_dir: str | None, env_content: str) -> int:
    vault = get_secrets_backend()
    if isinstance(vault, LocalVaultBackend):
        return vault.import_env_file(scope, env_content, repo_dir)
    count = 0
    for line in env_content.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            vault.set_secret(scope, k.strip(), v.strip().strip('"'), repo_dir)
            count += 1
    return count


def validate_secrets(repo_dir: str) -> tuple[bool, list[str]]:
    required = get_required_secrets(repo_dir)
    return get_secrets_backend().check_required(repo_dir, required)


def run_dev_ship(
    session_id: str, repo_dir: str, commit_msg: str, host_override: bool
) -> Generator[dict[str, Any], None, None]:
    state = session_manager.get(session_id, repo_dir)
    git, runner, _, _, notifier = _services(repo_dir)
    identity = git.get_git_identity()

    state.stage_statuses["dev"] = "in_progress"
    yield _line("Running pre-flight checks...\n")

    clean, clean_msg = git.is_working_tree_clean()
    if not clean:
        _append_log(state, "dev", clean_msg + "\n")
        state.stage_statuses["dev"] = "failed"
        _log_audit(git, repo_dir, "dev", "pre_flight", "failure", host_override, clean_msg)
        yield _done(False, clean_msg)
        return

    if git.is_protected_branch():
        msg = "Cannot push directly to main/master."
        state.stage_statuses["dev"] = "failed"
        _log_audit(git, repo_dir, "dev", "pre_flight", "failure", host_override, msg)
        yield _done(False, msg)
        return

    state.checklist_builtin["dev_clean_tree"] = True
    state.checklist_builtin["dev_not_main"] = True

    yield _line("Scanning for secret leaks...\n")
    leaks = git.scan_for_secrets()
    if leaks:
        msg = f"Blocked: {', '.join(leaks)}"
        state.stage_statuses["dev"] = "failed"
        _log_audit(git, repo_dir, "dev", "secret_scan", "failure", host_override, msg)
        notifier.notify_failure("Dev", msg)
        yield _done(False, msg)
        return

    if not commit_msg:
        state.stage_statuses["dev"] = "failed"
        yield _done(False, "Commit message required")
        return

    try:
        yield _line("Running lint and tests...\n")
        for line in runner.run_preflight():
            yield _line(line + "\n")
            _append_log(state, "dev", line + "\n")
        state.checklist_builtin["dev_tests_passed"] = True
    except Exception as e:
        state.stage_statuses["dev"] = "failed"
        _log_audit(git, repo_dir, "dev", "pre_flight", "failure", host_override, str(e))
        yield _done(False, str(e))
        return

    branch = identity["branch"]
    cmd = f'git add -A && git commit -m "{commit_msg}" && git push origin {branch}'
    yield _line(f"$ {cmd}\n")
    try:
        for line in runner.run_stream(cmd):
            yield _line(line)
            _append_log(state, "dev", line)
    except Exception as e:
        state.stage_statuses["dev"] = "failed"
        _log_audit(git, repo_dir, "dev", "commit_push", "failure", host_override, str(e))
        yield _done(False, str(e))
        return

    yield _line("Creating pull request...\n")
    pr_ok, pr_msg = git.create_pull_request()
    _append_log(state, "dev", pr_msg + "\n")
    if pr_ok:
        state.stage_statuses["dev"] = "passed"
        _log_audit(git, repo_dir, "dev", "ship", "success", host_override, pr_msg)
        yield _done(True, f"Shipped! {pr_msg}")
    else:
        _log_audit(git, repo_dir, "dev", "pr_create", "failure", host_override, pr_msg)
        yield _done(False, pr_msg)


def run_qa_action(
    session_id: str, repo_dir: str, action: str, host_override: bool
) -> Generator[dict[str, Any], None, None]:
    state = session_manager.get(session_id, repo_dir)
    git, runner, _, checklist, _ = _services(repo_dir)
    identity = git.get_git_identity()
    branch = identity["branch"]

    if action == "pull_setup":
        state.stage_statuses["qa"] = "in_progress"
        cmd = (
            f"git fetch origin && git checkout {branch} && "
            f"git reset --hard origin/{branch} && {runner.get_install_command()}"
        )
        yield _line(f"$ {cmd}\n")
        try:
            for line in runner.run_stream(cmd):
                yield _line(line)
                _append_log(state, "qa", line)
            _log_audit(git, repo_dir, "qa", "pull_setup", "success", host_override)
            yield _done(True, "Dependencies synced")
        except Exception as e:
            state.stage_statuses["qa"] = "failed"
            _log_audit(git, repo_dir, "qa", "pull_setup", "failure", host_override, str(e))
            yield _done(False, str(e))

    elif action == "run_tests":
        state.stage_statuses["qa"] = "in_progress"
        cmd = runner.get_test_command()
        yield _line(f"$ {cmd}\n")
        try:
            for line in runner.run_stream(cmd):
                yield _line(line)
                _append_log(state, "qa", line)
            state.checklist_builtin["qa_tests_passed"] = True
            _log_audit(git, repo_dir, "qa", "run_tests", "success", host_override)
            yield _done(True, "Tests complete")
        except Exception as e:
            state.checklist_builtin["qa_tests_passed"] = False
            state.stage_statuses["qa"] = "failed"
            _log_audit(git, repo_dir, "qa", "run_tests", "failure", host_override, str(e))
            yield _done(False, str(e))

    elif action == "launch":
        ok, msg, _ = runner.launch_app()
        _append_log(state, "qa", msg + "\n")
        if ok:
            state.checklist_builtin["qa_app_health"] = True
            _log_audit(git, repo_dir, "qa", "launch_app", "success")
        yield _done(ok, msg)

    elif action == "stop":
        ok, msg = runner.stop_app()
        _append_log(state, "qa", msg + "\n")
        _log_audit(git, repo_dir, "qa", "stop_app", "success")
        yield _done(ok, msg)

    elif action == "auto_checks":
        results = checklist.run_automated_items("qa")
        state.checklist_automated.update(results)
        for item_id, passed in results.items():
            yield _line(f"{item_id}: {'PASS' if passed else 'FAIL'}\n")
        yield _done(True, "Automated checks complete")

    elif action == "merge":
        merge_ok, merge_msg = git.merge_pull_request()
        _append_log(state, "qa", merge_msg + "\n")
        if merge_ok:
            state.stage_statuses["qa"] = "passed"
            _log_audit(git, repo_dir, "qa", "approve_merge", "success", host_override, merge_msg)
            yield _done(True, merge_msg)
        else:
            _log_audit(git, repo_dir, "qa", "approve_merge", "failure", host_override, merge_msg)
            yield _done(False, merge_msg)

    else:
        yield _done(False, f"Unknown QA action: {action}")


def run_prod_action(
    session_id: str,
    repo_dir: str,
    action: str,
    host_override: bool,
    check_id: str | None = None,
) -> Generator[dict[str, Any], None, None]:
    state = session_manager.get(session_id, repo_dir)
    git, _, deploy_provider, checklist, notifier = _services(repo_dir)
    identity = git.get_git_identity()

    if action == "preflight" and check_id:
        ok, msg = deploy_provider.preflight_check(check_id)
        state.checklist_builtin[check_id] = ok
        _append_log(state, "prod", msg + "\n")
        yield _line(msg + "\n")
        yield _done(ok, msg)

    elif action == "auto_checks":
        results = checklist.run_automated_items("prod")
        state.checklist_automated.update(results)
        for item_id, passed in results.items():
            yield _line(f"{item_id}: {'PASS' if passed else 'FAIL'}\n")
        yield _done(True, "Automated prod checks complete")

    elif action == "deploy":
        state.stage_statuses["prod"] = "in_progress"
        yield _line("Running deploy pipeline...\n")
        ok, msg = deploy_provider.deploy()
        _append_log(state, "prod", msg + "\n")
        if ok:
            state.stage_statuses["prod"] = "passed"
            if "prod_backup" in [c["id"] for c in deploy_provider.get_builtin_checks()]:
                state.checklist_builtin["prod_backup"] = True
            live = getattr(deploy_provider, "health_url", "") or getattr(deploy_provider, "live_url", "")
            _log_audit(git, repo_dir, "prod", "deploy", "success", host_override, msg)
            notifier.notify_success(repo_dir, identity["name"], identity["branch"], "HEAD", live)
            yield _done(True, msg)
        else:
            state.stage_statuses["prod"] = "failed"
            _log_audit(git, repo_dir, "prod", "deploy", "failure", host_override, msg)
            notifier.notify_failure("Prod", msg)
            yield _done(False, msg)

    elif action == "rollback":
        ok, msg = deploy_provider.rollback()
        _append_log(state, "prod", msg + "\n")
        _log_audit(git, repo_dir, "prod", "rollback", "success" if ok else "failure", details=msg)
        yield _done(ok, msg)

    elif action == "health":
        ok, msg = deploy_provider.health_check()
        yield _done(ok, msg)

    elif action == "vm_monitor":
        if deploy_provider.name == "oracle_vm":
            import json

            data = deploy_provider.get_health_monitor()
            yield _line(json.dumps(data, indent=2) + "\n")
            yield _done(True, "Health monitor data retrieved")
        else:
            yield _done(False, "VM monitor only available for Oracle VM")

    else:
        yield _done(False, f"Unknown prod action: {action}")
