"""OpenAI SDK interceptor for agent-wallet.

Wraps the OpenAI client to enforce budget limits on every
chat.completions.create() call.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_wallet.pricing import calculate_cost
from agent_wallet.wallet import Wallet

logger = logging.getLogger("agent_wallet.interceptors.openai")


class WrappedCompletions:
    """Wraps openai.chat.completions to intercept create() calls."""

    def __init__(self, completions: Any, wallet: Wallet) -> None:
        self._completions = completions
        self._wallet = wallet

    def create(self, **kwargs: Any) -> Any:
        """Intercept chat.completions.create() with budget enforcement."""
        # 1. Pre-flight — maybe downgrade model
        budget_pct = self._wallet.get_budget_pct()
        model = kwargs.get("model", "")
        downgraded_model = self._wallet.policy.maybe_downgrade(model, budget_pct)
        if downgraded_model != model:
            logger.info(f"Auto-downgrade: {model} → {downgraded_model}")
        kwargs["model"] = downgraded_model

        # Pre-flight — check budget
        self._wallet.check_budget_or_raise()

        # 2. Original call
        response = self._completions.create(**kwargs)

        # 3. Record spend (non-blocking on error)
        try:
            usage = response.usage
            if usage:
                input_tokens = usage.prompt_tokens or 0
                output_tokens = usage.completion_tokens or 0
                cost = calculate_cost(
                    provider="openai",
                    model=downgraded_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                self._wallet.record_spend(
                    provider="openai",
                    model=downgraded_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                )
        except Exception as e:
            logger.warning(f"agent-wallet: failed to record spend: {e}")

        # 4. Post-flight alerts
        self._wallet.maybe_alert_async()

        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._completions, name)


class WrappedChat:
    """Wraps openai.chat to provide completions."""

    def __init__(self, chat: Any, wallet: Wallet) -> None:
        self._chat = chat
        self._wallet = wallet
        self.completions = WrappedCompletions(chat.completions, wallet)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._chat, name)


class WrappedOpenAI:
    """Drop-in replacement for the OpenAI client with budget enforcement.

    Usage:
        client = OpenAI()
        wrapped = WrappedOpenAI(client, wallet)
        response = wrapped.chat.completions.create(model="gpt-4o", ...)
    """

    def __init__(self, client: Any, wallet: Wallet) -> None:
        self._client = client
        self._wallet = wallet
        self.chat = WrappedChat(client.chat, wallet)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)
