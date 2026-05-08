"""agent-wallet: Drop-in middleware for AI agent spending limits.

Public API:
    AgentWallet — convenience class to create a wallet and wrap a provider client.
    Wallet — core wallet class with budget enforcement.
    BudgetPolicy — budget period and downgrade configuration.
    BudgetExceededError — raised when budget is exceeded.
    WalletPausedError — raised when wallet is paused.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from agent_wallet.ledger import Ledger
from agent_wallet.policy import (
    AlertConfig,
    AutoDowngradeStep,
    BudgetPeriod,
    BudgetPolicy,
    KillSwitchConfig,
)
from agent_wallet.wallet import BudgetExceededError, Wallet, WalletPausedError

__all__ = [
    "AgentWallet",
    "AlertConfig",
    "AutoDowngradeStep",
    "BudgetExceededError",
    "BudgetPeriod",
    "BudgetPolicy",
    "KillSwitchConfig",
    "Ledger",
    "Wallet",
    "WalletPausedError",
]

logger = logging.getLogger("agent_wallet")


class AgentWallet:
    """Convenience class for the two-line setup pattern.

    Usage:
        wallet = AgentWallet(daily_limit_usd=5.00, kill_switch='telegram')
        client = wallet.wrap(Anthropic())
    """

    def __init__(
        self,
        name: str = "default",
        daily_limit_usd: float | None = None,
        weekly_limit_usd: float | None = None,
        session_limit_usd: float | None = None,
        lifetime_limit_usd: float | None = None,
        alert_thresholds: list[float] | None = None,
        fail_mode: str = "pause",
        auto_downgrade: list[AutoDowngradeStep] | None = None,
        kill_switch: str | KillSwitchConfig | None = None,
        alerts: str | AlertConfig | None = None,
        db_path: str | None = None,
        session_id: str | None = None,
        disabled: bool | None = None,
    ) -> None:
        # Check AGENT_WALLET_DISABLED
        if disabled is None:
            disabled = os.environ.get("AGENT_WALLET_DISABLED", "") == "1"
        self._disabled = disabled

        if self._disabled:
            logger.info("agent-wallet: disabled via AGENT_WALLET_DISABLED=1")
            self._wallet: Wallet | None = None
            return

        # Build budget periods
        periods: list[BudgetPeriod] = []
        if daily_limit_usd is not None:
            periods.append(BudgetPeriod(type="daily", limit_usd=daily_limit_usd))
        if weekly_limit_usd is not None:
            periods.append(BudgetPeriod(type="weekly", limit_usd=weekly_limit_usd))
        if session_limit_usd is not None:
            periods.append(BudgetPeriod(type="session", limit_usd=session_limit_usd))
        if lifetime_limit_usd is not None:
            periods.append(BudgetPeriod(type="lifetime", limit_usd=lifetime_limit_usd))

        policy = BudgetPolicy(
            periods=periods,
            alert_thresholds=alert_thresholds or [0.8, 1.0],
            fail_mode=fail_mode,
            auto_downgrade=auto_downgrade,
        )

        ledger = Ledger(db_path=db_path)

        # Build alerts
        alert_instances = _build_alerts(alerts)

        # Build kill switch
        ks_instance = _build_kill_switch(kill_switch, ledger)

        self._wallet = Wallet(
            name=name,
            policy=policy,
            ledger=ledger,
            session_id=session_id,
            alerts=alert_instances,
            kill_switch=ks_instance,
        )

    @property
    def wallet(self) -> Wallet | None:
        """Access the underlying Wallet instance."""
        return self._wallet

    def wrap(self, client: Any) -> Any:
        """Wrap a provider client with budget enforcement.

        Supports: Anthropic, OpenAI, Google GenerativeAI.
        If disabled, returns the client unchanged.
        """
        if self._disabled or self._wallet is None:
            return client

        client_type = type(client).__name__
        module = type(client).__module__ or ""

        # Anthropic
        if "anthropic" in module.lower() or client_type in ("Anthropic", "AsyncAnthropic"):
            from agent_wallet.interceptors.anthropic import WrappedAnthropic
            return WrappedAnthropic(client, self._wallet)

        # OpenAI
        if "openai" in module.lower() or client_type in ("OpenAI", "AsyncOpenAI"):
            from agent_wallet.interceptors.openai import WrappedOpenAI
            return WrappedOpenAI(client, self._wallet)

        # Google
        if "google" in module.lower() or "generativeai" in module.lower():
            from agent_wallet.interceptors.google import WrappedGoogle
            return WrappedGoogle(client, self._wallet)

        raise ValueError(
            f"Unsupported client type: {client_type} (module: {module}). "
            f"Supported: Anthropic, OpenAI, Google GenerativeAI."
        )

    def shutdown(self) -> None:
        """Stop background tasks and clean up."""
        if self._wallet:
            self._wallet.shutdown()

    def __enter__(self) -> AgentWallet:
        return self

    def __exit__(self, *args: Any) -> None:
        self.shutdown()


def _build_alerts(config: str | AlertConfig | None) -> list:  # type: ignore[type-arg]
    """Build alert instances from config."""
    if config is None:
        return []

    if isinstance(config, str):
        # Simple string like "telegram"
        config = AlertConfig(channels=[config])

    instances = []

    for channel in config.channels:
        if channel == "telegram":
            from agent_wallet.alerts.telegram import TelegramAlert

            instances.append(
                TelegramAlert(
                    bot_token=config.telegram_bot_token
                    or os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                    chat_id=config.telegram_chat_id
                    or os.environ.get("TELEGRAM_CHAT_ID", ""),
                )
            )
        elif channel == "discord":
            from agent_wallet.alerts.discord import DiscordAlert

            instances.append(
                DiscordAlert(
                    webhook_url=config.discord_webhook_url
                    or os.environ.get("DISCORD_WEBHOOK_URL", ""),
                )
            )
        elif channel == "webhook":
            from agent_wallet.alerts.webhook import WebhookAlert

            instances.append(
                WebhookAlert(
                    webhook_url=config.webhook_url or "",
                )
            )
        else:
            logger.warning(f"Unknown alert channel: {channel}")

    return instances


def _build_kill_switch(
    config: str | KillSwitchConfig | None,
    ledger: Ledger,
) -> Any:
    """Build a kill switch instance from config."""
    if config is None:
        return None

    if isinstance(config, str):
        config = KillSwitchConfig(platform=config)

    platform = config.platform

    if platform == "telegram":
        from agent_wallet.killswitch.telegram import TelegramKillSwitch

        return TelegramKillSwitch(
            bot_token=config.telegram_bot_token
            or os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            chat_id=config.telegram_chat_id
            or os.environ.get("TELEGRAM_CHAT_ID", ""),
            command=config.command,
            poll_interval=config.poll_interval_seconds,
            ledger=ledger,
        )
    elif platform == "discord":
        from agent_wallet.killswitch.discord import DiscordKillSwitch

        return DiscordKillSwitch(
            webhook_url=config.discord_webhook_url
            or os.environ.get("DISCORD_WEBHOOK_URL", ""),
            command=config.command,
            poll_interval=config.poll_interval_seconds,
            ledger=ledger,
        )
    elif platform == "webhook":
        from agent_wallet.killswitch.webhook import WebhookKillSwitch

        return WebhookKillSwitch(
            webhook_url=config.webhook_url or "",
            command=config.command,
            poll_interval=config.poll_interval_seconds,
            ledger=ledger,
        )
    else:
        logger.warning(f"Unknown kill switch platform: {platform}")
        return None
