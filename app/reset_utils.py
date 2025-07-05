from flask import current_app
from itsdangerous import URLSafeTimedSerializer
import os
import smtplib
from email.message import EmailMessage


def generate_reset_token(email: str) -> str:
    """Generate a timed token for password resets."""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(email, salt='password-reset')


def verify_reset_token(token: str, expiration: int = 3600) -> str | None:
    """Return the email embedded in a reset token if valid, else None."""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = serializer.loads(token, salt='password-reset', max_age=expiration)
    except Exception:
        return None
    return email


def send_reset_email(to_email: str, reset_url: str) -> None:
    """Send password reset email via Gmail SMTP."""
    user = os.getenv('GMAIL_USER')
    password = os.getenv('GMAIL_PASS')
    if not user or not password:
        raise RuntimeError('GMAIL_USER and GMAIL_PASS must be set')

    msg = EmailMessage()
    msg['Subject'] = 'Tokatap Password Reset'
    msg['From'] = user
    msg['To'] = to_email
    msg.set_content(
        f'Click the link below to reset your password:\n{reset_url}\n\n'
        'If you did not request a reset, please ignore this email.'
    )

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
