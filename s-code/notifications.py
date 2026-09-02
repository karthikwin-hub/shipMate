import smtplib
from email.mime.text import MIMEText
import requests

class NotificationManager:
    def __init__(self, webhook_url: str = None, smtp_config: dict = None):
        self.webhook_url = webhook_url
        self.smtp_config = smtp_config

    def send_webhook(self, title: str, message: str, is_success: bool = True):
        if not self.webhook_url: return
        color = 3066993 if is_success else 15158332
        payload = {
            "embeds": [{
                "title": title,
                "description": message,
                "color": color
            }]
        }
        try:
            requests.post(self.webhook_url, json=payload, timeout=5)
        except Exception as e:
            print(f"Webhook failed: {e}")

    def send_email(self, subject: str, body: str, recipient: str):
        if not self.smtp_config: return
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = self.smtp_config.get('from_email')
        msg['To'] = recipient
        try:
            with smtplib.SMTP(self.smtp_config.get('server'), self.smtp_config.get('port', 587)) as server:
                server.starttls()
                server.login(self.smtp_config.get('user'), self.smtp_config.get('password'))
                server.send_message(msg)
        except Exception as e:
            print(f"Email sending failed: {e}")