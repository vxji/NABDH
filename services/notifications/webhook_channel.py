# =============================================================
# services/notifications/webhook_channel.py — Generic custom webhook delivery
# NABDH AI Maintenance Platform v4.2.0
# =============================================================

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

import config
from services.notifications.base import NotificationChannel

logger = logging.getLogger(__name__)


class WebhookChannel(NotificationChannel):
    """
    Posts a plain JSON payload to any URL — for integrations that aren't
    Slack-shaped (Teams, PagerDuty relays, internal systems, ...).
    """

    name = "webhook"

    async def send(
        self,
        *,
        subject:              str,
        body:                 str,
        channel_config:       dict,
        attachment:           Optional[bytes] = None,
        attachment_filename:  Optional[str]   = None,
    ) -> bool:
        webhook_url = (channel_config or {}).get("webhook_url") or config.CUSTOM_NOTIFICATION_WEBHOOK_URL
        if not webhook_url:
            logger.warning("WebhookChannel: no webhook_url configured — skipping send")
            return False

        payload = {
            "subject":   subject,
            "body":      body,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(webhook_url, json=payload)
            if resp.status_code >= 300:
                logger.warning("WebhookChannel: endpoint returned status %d", resp.status_code)
                return False
            return True
        except Exception as exc:
            logger.warning("WebhookChannel send failed: %s", exc)
            return False
