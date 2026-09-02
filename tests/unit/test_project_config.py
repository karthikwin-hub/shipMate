import project_config


def test_load_deploy_config_empty(tmp_git_repo):
    assert project_config.load_deploy_config(tmp_git_repo) == {}


def test_load_deploy_config_oracle(oracle_deploy_repo):
    cfg = project_config.load_deploy_config(oracle_deploy_repo)
    assert cfg["deploy"]["provider"] == "oracle_vm"
    assert cfg["deploy"]["oracle_vm"]["host"] == "10.0.0.1"


def test_get_provider_name_vercel(vercel_deploy_repo):
    assert project_config.get_provider_name(vercel_deploy_repo) == "vercel"


def test_get_required_secrets(vercel_deploy_repo):
    assert project_config.get_required_secrets(vercel_deploy_repo) == ["VERCEL_TOKEN"]


def test_validate_deploy_config_valid(oracle_deploy_repo):
    cfg = project_config.load_deploy_config(oracle_deploy_repo)
    assert project_config.validate_deploy_config(cfg) == []


def test_validate_deploy_config_missing_provider():
    errors = project_config.validate_deploy_config({})
    assert "Missing deploy.provider" in errors[0]


def test_validate_deploy_config_vercel_missing_project():
    errors = project_config.validate_deploy_config({"deploy": {"provider": "vercel"}})
    assert any("vercel.project" in e for e in errors)


def test_get_effective_oracle_config(oracle_deploy_repo):
    cfg = project_config.get_effective_oracle_config(oracle_deploy_repo)
    assert cfg["host"] == "10.0.0.1"
    assert cfg["remote_path"] == "/var/www/app"


def test_get_repo_id_stable(tmp_git_repo):
    id1 = project_config.get_repo_id(tmp_git_repo)
    id2 = project_config.get_repo_id(tmp_git_repo)
    assert id1 == id2
    assert len(id1) == 16
