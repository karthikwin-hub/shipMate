from environment_inspector import ProjectInspection, TierSnapshot, suggest_next_step


def _tier(status, commit=None, **extra):
    short = commit[:7] if commit else None
    return TierSnapshot(
        reachable=True, status=status, commit=commit, commit_short=short, extra=extra
    ).to_dict()


def test_suggest_push_when_dev_ahead():
    inspection = ProjectInspection(
        project_id="demo",
        tiers={
            "dev": _tier("ahead", ahead=2),
            "remote": _tier("pr_open"),
            "qa": _tier("synced"),
            "prod": _tier("ok"),
        },
    )
    project = {"dev_path": "/tmp/demo", "remote_url": "https://github.com/o/demo.git"}
    suggestion = suggest_next_step(project, inspection)
    assert suggestion["action"] == "dev_ship"
    assert "Push" in suggestion["title"]


def test_suggest_qa_pull_when_behind():
    inspection = ProjectInspection(
        project_id="demo",
        tiers={
            "dev": _tier("clean", ahead=0),
            "remote": _tier("pr_open", pr={"state": "OPEN", "number": 14}),
            "qa": _tier("behind", behind=2),
            "prod": _tier("ok"),
        },
    )
    project = {"dev_path": "/tmp/demo", "qa_path": "/tmp/qa", "remote_url": "https://github.com/o/demo.git"}
    suggestion = suggest_next_step(project, inspection)
    assert suggestion["action"] == "qa_pull"


def test_suggest_deploy_when_prod_differs():
    inspection = ProjectInspection(
        project_id="demo",
        tiers={
            "dev": _tier("clean", ahead=0),
            "remote": _tier("synced", commit="abc123"),
            "qa": _tier("synced"),
            "prod": _tier("behind", commit="old456"),
        },
    )
    project = {"dev_path": "/tmp/demo", "provider": "oracle_vm", "remote_url": "https://github.com/o/demo.git"}
    suggestion = suggest_next_step(project, inspection)
    assert suggestion["action"] == "prod_deploy"
