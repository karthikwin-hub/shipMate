"""End-to-end integration tests across ShipMate modules."""

from unittest.mock import patch

import project_config
from checklist_engine import BUILTIN_QA, ChecklistEngine
from deploy_providers.factory import get_deploy_provider
from git_manager import GitManager
import audit_analytics
import audit_logger
from secrets_vault import LocalVaultBackend


def test_e2e_dev_preflight_blocks_protected_branch(tmp_git_repo, tmp_audit_file):
    """Requirements §5 Stage 1: branch protection guard."""
    import subprocess
    subprocess.run(["git", "checkout", "main"], cwd=tmp_git_repo, check=True)
    git = GitManager(tmp_git_repo)
    assert git.is_protected_branch()
    audit_logger.log_action(
        tmp_git_repo, "test@example.com", "dev", "main", "pre_flight", "failure",
        details="protected branch",
    )
    summary = audit_analytics.get_project_summary(tmp_git_repo)
    assert summary["failures"] == 1


def test_e2e_dev_preflight_clean_tree_and_secret_scan(tmp_git_repo, tmp_audit_file):
    """Requirements §5 Stage 1: clean tree + secret scan."""
    git = GitManager(tmp_git_repo)
    clean, _ = git.is_working_tree_clean()
    assert clean
    assert git.scan_for_secrets() == []
    assert not git.is_protected_branch()


def test_e2e_qa_gatekeeper_blocks_until_complete(checklist_repo):
    """Requirements §4: gatekeeper until all checklist items pass."""
    engine = ChecklistEngine(checklist_repo)
    builtin = {i["id"]: True for i in BUILTIN_QA}
    assert not engine.all_passed("qa", {}, builtin, {})
    manual = {"smoke": True}
    automated = engine.run_automated_items("qa")
    assert engine.all_passed("qa", manual, builtin, automated)


def test_e2e_secrets_required_for_deploy(vercel_deploy_repo, tmp_vault_dir):
    """Project-aware deploy: secrets gate before Stage 3."""
    vault = LocalVaultBackend(tmp_vault_dir)
    ok, missing = vault.check_required(vercel_deploy_repo, project_config.get_required_secrets(vercel_deploy_repo))
    assert not ok
    assert "VERCEL_TOKEN" in missing
    vault.set_secret("project", "VERCEL_TOKEN", "tok", vercel_deploy_repo)
    ok, missing = vault.check_required(vercel_deploy_repo, ["VERCEL_TOKEN"])
    assert ok


def test_e2e_deploy_provider_loads_secrets_into_env(vercel_deploy_repo, tmp_vault_dir):
    vault = LocalVaultBackend(tmp_vault_dir)
    vault.set_secret("project", "VERCEL_TOKEN", "my-vercel-token", vercel_deploy_repo)
    with patch("deploy_providers.factory.get_secrets_backend", return_value=vault):
        provider = get_deploy_provider(vercel_deploy_repo)
    assert provider.secrets_env.get("VERCEL_TOKEN") == "my-vercel-token"


def test_e2e_vercel_deploy_with_health_check(vercel_deploy_repo, tmp_audit_file):
    provider = get_deploy_provider(vercel_deploy_repo)
    with patch.object(provider, "_run", return_value=(0, "Deployed")):
        with patch.object(provider, "health_check", return_value=(True, "OK")):
            ok, msg = provider.deploy()
    assert ok
    audit_logger.log_action(
        vercel_deploy_repo, "test@example.com", "prod", "feature/test", "deploy", "success", details=msg
    )
    timeline = audit_analytics.get_project_timeline(vercel_deploy_repo)
    assert timeline[0]["action"] == "deploy"
    assert audit_analytics.suggest_current_stage(vercel_deploy_repo) == "prod"


def test_e2e_oracle_deploy_config_validation(oracle_deploy_repo):
    cfg = project_config.load_deploy_config(oracle_deploy_repo)
    assert project_config.validate_deploy_config(cfg) == []
    provider = get_deploy_provider(oracle_deploy_repo)
    assert provider.name == "oracle_vm"
    with patch.object(provider._deployer, "deploy_with_auto_rollback", return_value=(True, "OK")):
        ok, msg = provider.deploy()
    assert ok


def test_e2e_activity_dashboard_multi_project(tmp_audit_file, tmp_git_repo, vercel_deploy_repo):
    """Activity dashboard: cross-project overview."""
    audit_logger.log_action(tmp_git_repo, "u", "dev", "b", "ship", "success")
    audit_logger.log_action(vercel_deploy_repo, "u", "prod", "b", "deploy", "failure")
    overview = audit_analytics.get_all_projects_overview()
    projects = {o["project"] for o in overview}
    assert tmp_git_repo in projects
    assert vercel_deploy_repo in projects
    assert any(o["failures"] >= 1 for o in overview)


def test_e2e_global_secrets_for_notifications(tmp_vault_dir):
    """Team/global secrets usable outside deploy pipeline."""
    vault = LocalVaultBackend(tmp_vault_dir)
    vault.set_secret("global", "SMTP_USER", "mailer@example.com")
    vault.set_secret("global", "SMTP_PASSWORD", "pass")
    from notifications import NotificationManager
    with patch("notifications.get_global_secret", side_effect=lambda k: vault.get_secret("global", k)):
        nm = NotificationManager({"smtp": {"user_secret": "SMTP_USER", "password_secret": "SMTP_PASSWORD"}})
        assert nm._resolve_smtp_credential("user", "SMTP_USER") == "mailer@example.com"
        assert nm._resolve_smtp_credential("password", "SMTP_PASSWORD") == "pass"
