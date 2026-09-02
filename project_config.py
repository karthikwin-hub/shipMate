import hashlib
import os
import subprocess

import yaml

DEPLOY_PATHS = (
    os.path.join(".shipmate", "deploy.yaml"),
    os.path.join(".shipmate", "deploy.yml"),
    ".shipmate.yaml",
)


def get_repo_id(repo_path: str) -> str:
    try:
        res = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if res.returncode == 0 and res.stdout.strip():
            return hashlib.sha256(res.stdout.strip().encode()).hexdigest()[:16]
    except Exception:
        pass
    normalized = os.path.normpath(os.path.abspath(repo_path)).lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _find_deploy_file(repo_path: str) -> str | None:
    for rel in DEPLOY_PATHS:
        path = os.path.join(repo_path, rel)
        if os.path.exists(path):
            return path
    return None


def load_deploy_config(repo_path: str) -> dict:
    path = _find_deploy_file(repo_path)
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def get_provider_name(repo_path: str) -> str:
    cfg = load_deploy_config(repo_path)
    provider = (cfg.get("deploy") or {}).get("provider")
    if provider:
        return provider
    legacy = _legacy_oracle_from_global()
    if legacy.get("host"):
        return "oracle_vm"
    return "oracle_vm"


def get_required_secrets(repo_path: str) -> list[str]:
    cfg = load_deploy_config(repo_path)
    return list((cfg.get("secrets") or {}).get("required") or [])


def get_deploy_section(repo_path: str) -> dict:
    return load_deploy_config(repo_path).get("deploy") or {}


def get_secrets_section(repo_path: str) -> dict:
    return load_deploy_config(repo_path).get("secrets") or {}


def validate_deploy_config(config: dict) -> list[str]:
    errors = []
    deploy = config.get("deploy") or {}
    provider = deploy.get("provider")
    if not provider:
        return ["Missing deploy.provider in .shipmate/deploy.yaml"]
    if provider not in ("oracle_vm", "vercel", "firebase"):
        errors.append(f"Unknown provider: {provider}")
    if provider == "oracle_vm" and not (deploy.get("oracle_vm") or {}).get("host"):
        errors.append("oracle_vm.host is required")
    if provider == "vercel" and not (deploy.get("vercel") or {}).get("project"):
        errors.append("vercel.project is required")
    if provider == "firebase" and not (deploy.get("firebase") or {}).get("project_id"):
        errors.append("firebase.project_id is required")
    return errors


def _legacy_oracle_from_global() -> dict:
    try:
        from config_loader import get_oracle_vm_config
        return get_oracle_vm_config()
    except Exception:
        return {}


def get_effective_oracle_config(repo_path: str) -> dict:
    deploy = get_deploy_section(repo_path)
    oracle = deploy.get("oracle_vm") or {}
    if oracle.get("host"):
        return {
            "host": oracle.get("host", ""),
            "user": oracle.get("user", "ubuntu"),
            "key_path": oracle.get("key_path", "~/.ssh/id_rsa"),
            "remote_path": oracle.get("remote_path", "/var/www/myapp"),
            "health_url": deploy.get("health_url", ""),
            "backup_command": oracle.get(
                "backup_command",
                "git rev-parse HEAD > .last_stable_commit && cp -r data/ backup/ 2>/dev/null || true",
            ),
            "deploy_command": oracle.get("deploy_command", "git pull origin main"),
            "restart_command": oracle.get(
                "restart_command",
                "docker compose down && docker compose up -d --build || true",
            ),
        }
    return _legacy_oracle_from_global()
