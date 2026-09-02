import os
from pathlib import Path

import config_loader


def test_load_config_has_secrets_section():
    cfg = config_loader.load_config()
    assert "secrets" in cfg or "notifications" in cfg


def test_get_secrets_config():
    cfg = config_loader.get_secrets_config()
    assert "backend" in cfg or cfg == {} or "local" in cfg


def test_expand_env(monkeypatch):
    monkeypatch.setenv("TEST_SHIPMATE_VAR", "hello")
    result = config_loader._expand_env("${TEST_SHIPMATE_VAR}")
    assert result == "hello"


def test_get_audit_file_default():
    path = config_loader.get_audit_file()
    assert path.endswith(".json")
