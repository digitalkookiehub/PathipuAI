"""Sending the few emails PathippuAI needs (password-reset links, sign-up notices) through an SMTP server."""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import Settings

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 20


def send_email(settings: Settings, to: str, subject: str, body: str) -> bool:
    """Send a plain-text email; returns False (and logs) instead of raising, so a mail problem never breaks a page."""
    if not settings.mail_enabled:
        logger.warning("Email is not set up (SMTP_HOST / SMTP_FROM); not sending '%s'", subject)
        return False
    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_username
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        context = ssl.create_default_context()
        if settings.smtp_security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=TIMEOUT_SECONDS, context=context
            )
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=TIMEOUT_SECONDS)
        with server:
            if settings.smtp_security == "starttls":
                server.starttls(context=context)
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        logger.error("Could not send email '%s': %s", subject, type(exc).__name__)
        return False
    logger.info("Sent email '%s'", subject)
    return True
