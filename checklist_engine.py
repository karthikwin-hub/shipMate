import json
import os
import subprocess

import yaml

BUILTIN_DEV = [
    {"id": "dev_clean_tree", "label": "Working tree clean (no untracked/uncommitted files)", "type": "builtin"},
    {"id": "dev_not_main", "label": "Active branch is not main/master", "type": "builtin"},
    {"id": "dev_tests_passed", "label": "Local unit tests and linter passed", "type": "builtin"},
]

BUILTIN_QA = [
    {"id": "qa_tests_passed", "label": "Automated test suite execution passed (0 failures)", "type": "builtin"},
    {"id": "qa_app_health", "label": "Local app launched and responded with HTTP 200 OK", "type": "builtin"},
    {"id": "qa_up_to_date", "label": "Branch is rebased/up-to-date with remote main", "type": "builtin"},
]

BUILTIN_PROD = [
    {"id": "prod_ssh", "label": "Oracle VM SSH connection verified", "type": "builtin"},
    {"id": "prod_env", "label": "Target environment variables / .env present on remote", "type": "builtin"},
    {"id": "prod_backup", "label": "Pre-deployment database backup completed", "type": "builtin"},
]

QA_KEYS = ("qa_checklist", "qa_manual_checklist")
PROD_KEYS = ("prod_checklist", "prod_pre_deploy_checklist")


class ChecklistEngine:
    def __init__(self, repo_path: str, prod_builtin: list | None = None):
        self.repo_path = repo_path
        self.prod_builtin = prod_builtin or BUILTIN_PROD

    def _find_checklist_file(self) -> str | None:
        for name in (".workflow-checklist.yaml", ".workflow-checklist.yml", ".checklist.json"):
            path = os.path.join(self.repo_path, name)
            if os.path.exists(path):
                return path
        return None

    def load_checklist(self) -> dict:
        path = self._find_checklist_file()
        if not path:
            return {
                "qa_checklist": [
                    {"id": "qa_smoke", "label": "Perform manual UI smoke test", "type": "manual"},
                ],
                "prod_checklist": [
                    {"id": "prod_backup_manual", "label": "Verify pre-deploy backup", "type": "manual"},
                ],
            }
        try:
            with open(path, "r", encoding="utf-8") as f:
                if path.endswith(".json"):
                    return json.load(f) or {}
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _get_dynamic_items(self, stage: str) -> list:
        data = self.load_checklist()
        if stage == "qa":
            for key in QA_KEYS:
                if key in data:
                    return data[key] or []
        if stage == "prod":
            for key in PROD_KEYS:
                if key in data:
                    return data[key] or []
        return []

    def get_stage_items(self, stage: str) -> list:
        if stage == "dev":
            return list(BUILTIN_DEV) + self._get_dynamic_items("dev")
        if stage == "qa":
            return list(BUILTIN_QA) + self._get_dynamic_items("qa")
        if stage == "prod":
            return list(self.prod_builtin) + self._get_dynamic_items("prod")
        return []

    def run_automated_check(self, command: str) -> tuple[bool, str]:
        try:
            res = subprocess.run(
                command,
                cwd=self.repo_path,
                shell=True,
                capture_output=True,
                text=True,
            )
            return res.returncode == 0, res.stdout if res.returncode == 0 else res.stderr
        except Exception as e:
            return False, str(e)

    def run_automated_items(self, stage: str) -> dict[str, bool]:
        results = {}
        for item in self.get_stage_items(stage):
            if item.get("type") == "automated_command" and item.get("command"):
                ok, _ = self.run_automated_check(item["command"])
                results[item["id"]] = ok
        return results

    def all_passed(
        self,
        stage: str,
        manual_state: dict[str, bool],
        builtin_state: dict[str, bool] | None = None,
        automated_state: dict[str, bool] | None = None,
    ) -> bool:
        builtin_state = builtin_state or {}
        automated_state = automated_state or {}
        for item in self.get_stage_items(stage):
            item_id = item["id"]
            item_type = item.get("type", "manual")
            if item_type == "builtin":
                if not builtin_state.get(item_id, False):
                    return False
            elif item_type == "automated_command":
                if not automated_state.get(item_id, False):
                    return False
            elif item_type == "manual":
                if not manual_state.get(item_id, False):
                    return False
        return True
