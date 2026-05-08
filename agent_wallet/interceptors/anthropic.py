"""Anthropic SDK interceptor for agent-wallet.

Wraps the Anthropic client to enforce budget limits on every
messages.create() call. Supports both sync and async patterns.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_wallet.pricing import calculate_cost
from agent_wallet.wallet import Wallet

logger = logging.getLogger("agent_wallet.interceptors.anthropic")


class WrappedMessages:
    """Wraps anthropic.messages to intercept create() calls."""

    def __init__(self, messages: Any, wallet: Wallet) -> None:
        self._messages = messages
        self._wallet = wallet

    def create(self, **kwargs: Any) -> Any:
        """Intercept messages.create() with pre-flight/post-flight checks.

        1. Pre-flight: check budget, check paused, maybe downgrade model
        2. Original call: call the real Anthropic API
        3. Record spend: write SpendRecord to ledger (non-blocking on error)
        4. Post-flight: check if threshold crossed, trigger alert
        """
        # 1. Pre-flight — maybe downgrade model
        budget_pct = self._wallet.get_budget_pct()
        model = kwargs.get("model", "")
        downgraded_model = self._wallet.policy.maybe_downgrade(model, budget_pct)
        if downgraded_model != model:
            logger.info(f"Auto-downgrade: {model} → {downgraded_model}")
        kwargs["model"] = downgraded_model

        # Pre-flight — check budget (raises BudgetExceededError or WalletPausedError)
        self._wallet.check_budget_or_raise()

        # 2. Original call
        response = self._messages.create(**kwargs)

        # 3. Record spend (non-blocking on error)
        try:
            usage = response.usage
            cost = calculate_cost(
                provider="anthropic",
                model=downgraded_model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
            self._wallet.record_spend(
                provider="anthropic",
                model=downgraded_model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=cost,
            )
        except Exception as e:
            logger.warning(f"agent-wallet: failed to record spend: {e}")

        # 4. Post-flight alerts (non-blocking)
        self._wallet.maybe_alert_async()

        return response

    def __getattr__(self, name: str) -> Any:
        """Pass through any other attributes to the original messages object."""
        return getattr(self._messages, name)


class WrappedAnthropic:
    """Drop-in replacement for the Anthropic client with budget enforcement.

    Usage:
        client = Anthropic()
        wrapped = WrappedAnthropic(client, wallet)
        # Use wrapped exactly like client
        response = wrapped.messages.create(model="claude-sonnet-4-6", ...)
    """

    def __init__(self, client: Any, wallet: Wallet) -> None:
        self._client = client
        self._wallet = wallet
        self.messages = WrappedMessages(client.messages, wallet)

    def __getattr__(self, name: str) -> Any:
        """Pass through any other attributes to the original client."""
        return getattr(self._client, name)
