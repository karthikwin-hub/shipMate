import os
import time

import paramiko
import requests

from config_loader import get_oracle_vm_config


class RemoteDeployer:
    def __init__(self, config: dict | None = None):
        cfg = config or get_oracle_vm_config()
        self.host = cfg.get("host", "")
        self.user = cfg.get("user", "ubuntu")
        self.key_path = os.path.expanduser(cfg.get("key_path", "~/.ssh/id_rsa"))
        self.remote_path = cfg.get("remote_path", "/var/www/myapp")
        self.health_url = cfg.get("health_url", "")
        self.backup_command = cfg.get(
            "backup_command",
            "git rev-parse HEAD > .last_stable_commit && cp -r data/ backup/ 2>/dev/null || true",
        )
        self.deploy_command = cfg.get("deploy_command", "git pull origin main")
        self.restart_command = cfg.get(
            "restart_command",
            "docker compose down && docker compose up -d --build || true",
        )

    def _get_ssh_client(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self.host,
            username=self.user,
            key_filename=self.key_path,
            timeout=10,
        )
        return client

    def execute_ssh_cmd(self, command: str) -> tuple[int, str]:
        if not self.host:
            return 1, "Oracle VM host not configured in shipmate_config.yaml"
        client = self._get_ssh_client()
        try:
            stdin, stdout, stderr = client.exec_command(f"cd {self.remote_path} && {command}")
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            return exit_code, out if exit_code == 0 else err
        finally:
            client.close()

    def check_ssh_connection(self) -> tuple[bool, str]:
        try:
            code, out = self.execute_ssh_cmd("echo connected")
            return code == 0, out or "SSH connection verified"
        except Exception as e:
            return False, str(e)

    def check_remote_env(self) -> tuple[bool, str]:
        code, out = self.execute_ssh_cmd("test -f .env && echo 'env present' || echo 'env missing'")
        return "env present" in out, out

    def deploy_with_auto_rollback(self) -> tuple[bool, str]:
        bk_code, bk_out = self.execute_ssh_cmd(self.backup_command)
        if bk_code != 0:
            return False, f"Backup failed: {bk_out}"

        deploy_cmd = f"{self.deploy_command} && {self.restart_command}"
        pull_code, pull_out = self.execute_ssh_cmd(deploy_cmd)
        if pull_code != 0:
            return False, f"Deploy failed during build: {pull_out}"

        if self.health_url:
            try:
                res = requests.get(self.health_url, timeout=15)
                if res.status_code == 200:
                    return True, "Deployment successful and Health Check 200 OK."
            except Exception:
                pass
            rollback_cmd = (
                "git checkout $(cat .last_stable_commit) && "
                f"{self.restart_command}"
            )
            self.execute_ssh_cmd(rollback_cmd)
            return False, "Health check failed! Automatic rollback executed to previous stable commit."

        return True, "Deployment completed (no health URL configured)."

    def manual_rollback(self) -> tuple[bool, str]:
        rollback_cmd = (
            "git checkout $(cat .last_stable_commit) && "
            f"{self.restart_command}"
        )
        code, out = self.execute_ssh_cmd(rollback_cmd)
        if code == 0:
            return True, "Rolled back Oracle VM to previous stable commit."
        return False, out

    def get_vm_health(self) -> dict:
        start = time.time()
        result = {"reachable": False, "latency_ms": None, "disk": "", "memory": ""}
        try:
            ok, _ = self.check_ssh_connection()
            result["reachable"] = ok
            result["latency_ms"] = round((time.time() - start) * 1000, 1)
            if ok:
                _, disk = self.execute_ssh_cmd("df -h / | tail -1")
                _, mem = self.execute_ssh_cmd("free -m | grep Mem")
                result["disk"] = disk
                result["memory"] = mem
        except Exception as e:
            result["error"] = str(e)
        if self.health_url:
            try:
                res = requests.get(self.health_url, timeout=10)
                result["health_status"] = res.status_code
            except Exception:
                result["health_status"] = "unreachable"
        return result
