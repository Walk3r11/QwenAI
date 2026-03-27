import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_BASE_DIR = Path(__file__).resolve().parent
env = Environment(loader=FileSystemLoader(str(_BASE_DIR / "email_templates")))


def send_verification_email(to_email: str, name: str, code: str):
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", os.environ.get("SMTP_EMAIL", "")).strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    smtp_from_email = os.environ.get("SMTP_FROM_EMAIL", smtp_user).strip()
    smtp_from_name = os.environ.get("SMTP_FROM_NAME", "SnapChef").strip()
    smtp_use_tls = os.environ.get("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}
    smtp_use_ssl = os.environ.get("SMTP_USE_SSL", "false").strip().lower() in {"1", "true", "yes", "on"}
    smtp_timeout = int(os.environ.get("SMTP_TIMEOUT_SEC", "20"))

    try:
        if not smtp_host or not smtp_user or not smtp_password or not smtp_from_email:
            raise ValueError(
                "SMTP configuration missing. Required: SMTP_HOST, SMTP_USER/SMTP_EMAIL, SMTP_PASSWORD, SMTP_FROM_EMAIL."
            )

        template = env.get_template("verification.html")
        html_content = template.render(name=name, code=code)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Verify your SnapChef account 👨‍🍳"
        msg["From"] = f"{smtp_from_name} <{smtp_from_email}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html"))
        msg.attach(MIMEText(f"Hello {name}, your SnapChef verification code is: {code}", "plain"))

        smtp_client_cls = smtplib.SMTP_SSL if smtp_use_ssl else smtplib.SMTP
        with smtp_client_cls(smtp_host, smtp_port, timeout=smtp_timeout) as server:
            if smtp_use_tls and not smtp_use_ssl:
                server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from_email, to_email, msg.as_string())

        return True

    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send verification email to {to_email}: {type(e).__name__}: {e}")
        return False
