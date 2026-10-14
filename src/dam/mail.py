from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from dam.config import get_settings

log = logging.getLogger(__name__)


async def send_mail(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if settings.mail_backend == "console":
        log.info("MAIL to=%s subject=%s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        start_tls=True,
    )
