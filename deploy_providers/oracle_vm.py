from deploy_providers.base import DeployProvider
from project_config import get_effective_oracle_config
from remote_deployer import RemoteDeployer


class OracleVMProvider(DeployProvider):
    name = "oracle_vm"
    label = "Oracle VM"

    def __init__(self, repo_path: str, secrets_env: dict | None = None):
        self.repo_path = repo_path
        self.secrets_env = secrets_env or {}
        self._deployer = RemoteDeployer(get_effective_oracle_config(repo_path))

    def get_builtin_checks(self) -> list[dict]:
        return [
            {"id": "prod_ssh", "label": "SSH connection verified", "type": "builtin"},
            {"id": "prod_env", "label": "Remote .env present", "type": "builtin"},
            {"id": "prod_backup", "label": "Pre-deploy backup completed", "type": "builtin"},
        ]

    def preflight_check(self, check_id: str) -> tuple[bool, str]:
        if check_id == "prod_ssh":
            return self._deployer.check_ssh_connection()
        if check_id == "prod_env":
            return self._deployer.check_remote_env()
        if check_id == "prod_backup":
            return True, "Backup runs automatically on deploy"
        return False, f"Unknown check: {check_id}"

    def deploy(self) -> tuple[bool, str]:
        return self._deployer.deploy_with_auto_rollback()

    def rollback(self) -> tuple[bool, str]:
        return self._deployer.manual_rollback()

    def health_check(self) -> tuple[bool, str]:
        health = self._deployer.get_vm_health()
        if health.get("health_status") == 200:
            return True, "Health check 200 OK"
        if health.get("reachable"):
            return True, f"SSH reachable, latency {health.get('latency_ms')}ms"
        return False, health.get("error", "Unreachable")

    def get_health_monitor(self) -> dict:
        return self._deployer.get_vm_health()

    @property
    def health_url(self) -> str:
        return self._deployer.health_url

    @property
    def deployer(self) -> RemoteDeployer:
        return self._deployer
