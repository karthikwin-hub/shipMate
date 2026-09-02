from unittest.mock import MagicMock, patch

import pytest

from deploy_providers.factory import get_deploy_provider
from deploy_providers.oracle_vm import OracleVMProvider
from deploy_providers.vercel import VercelProvider
from deploy_providers.firebase import FirebaseProvider


def test_factory_oracle(oracle_deploy_repo):
    provider = get_deploy_provider(oracle_deploy_repo)
    assert isinstance(provider, OracleVMProvider)
    assert provider.name == "oracle_vm"


def test_factory_vercel(vercel_deploy_repo):
    provider = get_deploy_provider(vercel_deploy_repo)
    assert isinstance(provider, VercelProvider)
    assert provider.name == "vercel"


def test_factory_firebase(tmp_git_repo):
    from pathlib import Path
    import yaml

    d = Path(tmp_git_repo) / ".shipmate"
    d.mkdir()
    yaml.dump(
        {
            "deploy": {
                "provider": "firebase",
                "health_url": "https://app.web.app",
                "firebase": {"project_id": "my-proj", "targets": ["hosting"]},
            }
        },
        open(d / "deploy.yaml", "w"),
    )
    provider = get_deploy_provider(tmp_git_repo)
    assert isinstance(provider, FirebaseProvider)


def test_vercel_health_check_success(vercel_deploy_repo):
    provider = VercelProvider(vercel_deploy_repo)
    with patch("deploy_providers.vercel.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        ok, msg = provider.health_check()
    assert ok
    assert "200" in msg


def test_vercel_preflight_auth(vercel_deploy_repo):
    provider = VercelProvider(vercel_deploy_repo)
    with patch.object(provider, "_run", return_value=(0, "user@example.com")):
        ok, msg = provider.preflight_check("prod_vercel_auth")
    assert ok


def test_oracle_builtin_checks(oracle_deploy_repo):
    provider = OracleVMProvider(oracle_deploy_repo)
    checks = provider.get_builtin_checks()
    assert len(checks) == 3
    assert checks[0]["id"] == "prod_ssh"
