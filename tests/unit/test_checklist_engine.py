from checklist_engine import BUILTIN_DEV, BUILTIN_QA, ChecklistEngine
from deploy_providers.oracle_vm import OracleVMProvider


def test_builtin_dev_items(tmp_git_repo):
    engine = ChecklistEngine(tmp_git_repo)
    items = engine.get_stage_items("dev")
    assert len(items) == len(BUILTIN_DEV)


def test_builtin_qa_items(tmp_git_repo):
    engine = ChecklistEngine(tmp_git_repo)
    items = engine.get_stage_items("qa")
    ids = {i["id"] for i in items}
    for builtin in BUILTIN_QA:
        assert builtin["id"] in ids


def test_dynamic_qa_checklist_keys(checklist_repo):
    engine = ChecklistEngine(checklist_repo)
    items = engine.get_stage_items("qa")
    ids = {i["id"] for i in items}
    assert "smoke" in ids
    assert "auto_ok" in ids


def test_all_passed_gatekeeper_manual_only(tmp_git_repo):
    engine = ChecklistEngine(tmp_git_repo)
    manual = {"qa_smoke": True}
    builtin = {i["id"]: True for i in BUILTIN_QA}
    assert engine.all_passed("qa", manual, builtin, {})


def test_all_passed_blocks_incomplete_manual(tmp_git_repo):
    engine = ChecklistEngine(tmp_git_repo)
    manual = {"qa_smoke": False}
    builtin = {i["id"]: True for i in BUILTIN_QA}
    assert not engine.all_passed("qa", manual, builtin, {})


def test_automated_check_echo(checklist_repo):
    engine = ChecklistEngine(checklist_repo)
    ok, _ = engine.run_automated_check("echo hello")
    assert ok


def test_automated_items(checklist_repo):
    engine = ChecklistEngine(checklist_repo)
    results = engine.run_automated_items("qa")
    assert results.get("auto_ok") is True


def test_provider_aware_prod_builtins(oracle_deploy_repo):
    provider = OracleVMProvider(oracle_deploy_repo)
    engine = ChecklistEngine(oracle_deploy_repo, prod_builtin=provider.get_builtin_checks())
    prod_ids = {i["id"] for i in engine.get_stage_items("prod")}
    assert "prod_ssh" in prod_ids
