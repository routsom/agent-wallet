"""Unit tests for agent_wallet/alerts/."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_wallet.alerts.discord import DiscordAlert
from agent_wallet.alerts.telegram import TelegramAlert
from agent_wallet.alerts.webhook import WebhookAlert


# Common alert call kwargs used across tests.
_ALERT_KWARGS = dict(
    wallet_name="test-wallet",
    threshold_pct=0.8,
    budget_pct=0.85,
    spent_usd=4.25,
    limit_usd=5.00,
    period_type="daily",
)


class TestWebhookAlert:
    def test_send_makes_post_request(self):
        """send() should POST JSON to the webhook URL."""
        alert = WebhookAlert(webhook_url="https://example.com/hook")

        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("agent_wallet.alerts.webhook.urllib_request.urlopen") as mock_open:
            mock_open.return_value = mock_resp
            alert.send(**_ALERT_KWARGS)

        mock_open.assert_called_once()
        req = mock_open.call_args[0][0]
        assert req.full_url == "https://example.com/hook"
        assert req.get_header("Content-type") == "application/json"

        body = json.loads(req.data.decode())
        assert body["wallet_name"] == "test-wallet"
        assert body["threshold_pct"] == 0.8
        assert body["spent_usd"] == 4.25
        assert "text" in body

    def test_send_skipped_when_url_empty(self):
        """send() should log a warning and skip when webhook_url is empty."""
        alert = WebhookAlert(webhook_url="")

        with patch("agent_wallet.alerts.webhook.urllib_request.urlopen") as mock_open:
            alert.send(**_ALERT_KWARGS)
            mock_open.assert_not_called()

    def test_send_handles_url_error_gracefully(self):
        """send() should catch URLError and not raise."""
        from urllib.error import URLError

        alert = WebhookAlert(webhook_url="https://example.com/hook")

        with patch(
            "agent_wallet.alerts.webhook.urllib_request.urlopen",
            side_effect=URLError("connection refused"),
        ):
            # Must not raise
            alert.send(**_ALERT_KWARGS)

    def test_format_message_contains_key_info(self):
        """format_message() should include wallet name, threshold, and spend."""
        alert = WebhookAlert(webhook_url="https://example.com/hook")
        msg = alert.format_message(**_ALERT_KWARGS)
        assert "test-wallet" in msg
        assert "80%" in msg
        assert "$4.2500" in msg


class TestTelegramAlert:
    def test_send_makes_post_to_sendmessage(self):
        """send() should POST to Telegram sendMessage endpoint."""
        alert = TelegramAlert(bot_token="tok123", chat_id="chat456")

        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("agent_wallet.alerts.telegram.urllib_request.urlopen") as mock_open:
            mock_open.return_value = mock_resp
            alert.send(**_ALERT_KWARGS)

        mock_open.assert_called_once()
        req = mock_open.call_args[0][0]
        assert "api.telegram.org" in req.full_url
        assert "sendMessage" in req.full_url

        body = json.loads(req.data.decode())
        assert body["chat_id"] == "chat456"
        assert "test-wallet" in body["text"]

    def test_send_skipped_when_token_empty(self):
        """send() should skip when bot_token is empty."""
        alert = TelegramAlert(bot_token="", chat_id="chat456")

        with patch("agent_wallet.alerts.telegram.urllib_request.urlopen") as mock_open:
            alert.send(**_ALERT_KWARGS)
            mock_open.assert_not_called()

    def test_send_skipped_when_chat_id_empty(self):
        """send() should skip when chat_id is empty."""
        alert = TelegramAlert(bot_token="tok123", chat_id="")

        with patch("agent_wallet.alerts.telegram.urllib_request.urlopen") as mock_open:
            alert.send(**_ALERT_KWARGS)
            mock_open.assert_not_called()

    def test_send_handles_url_error_gracefully(self):
        """send() should catch URLError and not raise."""
        from urllib.error import URLError

        alert = TelegramAlert(bot_token="tok123", chat_id="chat456")

        with patch(
            "agent_wallet.alerts.telegram.urllib_request.urlopen",
            side_effect=URLError("timeout"),
        ):
            alert.send(**_ALERT_KWARGS)


class TestDiscordAlert:
    def test_send_makes_post_to_webhook(self):
        """send() should POST JSON with 'content' key to the Discord webhook URL."""
        alert = DiscordAlert(webhook_url="https://discord.com/api/webhooks/123/abc")

        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("agent_wallet.alerts.discord.urllib_request.urlopen") as mock_open:
            mock_open.return_value = mock_resp
            alert.send(**_ALERT_KWARGS)

        mock_open.assert_called_once()
        req = mock_open.call_args[0][0]
        assert req.full_url == "https://discord.com/api/webhooks/123/abc"
        assert req.get_header("Content-type") == "application/json"

        body = json.loads(req.data.decode())
        assert "content" in body
        assert "test-wallet" in body["content"]

    def test_send_skipped_when_url_empty(self):
        """send() should skip when webhook_url is empty."""
        alert = DiscordAlert(webhook_url="")

        with patch("agent_wallet.alerts.discord.urllib_request.urlopen") as mock_open:
            alert.send(**_ALERT_KWARGS)
            mock_open.assert_not_called()

    def test_send_handles_url_error_gracefully(self):
        """send() should catch URLError and not raise."""
        from urllib.error import URLError

        alert = DiscordAlert(webhook_url="https://discord.com/api/webhooks/123/abc")

        with patch(
            "agent_wallet.alerts.discord.urllib_request.urlopen",
            side_effect=URLError("network error"),
        ):
            alert.send(**_ALERT_KWARGS)

    def test_format_message_100pct_shows_red_emoji(self):
        """format_message at 100% budget should include the red emoji."""
        alert = DiscordAlert(webhook_url="https://discord.com/api/webhooks/123/abc")
        msg = alert.format_message(
            wallet_name="w",
            threshold_pct=1.0,
            budget_pct=1.0,
            spent_usd=5.00,
            limit_usd=5.00,
            period_type="daily",
        )
        assert "\U0001f534" in msg  # 🔴

    def test_format_message_80pct_shows_yellow_emoji(self):
        """format_message at 80% budget should include the yellow emoji."""
        alert = DiscordAlert(webhook_url="https://discord.com/api/webhooks/123/abc")
        msg = alert.format_message(
            wallet_name="w",
            threshold_pct=0.8,
            budget_pct=0.85,
            spent_usd=4.25,
            limit_usd=5.00,
            period_type="daily",
        )
        assert "\U0001f7e1" in msg  # 🟡
