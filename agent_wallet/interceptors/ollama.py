"""Ollama interceptor for agent-wallet.

Wraps the Ollama client to track token usage. Since Ollama is local,
costs are effectively zero, but token counting is still valuable for
budget-aware agents.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_wallet.pricing import calculate_cost
from agent_wallet.wallet import Wallet

logger = logging.getLogger("agent_wallet.interceptors.ollama")


class WrappedOllamaChat:
    """Wraps ollama chat() / generate() to intercept calls."""

    def __init__(self, client: Any, wallet: Wallet) -> None:
        self._client = client
        self._wallet = wallet

    def chat(self, **kwargs: Any) -> Any:
        """Intercept ollama.chat() with budget enforcement."""
        # 1. Pre-flight
        model = kwargs.get("model", "unknown")
        self._wallet.check_budget_or_raise()

        # 2. Original call
        response = self._client.chat(**kwargs)

        # 3. Record spend (non-blocking)
        try:
            # Ollama returns token counts in response
            input_tokens = 0
            output_tokens = 0

            if isinstance(response, dict):
                input_tokens = response.get("prompt_eval_count", 0) or 0
                output_tokens = response.get("eval_count", 0) or 0
            elif hasattr(response, "prompt_eval_count"):
                input_tokens = getattr(response, "prompt_eval_count", 0) or 0
                output_tokens = getattr(response, "eval_count", 0) or 0

            cost = calculate_cost(
                provider="ollama",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            self._wallet.record_spend(
                provider="ollama",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
            )
        except Exception as e:
            logger.warning(f"agent-wallet: failed to record spend: {e}")

        # 4. Post-flight alerts
        self._wallet.maybe_alert_async()

        return response

    def generate(self, **kwargs: Any) -> Any:
        """Intercept ollama.generate() with budget enforcement."""
        model = kwargs.get("model", "unknown")
        self._wallet.check_budget_or_raise()

        response = self._client.generate(**kwargs)

        try:
            input_tokens = 0
            output_tokens = 0

            if isinstance(response, dict):
                input_tokens = response.get("prompt_eval_count", 0) or 0
                output_tokens = response.get("eval_count", 0) or 0
            elif hasattr(response, "prompt_eval_count"):
                input_tokens = getattr(response, "prompt_eval_count", 0) or 0
                output_tokens = getattr(response, "eval_count", 0) or 0

            cost = calculate_cost(
                provider="ollama",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            self._wallet.record_spend(
                provider="ollama",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
            )
        except Exception as e:
            logger.warning(f"agent-wallet: failed to record spend: {e}")

        self._wallet.maybe_alert_async()

        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class WrappedOllama:
    """Drop-in replacement for the Ollama client with token tracking.

    Usage:
        import ollama
        from agent_wallet.interceptors.ollama import WrappedOllama

        wallet = Wallet(...)
        client = WrappedOllama(ollama, wallet)
        response = client.chat(model="llama3", messages=[...])
    """

    def __init__(self, client: Any, wallet: Wallet) -> None:
        self._inner = WrappedOllamaChat(client, wallet)
        self._client = client
        self._wallet = wallet

    def chat(self, **kwargs: Any) -> Any:
        return self._inner.chat(**kwargs)

    def generate(self, **kwargs: Any) -> Any:
        return self._inner.generate(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)
