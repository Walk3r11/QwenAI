import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from jinja2 import Environment, FileSystemLoader
import os

env = Environment(loader=FileSystemLoader("email_templates"))


def send_verification_email(to_email: str, name: str, code: str):
    """
    Sends an HTML verification email with a 6-digit code.
    """
    # Read fresh on every call so Railway env-var changes take effect without restart
    smtp_email = os.environ.get("SMTP_EMAIL", "snapchef.noreply@gmail.com")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    print(f"[EMAIL] Attempting to send to {to_email} | SMTP_EMAIL set: {bool(smtp_email)} | SMTP_PASSWORD set: {bool(smtp_password)}")

    try:
        if not smtp_email or not smtp_password:
            raise ValueError(
                f"[EMAIL ERROR] SMTP credentials missing — "
                f"SMTP_EMAIL={'set' if smtp_email else 'MISSING'}, "
                f"SMTP_PASSWORD={'set' if smtp_password else 'MISSING'}"
            )
        # Both are confirmed non-empty strings past this point
        smtp_password = str(smtp_password)

        template = env.get_template("verification.html")
        html_content = template.render(name=name, code=code)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Verify your SnapChef account 👨‍🍳"
        msg["From"] = f"SnapChef <{smtp_email}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            try:
                server.login(smtp_email, smtp_password)
            except smtplib.SMTPAuthenticationError as e:
                print(f"[EMAIL ERROR] SMTP auth failed for '{smtp_email}': {e}")
                raise
            server.sendmail(smtp_email, to_email, msg.as_string())
            print(f"[EMAIL] Successfully sent to {to_email}")

        return True

    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send email to {to_email}: {type(e).__name__}: {e}")
        return False
