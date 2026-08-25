"""
Tests for §4: multi-channel notifications + proactive scheduling.

Covers: the pure is_approaching_critical predicate, each channel in
isolation (mocked SMTP/HTTP — no real network calls), the dispatcher's
fan-out/skip-disabled logic, and the /notifications/settings endpoints.
"""
from unittest.mock import AsyncMock, patch

import pytest

import database
from services.notifications import dispatcher
from services.notifications.proactive_check import is_approaching_critical

from tests.conftest import auth_headers


# ── is_approaching_critical (pure function) ────────────────────

@pytest.mark.parametrize("health_score,trend,drift_flag,expected", [
    (20.0, "STABLE", False, True),    # already below the proactive threshold
    (80.0, "STABLE", False, False),   # healthy, no signal
    (80.0, "RISING", True, True),     # rising trend confirmed by drift
    (80.0, "RISING", False, False),   # rising trend alone isn't enough
    (None, "STABLE", False, False),   # missing health score, no other signal
])
def test_is_approaching_critical(health_score, trend, drift_flag, expected):
    assert is_approaching_critical(health_score, trend, drift_flag) is expected


# ── Individual channels (mocked transport) ─────────────────────

async def test_email_channel_sends_when_configured(monkeypatch):
    from services.notifications.email_channel import EmailChannel
    import config as nabdh_config

    monkeypatch.setattr(nabdh_config, "SMTP_HOST", "smtp.example.com")
    channel = EmailChannel()

    with patch(
        "services.notifications.email_channel.aiosmtplib.send",
        new=AsyncMock(return_value=None),
    ) as mock_send:
        ok = await channel.send(subject="s", body="b", channel_config={"email_address": "a@b.com"})

    assert ok is True
    mock_send.assert_awaited_once()


async def test_email_channel_skips_without_address():
    from services.notifications.email_channel import EmailChannel

    channel = EmailChannel()
    ok = await channel.send(subject="s", body="b", channel_config={})
    assert ok is False


async def test_slack_channel_posts_webhook():
    from services.notifications.slack_channel import SlackChannel

    channel = SlackChannel()
    fake_response = AsyncMock()
    fake_response.status_code = 200

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)) as mock_post:
        ok = await channel.send(
            subject="s", body="b", channel_config={"webhook_url": "https://hooks.slack.test/x"}
        )

    assert ok is True
    mock_post.assert_awaited_once()


async def test_slack_channel_skips_without_webhook_url(monkeypatch):
    from services.notifications.slack_channel import SlackChannel
    import config as nabdh_config

    monkeypatch.setattr(nabdh_config, "SLACK_DEFAULT_WEBHOOK_URL", "")
    channel = SlackChannel()
    ok = await channel.send(subject="s", body="b", channel_config={})
    assert ok is False


async def test_webhook_channel_reports_failure_status():
    from services.notifications.webhook_channel import WebhookChannel

    channel = WebhookChannel()
    fake_response = AsyncMock()
    fake_response.status_code = 500

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        ok = await channel.send(subject="s", body="b", channel_config={"webhook_url": "https://x.test/hook"})

    assert ok is False


# ── Dispatcher fan-out ──────────────────────────────────────────

async def test_dispatcher_fans_out_to_enabled_channels_only():
    database.upsert_notification_setting("dispatch-test-user", "email", True, {"email_address": "a@b.com"})
    database.upsert_notification_setting("dispatch-test-user", "slack", False, {"webhook_url": "https://x"})

    with patch(
        "services.notifications.dispatcher.EmailChannel.send", new=AsyncMock(return_value=True)
    ) as mock_email, patch(
        "services.notifications.dispatcher.SlackChannel.send", new=AsyncMock(return_value=True)
    ) as mock_slack:
        results = await dispatcher.notify_user("dispatch-test-user", "subj", "body")

    assert results == {"email": True}
    mock_email.assert_awaited_once()
    mock_slack.assert_not_called()


# ── Settings endpoints ───────────────────────────────────────────

def test_notification_settings_endpoint_upserts(client, viewer_token):
    resp = client.put(
        "/notifications/settings",
        json={"channel": "slack", "enabled": True, "config": {"webhook_url": "https://hooks.slack.test/y"}},
        headers=auth_headers(viewer_token),
    )
    assert resp.status_code == 200

    resp = client.get("/notifications/settings", headers=auth_headers(viewer_token))
    assert resp.status_code == 200
    settings = resp.json()["settings"]
    assert any(s["channel"] == "slack" and s["enabled"] for s in settings)


def test_notification_settings_endpoint_rejects_unknown_channel(client, viewer_token):
    resp = client.put(
        "/notifications/settings",
        json={"channel": "carrier_pigeon", "enabled": True, "config": {}},
        headers=auth_headers(viewer_token),
    )
    assert resp.status_code == 422


def test_notification_settings_endpoint_requires_auth(client):
    resp = client.get("/notifications/settings")
    assert resp.status_code == 401
