"""Abstract base class for kill switches.

Kill switches run as background threads polling a messaging platform.
When a STOP/RESUME command is received, they pause/resume the wallet
via the ledger.
"""

from __future__ import annotations

import abc
import logging
import re
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_wallet.ledger import Ledger
    from agent_wallet.wallet import Wallet

logger = logging.getLogger("agent_wallet.killswitch")


class KillSwitchBase(abc.ABC):
    """Abstract base for all kill switch implementations.

    Subclasses must implement:
        - poll() — check for new messages, call on_message() for each
        - reply(text) — send a reply message back to the platform
    """

    def __init__(
        self,
        command: str,
        poll_interval: int,
        ledger: Ledger,
    ) -> None:
        self._command = command.upper()
        self._poll_interval = poll_interval
        self._ledger = ledger
        self._wallet: Wallet | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self, wallet: Wallet) -> None:
        """Start the background polling thread."""
        self._wallet = wallet
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name=f"killswitch-{wallet.name}",
        )
        self._thread.start()
        logger.info(
            f"Kill switch started for wallet '{wallet.name}' "
            f"(polling every {self._poll_interval}s)"
        )

    def stop(self) -> None:
        """Stop the background polling thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._poll_interval + 2)
        logger.info("Kill switch stopped")

    def _poll_loop(self) -> None:
        """Background loop that calls poll() at regular intervals."""
        while not self._stop_event.is_set():
            try:
                self.poll()
            except Exception as e:
                logger.warning(f"Kill switch poll error: {e}")
            self._stop_event.wait(self._poll_interval)

    def on_message(self, text: str) -> None:
        """Process an incoming message from the messaging platform.

        Supported commands:
            STOP <wallet> — pause the wallet
            RESUME <wallet> — resume the wallet
            STATUS — reply with all wallet statuses
        """
        text = text.strip()
        upper = text.upper()

        # Parse: STOP <wallet_name>
        stop_match = re.match(r"STOP\s+(\S+)", upper)
        if stop_match:
            wallet_name = stop_match.group(1)
            self._handle_stop(wallet_name)
            return

        # Parse: RESUME <wallet_name>
        resume_match = re.match(r"RESUME\s+(\S+)", upper)
        if resume_match:
            wallet_name = resume_match.group(1)
            self._handle_resume(wallet_name)
            return

        # Parse: STATUS
        if upper == "STATUS":
            self._handle_status()
            return

        # Also handle bare STOP (applies to the current wallet)
        if upper == self._command and self._wallet:
            self._handle_stop(self._wallet.name)
            return

    def _handle_stop(self, wallet_name: str) -> None:
        """Pause a wallet by name."""
        wallet_row = self._ledger.get_wallet_by_name(wallet_name)
        if not wallet_row:
            self.reply(f"❌ Unknown wallet: {wallet_name}")
            return

        wallet_id = wallet_row["id"]
        self._ledger.pause_wallet(wallet_id)
        self._ledger.log_kill_switch_event(
            wallet_id=wallet_id,
            platform=self.platform_name,
            command=f"STOP {wallet_name}",
            action="pause",
        )

        # Get today's spend for the reply
        from agent_wallet.policy import BudgetPeriod, BudgetPolicy

        policy = BudgetPolicy.from_json(wallet_row["policy"])
        period = BudgetPeriod(type="daily", limit_usd=0, reset_hour=0)
        since = policy.get_period_start(period)
        today_spend = self._ledger.get_spend_since(wallet_id, since)

        # Find daily limit
        daily_limit = next(
            (p.limit_usd for p in policy.periods if p.type == "daily"),
            0.0,
        )

        self.reply(
            f"✓ {wallet_name} paused. Budget: ${today_spend:.2f} / ${daily_limit:.2f} today."
        )
        logger.info(f"Kill switch: paused wallet '{wallet_name}'")

    def _handle_resume(self, wallet_name: str) -> None:
        """Resume a wallet by name."""
        wallet_row = self._ledger.get_wallet_by_name(wallet_name)
        if not wallet_row:
            self.reply(f"❌ Unknown wallet: {wallet_name}")
            return

        wallet_id = wallet_row["id"]
        self._ledger.resume_wallet(wallet_id)
        self._ledger.log_kill_switch_event(
            wallet_id=wallet_id,
            platform=self.platform_name,
            command=f"RESUME {wallet_name}",
            action="resume",
        )
        self.reply(f"✓ {wallet_name} resumed.")
        logger.info(f"Kill switch: resumed wallet '{wallet_name}'")

    def _handle_status(self) -> None:
        """Reply with all wallet statuses."""
        wallets = self._ledger.list_wallets()
        if not wallets:
            self.reply("No wallets found.")
            return

        from agent_wallet.policy import BudgetPeriod, BudgetPolicy

        lines = ["📊 Wallet Status:"]
        for w in wallets:
            policy = BudgetPolicy.from_json(w["policy"])
            period = BudgetPeriod(type="daily", limit_usd=0, reset_hour=0)
            since = policy.get_period_start(period)
            today_spend = self._ledger.get_spend_since(w["id"], since)

            daily_limit = next(
                (p.limit_usd for p in policy.periods if p.type == "daily"),
                0.0,
            )

            status = "⏸ PAUSED" if w["paused"] else "▶ active"
            lines.append(
                f"  {w['name']}: {status} — ${today_spend:.2f} / ${daily_limit:.2f} today"
            )

        self.reply("\n".join(lines))

    @property
    @abc.abstractmethod
    def platform_name(self) -> str:
        """Return the platform name (e.g. 'telegram', 'discord')."""
        ...

    @abc.abstractmethod
    def poll(self) -> None:
        """Poll for new messages. Call on_message() for each new message."""
        ...

    @abc.abstractmethod
    def reply(self, text: str) -> None:
        """Send a reply back to the platform."""
        ...
