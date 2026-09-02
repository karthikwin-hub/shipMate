import smtplib
from email.mime.text import MIMEText

import requests

from config_loader import get_notifications_config
from secrets_vault import get_global_secret


class NotificationManager:
    def __init__(self, config: dict | None = None):
        cfg = config or get_notifications_config()
        self.webhook_url = cfg.get("webhook_url") or ""
        self.webhook_type = (cfg.get("webhook_type") or "discord").lower()
        self.smtp_config = cfg.get("smtp") or {}

    def _resolve_smtp_credential(self, key: str, secret_name: str | None) -> str:
        if secret_name:
            val = get_global_secret(secret_name)
            if val:
                return val
        return self.smtp_config.get(key, "") or ""

    def send_webhook(self, title: str, message: str, is_success: bool = True):
        if not self.webhook_url:
            return
        payload = self._build_payload(title, message, is_success)
        try:
            requests.post(self.webhook_url, json=payload, timeout=5)
        except Exception as e:
            print(f"Webhook failed: {e}")

    def _build_payload(self, title: str, message: str, is_success: bool) -> dict:
        if self.webhook_type == "slack":
            emoji = ":white_check_mark:" if is_success else ":rotating_light:"
            return {"text": f"{emoji} *{title}*\n{message}"}
        if self.webhook_type == "teams":
            color = "00FF00" if is_success else "FF0000"
            return {
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "themeColor": color,
                "summary": title,
                "sections": [{"activityTitle": title, "text": message}],
            }
        color = 3066993 if is_success else 15158332
        return {
            "embeds": [{"title": title, "description": message, "color": color}]
        }

    def send_email(self, subject: str, body: str, recipient: str | None = None):
        server = self.smtp_config.get("server")
        if not server:
            return
        recipient = recipient or self.smtp_config.get("to_email", "")
        if not recipient:
            return
        user = self._resolve_smtp_credential("user", self.smtp_config.get("user_secret"))
        password = self._resolve_smtp_credential("password", self.smtp_config.get("password_secret"))
        if not user or not password:
            return
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = self.smtp_config.get("from_email", "")
        msg["To"] = recipient
        try:
            with smtplib.SMTP(server, self.smtp_config.get("port", 587)) as smtp:
                smtp.starttls()
                smtp.login(user, password)
                smtp.send_message(msg)
        except Exception as e:
            print(f"Email sending failed: {e}")

    def notify_success(
        self,
        repo: str,
        author: str,
        branch: str,
        commit: str,
        live_url: str,
    ):
        title = "Production Deployment Successful - App Ready to Use"
        message = (
            f"Repo: {repo}\nAuthor: {author}\nBranch: {branch}\n"
            f"Commit: {commit}\nLive URL: {live_url}"
        )
        self.send_webhook(title, message, True)
        self.send_email(title, message)

    def notify_failure(self, stage: str, error_snippet: str):
        title = f"Pipeline Failure in {stage}"
        snippet = error_snippet[:500] if error_snippet else "No details"
        message = f"Stage: {stage}\n\n{snippet}"
        self.send_webhook(title, message, False)
        self.send_email(title, message)
