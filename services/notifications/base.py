# =============================================================
# services/notifications/base.py — Notification channel interface
# NABDH AI Maintenance Platform v4.2.0
# =============================================================

from abc import ABC, abstractmethod
from typing import Optional


class NotificationChannel(ABC):
    """
    A single delivery mechanism (email, Slack, generic webhook, ...).
    `channel_config` is the per-user JSON blob stored in
    notification_settings.config (e.g. {"email_address": "..."} or
    {"webhook_url": "..."}), falling back to a system-wide default when a
    user hasn't set one.
    """

    name: str

    @abstractmethod
    async def send(
        self,
        *,
        subject:              str,
        body:                 str,
        channel_config:       dict,
        attachment:           Optional[bytes] = None,
        attachment_filename:  Optional[str]   = None,
    ) -> bool:
        """Returns True on successful delivery, False otherwise (never raises)."""
        raise NotImplementedError
