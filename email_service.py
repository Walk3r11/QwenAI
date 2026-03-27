import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from jinja2 import Environment, FileSystemLoader

from config import (
    BREVO_API_KEY,
    BREVO_SENDER_EMAIL,
    BREVO_SENDER_NAME,
    SMTP_FROM_EMAIL,
    SMTP_FROM_NAME,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_TIMEOUT_SEC,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
    SMTP_USER,
)

_BASE_DIR = Path(__file__).resolve().parent
env = Environment(loader=FileSystemLoader(str(_BASE_DIR / "email_templates")))

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def is_email_configured() -> bool:
    if BREVO_API_KEY:
        return bool(BREVO_SENDER_EMAIL)
    return bool(SMTP_USER) and bool(SMTP_PASSWORD)


def _render_verification_html(name: str, code: str) -> str:
    template = env.get_template("verification.html")
    return template.render(name=name, code=code)


def _send_via_brevo(to_email: str, name: str, code: str) -> bool:
    if not BREVO_API_KEY or not BREVO_SENDER_EMAIL:
        return False

    html_content = _render_verification_html(name, code)
    plain = f"Hello {name}, your SnapChef verification code is: {code}"

    payload = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": to_email, "name": name}],
        "subject": "Verify your SnapChef account",
        "htmlContent": html_content,
        "textContent": plain,
    }

    try:
        r = requests.post(
            BREVO_API_URL,
            headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json", "Accept": "application/json"},
            json=payload,
            timeout=30,
        )
        if r.status_code in (200, 201, 202):
            return True
        print(f"[EMAIL ERROR] Brevo HTTP {r.status_code}: {r.text[:500]}")
        return False
    except requests.RequestException as e:
        print(f"[EMAIL ERROR] Brevo request failed: {type(e).__name__}: {e}")
        return False


def _send_via_smtp(to_email: str, name: str, code: str) -> bool:
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD or not SMTP_FROM_EMAIL:
        return False

    html_content = _render_verification_html(name, code)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Verify your SnapChef account"
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.attach(MIMEText(f"Hello {name}, your SnapChef verification code is: {code}", "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        smtp_client_cls = smtplib.SMTP_SSL if SMTP_USE_SSL else smtplib.SMTP
        with smtp_client_cls(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SEC) as server:
            if SMTP_USE_TLS and not SMTP_USE_SSL:
                server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] SMTP failed: {type(e).__name__}: {e}")
        return False


def send_verification_email(to_email: str, name: str, code: str) -> bool:
    if BREVO_API_KEY:
        return _send_via_brevo(to_email, name, code)
    return _send_via_smtp(to_email, name, code)
