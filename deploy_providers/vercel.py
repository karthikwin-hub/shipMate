import os
import subprocess

import requests

from deploy_providers.base import DeployProvider
from project_config import get_deploy_section


class VercelProvider(DeployProvider):
    name = "vercel"
    label = "Vercel"

    def __init__(self, repo_path: str, secrets_env: dict | None = None):
        self.repo_path = repo_path
        self.secrets_env = secrets_env or {}
        deploy = get_deploy_section(repo_path)
        self.vercel_cfg = deploy.get("vercel") or {}
        self.health_url = deploy.get("health_url", "")
        self.live_url = deploy.get("live_url", "")

    def _run(self, cmd: str) -> tuple[int, str]:
        env = {**os.environ, **self.secrets_env}
        res = subprocess.run(
            cmd, cwd=self.repo_path, shell=True, capture_output=True, text=True, env=env
        )
        out = res.stdout.strip() if res.returncode == 0 else res.stderr.strip()
        return res.returncode, out

    def get_builtin_checks(self) -> list[dict]:
        return [
            {"id": "prod_vercel_auth", "label": "Vercel CLI authenticated", "type": "builtin"},
            {"id": "prod_vercel_linked", "label": "Vercel project linked", "type": "builtin"},
        ]

    def preflight_check(self, check_id: str) -> tuple[bool, str]:
        if check_id == "prod_vercel_auth":
            code, out = self._run("vercel whoami")
            return code == 0, out or "Not authenticated"
        if check_id == "prod_vercel_linked":
            if self.vercel_cfg.get("project"):
                return True, f"Project configured: {self.vercel_cfg['project']}"
            code, out = self._run("vercel project ls")
            return code == 0, out
        return False, f"Unknown check: {check_id}"

    def deploy(self) -> tuple[bool, str]:
        project = self.vercel_cfg.get("project", "")
        org = self.vercel_cfg.get("org", "")
        flags = "--prod --yes"
        if project:
            flags += f" --project {project}"
        if org:
            flags += f" --scope {org}"
        code, out = self._run(f"vercel deploy {flags}")
        if code != 0:
            return False, out
        if self.health_url:
            ok, msg = self.health_check()
            if not ok:
                return False, f"Deploy succeeded but health check failed: {msg}"
        return True, out or "Deployed to Vercel production"

    def rollback(self) -> tuple[bool, str]:
        code, out = self._run("vercel rollback --yes")
        return code == 0, out or "Rollback initiated"

    def health_check(self) -> tuple[bool, str]:
        if not self.health_url:
            return True, "No health URL configured"
        try:
            res = requests.get(self.health_url, timeout=15)
            if res.status_code == 200:
                return True, "Health check 200 OK"
            return False, f"HTTP {res.status_code}"
        except Exception as e:
            return False, str(e)
