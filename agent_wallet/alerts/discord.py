"""Discord alert channel for agent-wallet."""

from __future__ import annotations

import json
import logging
from urllib import request as urllib_request
from urllib.error import URLError

from agent_wallet.alerts.base import AlertBase

logger = logging.getLogger("agent_wallet.alerts.discord")


class DiscordAlert(AlertBase):
    """Sends budget alerts via Discord webhook."""

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    def send(
        self,
        wallet_name: str,
        threshold_pct: float,
        budget_pct: float,
        spent_usd: float,
        limit_usd: float,
        period_type: str,
    ) -> None:
        """Send alert to Discord channel via webhook."""
        text = self.format_message(
            wallet_name, threshold_pct, budget_pct, spent_usd, limit_usd, period_type
        )

        if not self._webhook_url:
            logger.warning("Discord alert skipped: missing webhook_url")
            return

        payload = json.dumps({"content": text}).encode()

        try:
            req = urllib_request.Request(
                self._webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib_request.urlopen(req, timeout=10)
            logger.info(f"Discord alert sent for wallet '{wallet_name}'")
        except (URLError, TimeoutError) as e:
            logger.warning(f"Discord alert failed: {e}")
