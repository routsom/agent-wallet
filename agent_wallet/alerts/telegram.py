"""Telegram alert channel for agent-wallet."""

from __future__ import annotations

import json
import logging
from urllib import request as urllib_request
from urllib.error import URLError

from agent_wallet.alerts.base import AlertBase

logger = logging.getLogger("agent_wallet.alerts.telegram")


class TelegramAlert(AlertBase):
    """Sends budget alerts via Telegram Bot API."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}"

    def send(
        self,
        wallet_name: str,
        threshold_pct: float,
        budget_pct: float,
        spent_usd: float,
        limit_usd: float,
        period_type: str,
    ) -> None:
        """Send alert to Telegram chat."""
        text = self.format_message(
            wallet_name, threshold_pct, budget_pct, spent_usd, limit_usd, period_type
        )

        if not self._bot_token or not self._chat_id:
            logger.warning("Telegram alert skipped: missing bot_token or chat_id")
            return

        url = f"{self._base_url}/sendMessage"
        payload = json.dumps({"chat_id": self._chat_id, "text": text}).encode()

        try:
            req = urllib_request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib_request.urlopen(req, timeout=10)
            logger.info(f"Telegram alert sent for wallet '{wallet_name}'")
        except (URLError, TimeoutError) as e:
            logger.warning(f"Telegram alert failed: {e}")
