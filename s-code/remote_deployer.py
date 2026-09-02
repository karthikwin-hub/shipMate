import paramiko
import requests

class RemoteDeployer:
    def __init__(self, host: str, user: str, key_path: str, remote_path: str, health_url: str):
        self.host = host
        self.user = user
        self.key_path = key_path
        self.remote_path = remote_path
        self.health_url = health_url

    def _get_ssh_client(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=self.host, username=self.user, key_filename=self.key_path, timeout=10)
        return client

    def execute_ssh_cmd(self, command: str) -> tuple[int, str]:
        client = self._get_ssh_client()
        stdin, stdout, stderr = client.exec_command(f"cd {self.remote_path} && {command}")
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode().strip()
        err = stderr.read().decode().strip()
        client.close()
        return exit_code, out if exit_code == 0 else err

    def deploy_with_auto_rollback(self) -> tuple[bool, str]:
        # 1. Pre-deploy backup
        bk_code, _ = self.execute_ssh_cmd("git rev-parse HEAD > .last_stable_commit && cp -r data/ backup/ 2>/dev/null || true")
        
        # 2. Pull and restart
        pull_code, pull_out = self.execute_ssh_cmd("git pull origin main && (docker compose down && docker compose up -d --build || true)")
        if pull_code != 0:
            return False, f"Deploy failed during build: {pull_out}"

        # 3. Automated health check
        try:
            res = requests.get(self.health_url, timeout=15)
            if res.status_code == 200:
                return True, "Deployment successful and Health Check 200 OK."
        except Exception:
            pass

        # 4. Trigger Auto-Rollback if health check failed
        self.execute_ssh_cmd("git checkout $(cat .last_stable_commit) && (docker compose down && docker compose up -d || true)")
        return False, "Health check failed! Automatic rollback executed to previous stable commit."