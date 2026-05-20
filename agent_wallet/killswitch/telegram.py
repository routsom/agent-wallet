"""Telegram kill switch for agent-wallet.

Polls the Telegram Bot API for new messages and processes STOP/RESUME commands.
Uses a background threading.Thread (not asyncio) per the project design.
"""

from __future__ import annotations

import json
import logging
from urllib import request as urllib_request
from urllib.error import URLError

from agent_wallet.killswitch.base import KillSwitchBase
from agent_wallet.ledger import Ledger

logger = logging.getLogger("agent_wallet.killswitch.telegram")


class TelegramKillSwitch(KillSwitchBase):
    """Telegram-based kill switch using the Bot API.

    Uses urllib to avoid a hard dependency on python-telegram-bot
    for the kill switch (which only needs simple getUpdates + sendMessage).
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        command: str = "STOP",
        poll_interval: int = 5,
        ledger: Ledger | None = None,
    ) -> None:
        super().__init__(
            command=command,
            poll_interval=poll_interval,
            ledger=ledger,
        )
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._last_update_id = 0

    @property
    def platform_name(self) -> str:
        return "telegram"

    def poll(self) -> None:
        """Poll Telegram for new messages using getUpdates."""
        if not self._bot_token:
            return

        url = (
            f"{self._base_url}/getUpdates"
            f"?offset={self._last_update_id + 1}&timeout=1"
        )

        try:
            req = urllib_request.Request(url)
            with urllib_request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            if not data.get("ok"):
                return

            for update in data.get("result", []):
                update_id = update.get("update_id", 0)
                if update_id > self._last_update_id:
                    self._last_update_id = update_id

                message = update.get("message", {})
                text = message.get("text", "")
                chat_id = str(message.get("chat", {}).get("id", ""))

                # Only process messages from the configured chat
                if chat_id == self._chat_id and text:
                    self.on_message(text)

        except (URLError, TimeoutError, json.JSONDecodeError) as e:
            logger.warning(f"Telegram poll error: {e}")

    def reply(self, text: str) -> None:
        """Send a message back to the Telegram chat."""
        if not self._bot_token or not self._chat_id:
            logger.warning("Telegram reply skipped: missing bot_token or chat_id")
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
        except (URLError, TimeoutError) as e:
            logger.warning(f"Telegram reply failed: {e}")
