"""Google Gemini interceptor for agent-wallet.

Wraps the Google GenerativeAI client to enforce budget limits on
generate_content() calls.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_wallet.pricing import calculate_cost
from agent_wallet.wallet import Wallet

logger = logging.getLogger("agent_wallet.interceptors.google")


class WrappedGenerativeModel:
    """Wraps a google.generativeai GenerativeModel to intercept generate_content()."""

    def __init__(self, model: Any, wallet: Wallet, model_name: str = "") -> None:
        self._model = model
        self._wallet = wallet
        self._model_name = model_name or getattr(model, "model_name", "unknown")

    def generate_content(self, *args: Any, **kwargs: Any) -> Any:
        """Intercept generate_content() with budget enforcement."""
        # 1. Pre-flight
        budget_pct = self._wallet.get_budget_pct()
        model_name = self._model_name
        downgraded = self._wallet.policy.maybe_downgrade(model_name, budget_pct)

        self._wallet.check_budget_or_raise()

        # 2. Original call
        response = self._model.generate_content(*args, **kwargs)

        # 3. Record spend (non-blocking)
        try:
            usage = getattr(response, "usage_metadata", None)
            if usage:
                input_tokens = getattr(usage, "prompt_token_count", 0) or 0
                output_tokens = getattr(usage, "candidates_token_count", 0) or 0
                cost = calculate_cost(
                    provider="google",
                    model=downgraded,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                self._wallet.record_spend(
                    provider="google",
                    model=downgraded,
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
        return getattr(self._model, name)


class WrappedGoogle:
    """Wraps the Google GenerativeAI module/client.

    Since Google's API uses GenerativeModel instances rather than a single client,
    this wrapper intercepts the GenerativeModel constructor.
    """

    def __init__(self, client: Any, wallet: Wallet) -> None:
        self._client = client
        self._wallet = wallet

    def GenerativeModel(self, model_name: str, **kwargs: Any) -> WrappedGenerativeModel:
        """Create a wrapped GenerativeModel with budget enforcement."""
        original = self._client.GenerativeModel(model_name, **kwargs)
        return WrappedGenerativeModel(original, self._wallet, model_name)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)
