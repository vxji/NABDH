# =============================================================
# services/notifications/dispatcher.py — Fan-out across enabled channels
# NABDH AI Maintenance Platform v4.2.0
# =============================================================

import logging
from typing import Optional

import database
from services.notifications.email_channel import EmailChannel
from services.notifications.slack_channel import SlackChannel
from services.notifications.webhook_channel import WebhookChannel

logger = logging.getLogger(__name__)

_CHANNELS = {
    "email":   EmailChannel(),
    "slack":   SlackChannel(),
    "webhook": WebhookChannel(),
}


async def notify_user(
    username:             str,
    subject:              str,
    body:                 str,
    attachment:           Optional[bytes] = None,
    attachment_filename:  Optional[str]   = None,
) -> dict:
    """
    Fans out to every channel the user has enabled in notification_settings.
    Returns {channel_name: success_bool}. Never raises — a failing channel
    doesn't block the others.
    """
    settings = database.get_notification_settings(username)
    results: dict = {}
    for row in settings:
        if not row["enabled"]:
            continue
        channel = _CHANNELS.get(row["channel"])
        if channel is None:
            continue
        try:
            ok = await channel.send(
                subject             = subject,
                body                = body,
                channel_config      = row.get("config") or {},
                attachment          = attachment,
                attachment_filename = attachment_filename,
            )
        except Exception as exc:
            logger.warning("Notification channel '%s' raised for user '%s': %s", row["channel"], username, exc)
            ok = False
        results[row["channel"]] = ok
    return results


async def notify_all_enabled(
    subject:              str,
    body:                 str,
    attachment:           Optional[bytes] = None,
    attachment_filename:  Optional[str]   = None,
) -> dict:
    """Fans out to every user with at least one enabled channel. Used by the
    proactive maintenance scheduler, and by §6's critical-alert path (with a
    PDF report attached). Returns {username: {channel: bool}}."""
    rows = database.get_all_enabled_notification_settings()
    usernames = sorted({r["username"] for r in rows})
    results = {}
    for username in usernames:
        results[username] = await notify_user(
            username, subject, body,
            attachment=attachment, attachment_filename=attachment_filename,
        )
    return results
