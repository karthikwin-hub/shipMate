from pathlib import Path

import shipmate_user_config as cfg


def test_normalize_remote_url_https():
    assert cfg.normalize_remote_url("https://github.com/Org/Repo.git") == "github.com/org/repo"


def test_normalize_remote_url_ssh():
    assert cfg.normalize_remote_url("git@github.com:Org/Repo.git") == "github.com/org/repo"


def test_register_and_load_paths(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_file)

    cfg.register_local_path(str(tmp_path / "proj"), "https://github.com/user/repo.git")
    paths = cfg.get_registered_paths()
    assert len(paths) == 1
    assert paths[0]["remote"] == "github.com/user/repo"
    assert Path(paths[0]["path"]).name == "proj"


def test_set_last_mode(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_file)

    cfg.set_last_mode("https://github.com/user/repo", "cache", "/tmp/cache/repo")
    last = cfg.get_last_mode("https://github.com/user/repo")
    assert last["mode"] == "cache"
    assert last["path"] == "/tmp/cache/repo"
