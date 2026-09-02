import os
import yaml
import subprocess

class ChecklistEngine:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.checklist_file = os.path.join(repo_path, ".workflow-checklist.yaml")

    def load_checklist(self) -> dict:
        if not os.path.exists(self.checklist_file):
            return {
                "qa_checklist": [
                    {"id": "qa_smoke", "label": "Perform manual UI smoke test", "type": "manual"}
                ],
                "prod_checklist": [
                    {"id": "prod_backup", "label": "Verify pre-deploy backup", "type": "manual"}
                ]
            }
        try:
            with open(self.checklist_file, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def run_automated_check(self, command: str) -> tuple[bool, str]:
        try:
            res = subprocess.run(command, cwd=self.repo_path, shell=True, capture_output=True, text=True)
            return res.returncode == 0, res.stdout if res.returncode == 0 else res.stderr
        except Exception as e:
            return False, str(e)