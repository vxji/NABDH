# =============================================================
# services/notifications/slack_channel.py — Slack incoming webhook delivery
# NABDH AI Maintenance Platform v4.2.0
# =============================================================

import logging
from typing import Optional

import httpx

import config
from services.notifications.base import NotificationChannel

logger = logging.getLogger(__name__)


class SlackChannel(NotificationChannel):
    name = "slack"

    async def send(
        self,
        *,
        subject:              str,
        body:                 str,
        channel_config:       dict,
        attachment:           Optional[bytes] = None,
        attachment_filename:  Optional[str]   = None,
    ) -> bool:
        webhook_url = (channel_config or {}).get("webhook_url") or config.SLACK_DEFAULT_WEBHOOK_URL
        if not webhook_url:
            logger.warning("SlackChannel: no webhook_url configured — skipping send")
            return False

        payload = {"text": f"*{subject}*\n{body}"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(webhook_url, json=payload)
            if resp.status_code >= 300:
                logger.warning("SlackChannel: webhook returned status %d", resp.status_code)
                return False
            return True
        except Exception as exc:
            logger.warning("SlackChannel send failed: %s", exc)
            return False
