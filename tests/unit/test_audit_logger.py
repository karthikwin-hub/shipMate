import json

import audit_logger


def test_log_and_get_entries(tmp_audit_file):
    audit_logger.log_action(
        project="/repo/a",
        git_user="user@test.com",
        stage="dev",
        branch="feature/x",
        action="ship",
        status="success",
        details="PR created",
    )
    entries = audit_logger.get_entries()
    assert len(entries) == 1
    assert entries[0]["project"] == "/repo/a"
    assert entries[0]["stage"] == "dev"
    assert entries[0]["action"] == "ship"
    assert "timestamp" in entries[0]


def test_log_appends(tmp_audit_file):
    audit_logger.log_action("p", "u", "dev", "b", "a1", "success")
    audit_logger.log_action("p", "u", "qa", "b", "a2", "failure")
    entries = audit_logger.get_entries()
    assert len(entries) == 2
    assert entries[1]["status"] == "failure"


def test_log_checklist_and_host_override(tmp_audit_file):
    audit_logger.log_action(
        project="/repo",
        git_user="u",
        stage="qa",
        branch="main",
        action="approve",
        status="success",
        checklist_items=["qa_tests_passed"],
        host_override=True,
    )
    entry = audit_logger.get_entries()[0]
    assert entry["checklist_items"] == ["qa_tests_passed"]
    assert entry["host_override"] is True


def test_corrupt_audit_file_returns_empty(tmp_audit_file):
    with open(tmp_audit_file, "w", encoding="utf-8") as f:
        f.write("not json")
    assert audit_logger.get_entries() == []
