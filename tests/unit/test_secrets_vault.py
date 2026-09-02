from secrets_vault import LocalVaultBackend, mask_value


def test_mask_value():
    assert mask_value("secret1234") == "••••••1234"
    assert mask_value("") == "(empty)"
    assert mask_value("abc") == "••••"


def test_local_vault_crud(tmp_vault_dir, tmp_git_repo):
    vault = LocalVaultBackend(tmp_vault_dir)
    vault.set_secret("project", "API_KEY", "my-secret-value", tmp_git_repo)
    assert vault.get_secret("project", "API_KEY", tmp_git_repo) == "my-secret-value"
    listed = vault.list_secrets("project", tmp_git_repo)
    assert "API_KEY" in listed
    assert listed["API_KEY"] == "••••••alue"
    vault.delete_secret("project", "API_KEY", tmp_git_repo)
    assert vault.get_secret("project", "API_KEY", tmp_git_repo) is None


def test_local_vault_global_scope(tmp_vault_dir):
    vault = LocalVaultBackend(tmp_vault_dir)
    vault.set_secret("global", "SMTP_PASSWORD", "email-pass")
    assert vault.get_secret("global", "SMTP_PASSWORD") == "email-pass"


def test_check_required(tmp_vault_dir, tmp_git_repo):
    vault = LocalVaultBackend(tmp_vault_dir)
    ok, missing = vault.check_required(tmp_git_repo, ["A", "B"])
    assert not ok
    assert set(missing) == {"A", "B"}
    vault.set_secret("project", "A", "val", tmp_git_repo)
    ok, missing = vault.check_required(tmp_git_repo, ["A", "B"])
    assert not ok
    assert missing == ["B"]


def test_import_env_file(tmp_vault_dir, tmp_git_repo):
    vault = LocalVaultBackend(tmp_vault_dir)
    content = "# comment\nFOO=bar\nBAZ=\"qux\"\n"
    count = vault.import_env_file("project", content, tmp_git_repo)
    assert count == 2
    assert vault.get_secret("project", "FOO", tmp_git_repo) == "bar"
    assert vault.get_secret("project", "BAZ", tmp_git_repo) == "qux"
