"""Abstract base class for alert channels.

Alerts are fire-and-forget notifications sent when budget thresholds
are crossed. Errors in alert delivery must never block user code.
"""

from __future__ import annotations

import abc
import logging

logger = logging.getLogger("agent_wallet.alerts")


class AlertBase(abc.ABC):
    """Abstract base for all alert channel implementations.

    Subclasses must implement send() to deliver the alert message
    to the specific platform (Telegram, Discord, webhook, etc.).
    """

    @abc.abstractmethod
    def send(
        self,
        wallet_name: str,
        threshold_pct: float,
        budget_pct: float,
        spent_usd: float,
        limit_usd: float,
        period_type: str,
    ) -> None:
        """Send a budget threshold alert.

        Args:
            wallet_name: Name of the wallet that crossed the threshold.
            threshold_pct: The threshold that was crossed (e.g. 0.8 for 80%).
            budget_pct: Current budget utilisation percentage.
            spent_usd: Amount spent so far.
            limit_usd: Budget limit for the period.
            period_type: Type of budget period ("daily", "weekly", etc.).
        """
        ...

    def format_message(
        self,
        wallet_name: str,
        threshold_pct: float,
        budget_pct: float,
        spent_usd: float,
        limit_usd: float,
        period_type: str,
    ) -> str:
        """Format the alert message text."""
        emoji = "🔴" if budget_pct >= 1.0 else "🟡" if budget_pct >= 0.8 else "🟢"
        return (
            f"{emoji} agent-wallet alert\n"
            f"Wallet: {wallet_name}\n"
            f"Threshold: {threshold_pct:.0%} reached ({budget_pct:.0%} used)\n"
            f"Spent: ${spent_usd:.4f} / ${limit_usd:.2f} ({period_type})"
        )
