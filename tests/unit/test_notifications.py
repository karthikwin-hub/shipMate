from notifications import NotificationManager


def test_build_discord_payload():
    nm = NotificationManager({"webhook_type": "discord"})
    payload = nm._build_payload("Title", "Body", True)
    assert payload["embeds"][0]["title"] == "Title"
    assert payload["embeds"][0]["color"] == 3066993


def test_build_slack_payload():
    nm = NotificationManager({"webhook_type": "slack"})
    payload = nm._build_payload("Title", "Body", False)
    assert "Title" in payload["text"]


def test_resolve_smtp_from_global_secret(tmp_vault_dir, monkeypatch):
    from secrets_vault import LocalVaultBackend

    vault = LocalVaultBackend(tmp_vault_dir)
    vault.set_secret("global", "SMTP_PASSWORD", "secret-pass")
    monkeypatch.setattr("notifications.get_global_secret", lambda k: vault.get_secret("global", k))

    nm = NotificationManager({"smtp": {"password_secret": "SMTP_PASSWORD"}})
    pw = nm._resolve_smtp_credential("password", "SMTP_PASSWORD")
    assert pw == "secret-pass"


def test_send_webhook_no_url_does_not_raise():
    nm = NotificationManager({"webhook_url": ""})
    nm.send_webhook("t", "m")  # no-op
