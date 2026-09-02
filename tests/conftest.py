import os
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_git_repo(tmp_path):
    """Minimal git repo on a feature branch."""
    repo = tmp_path / "target-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "feature/test"], cwd=repo, check=True)
    return str(repo)


@pytest.fixture
def tmp_vault_dir(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    return str(vault)


@pytest.fixture
def tmp_audit_file(tmp_path, monkeypatch):
    audit_path = tmp_path / "workflow_audit.json"
    monkeypatch.setattr("audit_logger.get_audit_file", lambda: str(audit_path))
    monkeypatch.setattr("config_loader.get_audit_file", lambda: str(audit_path))
    return str(audit_path)


@pytest.fixture
def oracle_deploy_repo(tmp_git_repo):
    shipmate_dir = Path(tmp_git_repo) / ".shipmate"
    shipmate_dir.mkdir()
    config = {
        "deploy": {
            "provider": "oracle_vm",
            "health_url": "https://api.example.com/health",
            "oracle_vm": {
                "host": "10.0.0.1",
                "user": "ubuntu",
                "remote_path": "/var/www/app",
            },
        },
        "secrets": {"required": ["DEPLOY_TOKEN"]},
    }
    with open(shipmate_dir / "deploy.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return tmp_git_repo


@pytest.fixture
def vercel_deploy_repo(tmp_git_repo):
    shipmate_dir = Path(tmp_git_repo) / ".shipmate"
    shipmate_dir.mkdir()
    config = {
        "deploy": {
            "provider": "vercel",
            "health_url": "https://app.vercel.app/health",
            "vercel": {"project": "my-app", "org": "team"},
        },
        "secrets": {"required": ["VERCEL_TOKEN"]},
    }
    with open(shipmate_dir / "deploy.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return tmp_git_repo


@pytest.fixture
def checklist_repo(tmp_git_repo):
    checklist = {
        "qa_manual_checklist": [
            {"id": "smoke", "label": "Smoke test", "type": "manual"},
            {"id": "auto_ok", "label": "Auto ok", "type": "automated_command", "command": "echo ok"},
        ],
        "prod_pre_deploy_checklist": [
            {"id": "manual_prod", "label": "Manual prod check", "type": "manual"},
        ],
    }
    with open(Path(tmp_git_repo) / ".workflow-checklist.yaml", "w", encoding="utf-8") as f:
        yaml.dump(checklist, f)
    return tmp_git_repo
