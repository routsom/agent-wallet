"""Discord kill switch for agent-wallet.

Uses Discord webhook API to listen for commands and reply.
Note: Discord webhooks are send-only. For receiving commands,
this uses a simple HTTP polling mechanism on a custom endpoint
or a Discord bot token if available.
"""

from __future__ import annotations

import json
import logging
from urllib import request as urllib_request
from urllib.error import URLError

from agent_wallet.killswitch.base import KillSwitchBase
from agent_wallet.ledger import Ledger

logger = logging.getLogger("agent_wallet.killswitch.discord")


class DiscordKillSwitch(KillSwitchBase):
    """Discord-based kill switch.

    Uses a webhook URL for sending replies. Command polling requires
    a separate bot setup or webhook endpoint.
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
            ledger=ledger,
        )
        self._webhook_url = webhook_url

    @property
    def platform_name(self) -> str:
        return "discord"

    def poll(self) -> None:
        """Poll for new Discord messages.

        Note: Standard Discord webhooks are send-only. In production,
        you'd use a Discord bot with gateway intents. This is a placeholder
        that can be extended with a bot token-based implementation.
        """
        # Discord webhooks don't support receiving messages.
        # This is intentionally a no-op for the webhook-only setup.
        # A full implementation would use discord.py with gateway intents.
        pass

    def reply(self, text: str) -> None:
        """Send a message to the Discord channel via webhook."""
        if not self._webhook_url:
            logger.warning("Discord reply skipped: missing webhook_url")
            return

        payload = json.dumps({"content": text}).encode()

        try:
            req = urllib_request.Request(
                self._webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib_request.urlopen(req, timeout=10)
        except (URLError, TimeoutError) as e:
            logger.warning(f"Discord reply failed: {e}")
