# =============================================================
# services/notifications/email_channel.py — SMTP email delivery
# NABDH AI Maintenance Platform v4.2.0
# =============================================================

import logging
from email.message import EmailMessage
from typing import Optional

import aiosmtplib

import config
from services.notifications.base import NotificationChannel

logger = logging.getLogger(__name__)


class EmailChannel(NotificationChannel):
    name = "email"

    async def send(
        self,
        *,
        subject:              str,
        body:                 str,
        channel_config:       dict,
        attachment:           Optional[bytes] = None,
        attachment_filename:  Optional[str]   = None,
    ) -> bool:
        to_address = (channel_config or {}).get("email_address")
        if not to_address:
            logger.warning("EmailChannel: no email_address configured — skipping send")
            return False
        if not config.SMTP_HOST:
            logger.warning("EmailChannel: SMTP_HOST not configured — skipping send")
            return False

        msg = EmailMessage()
        msg["From"]    = config.SMTP_FROM_ADDRESS
        msg["To"]      = to_address
        msg["Subject"] = subject
        msg.set_content(body)
        if attachment:
            msg.add_attachment(
                attachment,
                maintype = "application",
                subtype  = "pdf",
                filename = attachment_filename or "report.pdf",
            )

        try:
            await aiosmtplib.send(
                msg,
                hostname = config.SMTP_HOST,
                port     = config.SMTP_PORT,
                username = config.SMTP_USERNAME or None,
                password = config.SMTP_PASSWORD or None,
                start_tls= config.SMTP_USE_TLS,
            )
            return True
        except Exception as exc:
            logger.warning("EmailChannel send failed: %s", exc)
            return False
