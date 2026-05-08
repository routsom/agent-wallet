"""Generic HTTP webhook kill switch for agent-wallet.

Polls an HTTP endpoint for kill switch commands and sends
replies via a configurable webhook URL.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib import request as urllib_request
from urllib.error import URLError

from agent_wallet.killswitch.base import KillSwitchBase
from agent_wallet.ledger import Ledger

logger = logging.getLogger("agent_wallet.killswitch.webhook")


class WebhookKillSwitch(KillSwitchBase):
    """Generic HTTP webhook-based kill switch.

    Polls a GET endpoint for new commands and sends replies via POST.
    """

    def __init__(
        self,
        webhook_url: str,
        command: str = "STOP",
        poll_interval: int = 5,
        ledger: Ledger | None = None,
    ) -> None:
        super().__init__(
            command=command,
            poll_interval=poll_interval,
            ledger=ledger,  # type: ignore[arg-type]
        )
        self._webhook_url = webhook_url

    @property
    def platform_name(self) -> str:
        return "webhook"

    def poll(self) -> None:
        """Poll the webhook endpoint for new commands.

        Expected response format:
        {
            "messages": [
                {"text": "STOP research-bot"},
                {"text": "STATUS"}
            ]
        }
        """
        if not self._webhook_url:
            return

        poll_url = self._webhook_url.rstrip("/") + "/poll"

        try:
            req = urllib_request.Request(poll_url)
            with urllib_request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            for msg in data.get("messages", []):
                text = msg.get("text", "")
                if text:
                    self.on_message(text)

        except (URLError, TimeoutError, json.JSONDecodeError) as e:
            logger.warning(f"Webhook poll error: {e}")

    def reply(self, text: str) -> None:
        """Send a reply to the webhook endpoint via POST."""
        if not self._webhook_url:
            logger.warning("Webhook reply skipped: missing webhook_url")
            return

        reply_url = self._webhook_url.rstrip("/") + "/reply"
        payload = json.dumps({"text": text}).encode()

        try:
            req = urllib_request.Request(
                reply_url,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib_request.urlopen(req, timeout=10)
        except (URLError, TimeoutError) as e:
            logger.warning(f"Webhook reply failed: {e}")
