import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from jinja2 import Environment, FileSystemLoader
import os

env = Environment(loader=FileSystemLoader("email_templates"))

SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "snapchef.noreply@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")

def send_verification_email(to_email: str, name: str, code: str):
    """
    Sends an HTML verification email with a 6-digit code.
    """
    try:
        if not SMTP_EMAIL or not SMTP_PASSWORD:
            raise ValueError("SMTP_EMAIL or SMTP_PASSWORD environment variables are missing!")

        template = env.get_template("verification.html")
        html_content = template.render(name=name, code=code)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Verify your SnapChef account 👨‍🍳"
        msg["From"] = f"SnapChef <{SMTP_EMAIL}>"
        msg["To"] = to_email

        # Attach HTML
        msg.attach(MIMEText(html_content, "html"))

        # Connect to Gmail SMTP Server securely
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        
        try:
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
            print(f"Email successfully sent to {to_email}!")
        except smtplib.SMTPAuthenticationError:
            print(f"AUTH FAILED: Make sure SMTP_EMAIL ('{SMTP_EMAIL}') matches your App Password account.")
            raise
        finally:
            server.quit()
            
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False
