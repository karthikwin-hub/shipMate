import pipeline_service as ps
from session_manager import session_manager


def test_validate_repo(tmp_git_repo):
    ok, msg = ps.validate_repo(tmp_git_repo)
    assert ok
    assert msg == "OK"


def test_validate_repo_invalid():
    ok, msg = ps.validate_repo("/nonexistent/path/xyz")
    assert not ok


def test_get_context(tmp_git_repo):
    ctx = ps.get_context("test-session", tmp_git_repo)
    assert ctx["valid"]
    assert ctx["identity"]["branch"] == "feature/test"
    assert "stack" in ctx
    assert ctx["primary_stage"] in ("dev", "qa")


def test_stage_enabled_primary(tmp_git_repo):
    state = session_manager.get("s1", tmp_git_repo)
    assert ps.stage_enabled(state, ps.PRIMARY_STAGE)


def test_checklist_view(tmp_git_repo):
    view = ps.get_checklist_view("s1", tmp_git_repo, "dev")
    assert len(view["items"]) >= 3
    assert "all_passed" in view


def test_update_checklist_manual(tmp_git_repo):
    ps.update_checklist_manual("s1", tmp_git_repo, "qa_smoke", True)
    state = session_manager.get("s1", tmp_git_repo)
    assert state.checklist_manual["qa_smoke"] is True


def test_get_settings(tmp_git_repo):
    settings = ps.get_settings(tmp_git_repo)
    assert "deploy_path" in settings
    assert "provider_name" in settings


def test_list_secrets_global(tmp_vault_dir, monkeypatch):
    monkeypatch.setattr(
        "secrets_vault.get_secrets_config",
        lambda: {"backend": "local", "local": {"vault_dir": tmp_vault_dir}},
    )
    result = ps.list_secrets("global", None)
    assert result["scope"] == "global"
    assert "secrets" in result
