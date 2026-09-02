import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = Path(__file__).parent / "shipmate_config.yaml"
EXAMPLE_PATH = Path(__file__).parent / "shipmate_config.example.yaml"


def _expand_env(value):
    if not isinstance(value, str):
        return value
    pattern = re.compile(r"\$\{([^}]+)\}")

    def replacer(match):
        return os.environ.get(match.group(1), "")

    return pattern.sub(replacer, value)


def _expand_dict(obj):
    if isinstance(obj, dict):
        return {k: _expand_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_dict(v) for v in obj]
    return _expand_env(obj)


def load_config() -> dict:
    path = CONFIG_PATH if CONFIG_PATH.exists() else EXAMPLE_PATH
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _expand_dict(data)


def get_oracle_vm_config() -> dict:
    return load_config().get("oracle_vm", {})


def get_notifications_config() -> dict:
    return load_config().get("notifications", {})


def get_audit_file() -> str:
    return load_config().get("audit", {}).get("file", "workflow_audit.json")


def get_secrets_config() -> dict:
    return load_config().get("secrets", {})


def get_oracle_vm_config() -> dict:
    """Legacy global oracle config — prefer per-project .shipmate/deploy.yaml."""
    return load_config().get("oracle_vm", {})
