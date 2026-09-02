import os
import subprocess

import requests

from deploy_providers.base import DeployProvider
from project_config import get_deploy_section


class FirebaseProvider(DeployProvider):
    name = "firebase"
    label = "Firebase"

    def __init__(self, repo_path: str, secrets_env: dict | None = None):
        self.repo_path = repo_path
        self.secrets_env = secrets_env or {}
        deploy = get_deploy_section(repo_path)
        self.fb_cfg = deploy.get("firebase") or {}
        self.health_url = deploy.get("health_url", deploy.get("live_url", ""))

    def _run(self, cmd: str) -> tuple[int, str]:
        env = {**os.environ, **self.secrets_env}
        res = subprocess.run(
            cmd, cwd=self.repo_path, shell=True, capture_output=True, text=True, env=env
        )
        out = res.stdout.strip() if res.returncode == 0 else res.stderr.strip()
        return res.returncode, out

    def get_builtin_checks(self) -> list[dict]:
        return [
            {"id": "prod_firebase_auth", "label": "Firebase CLI authenticated", "type": "builtin"},
            {"id": "prod_firebase_project", "label": "Firebase project selected", "type": "builtin"},
        ]

    def preflight_check(self, check_id: str) -> tuple[bool, str]:
        if check_id == "prod_firebase_auth":
            code, out = self._run("firebase login:list")
            return code == 0, out or "Not logged in"
        if check_id == "prod_firebase_project":
            pid = self.fb_cfg.get("project_id", "")
            if pid:
                return True, f"Project: {pid}"
            code, out = self._run("firebase projects:list")
            return code == 0, out
        return False, f"Unknown check: {check_id}"

    def deploy(self) -> tuple[bool, str]:
        targets = self.fb_cfg.get("targets") or ["hosting"]
        only = ",".join(targets)
        project = self.fb_cfg.get("project_id", "")
        proj_flag = f" --project {project}" if project else ""
        code, out = self._run(f"firebase deploy --only {only}{proj_flag}")
        if code != 0:
            return False, out
        if self.health_url:
            ok, msg = self.health_check()
            if not ok:
                return False, f"Deploy succeeded but health check failed: {msg}"
        return True, out or "Firebase deploy complete"

    def rollback(self) -> tuple[bool, str]:
        return False, "Firebase rollback: use Firebase Console hosting release history"

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
