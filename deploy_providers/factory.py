from deploy_providers.base import DeployProvider
from deploy_providers.firebase import FirebaseProvider
from deploy_providers.oracle_vm import OracleVMProvider
from deploy_providers.vercel import VercelProvider
from project_config import get_provider_name, get_required_secrets
from secrets_vault import get_secrets_backend

PROVIDERS = {
    "oracle_vm": OracleVMProvider,
    "vercel": VercelProvider,
    "firebase": FirebaseProvider,
}


def get_deploy_provider(repo_path: str) -> DeployProvider:
    name = get_provider_name(repo_path)
    cls = PROVIDERS.get(name, OracleVMProvider)
    vault = get_secrets_backend()
    secrets_env = {}
    for key in get_required_secrets(repo_path):
        val = vault.get_secret("project", key, repo_path)
        if val:
            secrets_env[key] = val
    return cls(repo_path, secrets_env)
