import os
import re
from abc import ABC, abstractmethod
from pathlib import Path

from config_loader import get_secrets_config
from project_config import get_repo_id, get_secrets_section


def mask_value(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 4:
        return "••••"
    return "••••••" + value[-4:]


class SecretsBackend(ABC):
    @abstractmethod
    def list_secrets(self, scope: str, project_ref: str | None = None) -> dict[str, str]:
        """Returns masked values."""

    @abstractmethod
    def get_secret(self, scope: str, key: str, project_ref: str | None = None) -> str | None:
        pass

    @abstractmethod
    def set_secret(self, scope: str, key: str, value: str, project_ref: str | None = None) -> None:
        pass

    @abstractmethod
    def delete_secret(self, scope: str, key: str, project_ref: str | None = None) -> None:
        pass

    def check_required(self, project_ref: str, required_keys: list[str]) -> tuple[bool, list[str]]:
        missing = []
        for key in required_keys:
            if not self.get_secret("project", key, project_ref):
                missing.append(key)
        return len(missing) == 0, missing

    def list_all_secrets(self, scope: str, project_ref: str | None = None) -> list[dict]:
        masked = self.list_secrets(scope, project_ref)
        return [{"key": k, "masked": v, "set": True} for k, v in masked.items()]


class LocalVaultBackend(SecretsBackend):
    def __init__(self, vault_dir: str | None = None):
        cfg = get_secrets_config()
        default = Path.home() / ".shipmate" / "vault"
        self.vault_dir = Path(vault_dir or cfg.get("local", {}).get("vault_dir", str(default)))
        self.vault_dir.mkdir(parents=True, exist_ok=True)

    def _file_for(self, scope: str, project_ref: str | None) -> Path:
        if scope == "global":
            return self.vault_dir / "global.secrets.env"
        repo_id = get_repo_id(project_ref) if project_ref else "unknown"
        return self.vault_dir / f"{repo_id}.secrets.env"

    def _read_env_file(self, path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        data = {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                data[k.strip()] = v.strip().strip('"').strip("'")
        return data

    def _write_env_file(self, path: Path, data: dict[str, str]) -> None:
        lines = [f'{k}="{v}"' for k, v in sorted(data.items())]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def list_secrets(self, scope: str, project_ref: str | None = None) -> dict[str, str]:
        raw = self._read_env_file(self._file_for(scope, project_ref))
        return {k: mask_value(v) for k, v in raw.items()}

    def get_secret(self, scope: str, key: str, project_ref: str | None = None) -> str | None:
        return self._read_env_file(self._file_for(scope, project_ref)).get(key)

    def set_secret(self, scope: str, key: str, value: str, project_ref: str | None = None) -> None:
        path = self._file_for(scope, project_ref)
        data = self._read_env_file(path)
        data[key] = value
        self._write_env_file(path, data)

    def delete_secret(self, scope: str, key: str, project_ref: str | None = None) -> None:
        path = self._file_for(scope, project_ref)
        data = self._read_env_file(path)
        data.pop(key, None)
        self._write_env_file(path, data)

    def import_env_file(self, scope: str, content: str, project_ref: str | None = None) -> int:
        count = 0
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            self.set_secret(scope, k.strip(), v.strip().strip('"').strip("'"), project_ref)
            count += 1
        return count


class InfisicalBackend(SecretsBackend):
    """Infisical REST API backend. Requires INFISICAL_TOKEN or machine identity env vars."""

    def __init__(self):
        cfg = get_secrets_config().get("infisical", {})
        self.site_url = (cfg.get("site_url") or "https://app.infisical.com").rstrip("/")
        self.token = os.environ.get("INFISICAL_TOKEN", "")
        self._client = None

    def _available(self) -> bool:
        return bool(self.token or (
            os.environ.get("INFISICAL_CLIENT_ID") and os.environ.get("INFISICAL_CLIENT_SECRET")
        ))

    def _resolve_project_env(self, scope: str, project_ref: str | None) -> tuple[str, str]:
        if scope == "global":
            gp = get_secrets_config().get("global_project") or {}
            return gp.get("project_slug", "shipmate-team"), gp.get("environment", "shared")
        if project_ref:
            sec = get_secrets_section(project_ref)
            inf = sec.get("infisical") or {}
            slug = inf.get("project_slug") or Path(project_ref).name
            env = inf.get("environment", "prod")
            return slug, env
        return "default", "prod"

    def list_secrets(self, scope: str, project_ref: str | None = None) -> dict[str, str]:
        if not self._available():
            return {}
        try:
            import requests
            slug, env = self._resolve_project_env(scope, project_ref)
            # Simplified: list via universal auth API v3
            headers = {"Authorization": f"Bearer {self.token}"}
            url = f"{self.site_url}/api/v3/secrets/raw"
            params = {"workspaceId": slug, "environment": env, "secretPath": "/"}
            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code != 200:
                return {}
            secrets = res.json().get("secrets") or []
            return {s.get("secretKey", ""): mask_value("***") for s in secrets if s.get("secretKey")}
        except Exception:
            return {}

    def get_secret(self, scope: str, key: str, project_ref: str | None = None) -> str | None:
        if not self._available():
            return None
        try:
            import requests
            slug, env = self._resolve_project_env(scope, project_ref)
            headers = {"Authorization": f"Bearer {self.token}"}
            url = f"{self.site_url}/api/v3/secrets/raw/{key}"
            params = {"workspaceId": slug, "environment": env, "secretPath": "/"}
            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code == 200:
                return res.json().get("secret", {}).get("secretValue")
        except Exception:
            pass
        return None

    def set_secret(self, scope: str, key: str, value: str, project_ref: str | None = None) -> None:
        if not self._available():
            raise RuntimeError("Infisical not configured. Set INFISICAL_TOKEN or use local backend.")
        import requests
        slug, env = self._resolve_project_env(scope, project_ref)
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        url = f"{self.site_url}/api/v3/secrets/raw/{key}"
        payload = {"workspaceId": slug, "environment": env, "secretPath": "/", "secretValue": value}
        requests.post(url, headers=headers, json=payload, timeout=10)

    def delete_secret(self, scope: str, key: str, project_ref: str | None = None) -> None:
        if not self._available():
            return
        import requests
        slug, env = self._resolve_project_env(scope, project_ref)
        headers = {"Authorization": f"Bearer {self.token}"}
        url = f"{self.site_url}/api/v3/secrets/raw/{key}"
        params = {"workspaceId": slug, "environment": env, "secretPath": "/"}
        requests.delete(url, headers=headers, params=params, timeout=10)


def get_secrets_backend() -> SecretsBackend:
    cfg = get_secrets_config()
    backend = (cfg.get("backend") or "local").lower()
    if backend == "infisical":
        ib = InfisicalBackend()
        if ib._available():
            return ib
    return LocalVaultBackend()


def get_global_secret(key: str) -> str | None:
    return get_secrets_backend().get_secret("global", key)
