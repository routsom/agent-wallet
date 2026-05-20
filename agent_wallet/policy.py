"""Budget policy and auto-downgrade logic for agent-wallet.

Defines the data models for budget periods, auto-downgrade steps, alert
configuration, and the core BudgetPolicy class.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

logger = logging.getLogger("agent_wallet.policy")


@dataclass
class BudgetPeriod:
    """A budget limit for a specific time period."""

    type: str  # "daily" | "weekly" | "session" | "lifetime"
    limit_usd: float
    reset_hour: int = 0  # UTC hour for daily reset (default: midnight)


@dataclass
class AutoDowngradeStep:
    """Defines a model downgrade triggered at a budget threshold."""

    at_budget_pct: float  # trigger when this % of budget is spent
    from_model: str
    to_model: str
    provider: str


@dataclass
class AlertConfig:
    """Configuration for budget alert channels."""

    channels: list[str] = field(default_factory=list)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    discord_webhook_url: str | None = None
    webhook_url: str | None = None


@dataclass
class KillSwitchConfig:
    """Configuration for the kill switch mechanism."""

    platform: str  # "telegram" | "discord" | "webhook"
    command: str = "STOP"
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    discord_webhook_url: str | None = None
    webhook_url: str | None = None
    poll_interval_seconds: int = 5


@dataclass
class BudgetPolicy:
    """Defines the full budget policy for a wallet.

    Includes budget periods, alert thresholds, failure mode, and
    optional auto-downgrade rules.
    """

    periods: list[BudgetPeriod] = field(default_factory=list)
    alert_thresholds: list[float] = field(default_factory=lambda: [0.8, 1.0])
    fail_mode: str = "pause"  # "pause" | "error" | "downgrade"
    auto_downgrade: list[AutoDowngradeStep] | None = None

    def to_json(self) -> str:
        """Serialize policy to JSON string for storage."""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> BudgetPolicy:
        """Deserialize policy from JSON string."""
        raw = json.loads(data)
        return cls(
            periods=[BudgetPeriod(**p) for p in raw.get("periods", [])],
            alert_thresholds=raw.get("alert_thresholds", [0.8, 1.0]),
            fail_mode=raw.get("fail_mode", "pause"),
            auto_downgrade=[
                AutoDowngradeStep(**s) for s in raw["auto_downgrade"]
            ]
            if raw.get("auto_downgrade")
            else None,
        )

    def get_period_start(self, period: BudgetPeriod, now: datetime | None = None) -> str:
        """Calculate the ISO-8601 start timestamp for a given budget period."""
        now = now or datetime.now(UTC)

        if period.type == "daily":
            # Reset at the configured UTC hour
            start = now.replace(
                hour=period.reset_hour, minute=0, second=0, microsecond=0
            )
            if now < start:
                start -= timedelta(days=1)
            return start.isoformat()

        elif period.type == "weekly":
            # Monday at the configured hour
            days_since_monday = now.weekday()
            start = now.replace(
                hour=period.reset_hour, minute=0, second=0, microsecond=0
            ) - timedelta(days=days_since_monday)
            if now < start:
                start -= timedelta(weeks=1)
            return start.isoformat()

        elif period.type == "lifetime":
            return "1970-01-01T00:00:00+00:00"

        elif period.type == "session":
            # Session spend is handled separately via session_id
            return "1970-01-01T00:00:00+00:00"

        else:
            logger.warning(f"Unknown period type: {period.type}, treating as lifetime")
            return "1970-01-01T00:00:00+00:00"

    def maybe_downgrade(self, model: str, budget_pct: float) -> str:
        """Return the model to use, potentially downgraded based on spend %.

        If the requested model doesn't match any from_model in the downgrade
        chain, it passes through unchanged — never error, never block.
        """
        if not self.auto_downgrade:
            return model

        # Sort by at_budget_pct descending so we apply the highest applicable step
        sorted_steps = sorted(
            self.auto_downgrade, key=lambda s: s.at_budget_pct, reverse=True
        )

        for step in sorted_steps:
            if budget_pct >= step.at_budget_pct and model == step.from_model:
                logger.info(
                    f"Auto-downgrade: {step.from_model} → {step.to_model} "
                    f"(budget at {budget_pct:.0%})"
                )
                # Recursively check if the downgraded model also needs downgrading
                return self.maybe_downgrade(step.to_model, budget_pct)

        return model
