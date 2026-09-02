import audit_analytics
import audit_logger


def _log(project, stage, action, status):
    audit_logger.log_action(project, "user@test.com", stage, "feature/x", action, status)


def test_get_distinct_projects(tmp_audit_file):
    _log("/repo/a", "dev", "ship", "success")
    _log("/repo/b", "qa", "test", "success")
    _log("/repo/a", "qa", "merge", "success")
    assert sorted(audit_analytics.get_distinct_projects()) == ["/repo/a", "/repo/b"]


def test_get_project_summary(tmp_audit_file, tmp_git_repo):
    _log(tmp_git_repo, "dev", "ship", "success")
    _log(tmp_git_repo, "qa", "test", "failure")
    summary = audit_analytics.get_project_summary(tmp_git_repo)
    assert summary["total_runs"] == 2
    assert summary["failures"] == 1
    assert summary["last_action"] == "test"
    assert summary["stage_counts"]["dev"] == 1
    assert summary["stage_counts"]["qa"] == 1


def test_get_project_timeline_order(tmp_audit_file, tmp_git_repo):
    _log(tmp_git_repo, "dev", "first", "success")
    _log(tmp_git_repo, "dev", "second", "success")
    timeline = audit_analytics.get_project_timeline(tmp_git_repo)
    assert timeline[0]["action"] == "second"
    assert timeline[1]["action"] == "first"


def test_suggest_current_stage_after_dev(tmp_audit_file, tmp_git_repo):
    _log(tmp_git_repo, "dev", "ship", "success")
    assert audit_analytics.suggest_current_stage(tmp_git_repo) == "dev"


def test_suggest_current_stage_after_qa(tmp_audit_file, tmp_git_repo):
    _log(tmp_git_repo, "dev", "ship", "success")
    _log(tmp_git_repo, "qa", "merge", "success")
    assert audit_analytics.suggest_current_stage(tmp_git_repo) == "qa"


def test_get_all_projects_overview(tmp_audit_file):
    _log("/repo/a", "dev", "ship", "success")
    _log("/repo/b", "prod", "deploy", "success")
    overview = audit_analytics.get_all_projects_overview()
    assert len(overview) == 2
